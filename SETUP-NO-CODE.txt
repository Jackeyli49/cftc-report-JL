#!/usr/bin/env python3
"""Download official CFTC COT files and build data/reports.json.

Uses only the Python standard library so it runs on GitHub Actions without
installing packages. The script is intentionally resilient: when the current
week is delayed, it keeps the newest available official report.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import statistics
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reports.json"
YEARS_BACK = int(os.getenv("CFTC_YEARS_BACK", "4"))
TIMEOUT = 60

DISAGG_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
TFF_URL = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"

# Match official CFTC market names. More-specific expressions should come first.
DISAGG_ASSETS = [
    ("Energy", "WTI Crude Oil", [r"CRUDE OIL, LIGHT SWEET", r"WTI.*CRUDE"]),
    ("Energy", "Natural Gas", [r"NATURAL GAS - NEW YORK", r"HENRY HUB.*NATURAL GAS"]),
    ("Energy", "RBOB Gasoline", [r"GASOLINE BLENDSTOCK", r"RBOB GASOLINE"]),
    ("Energy", "Heating Oil", [r"NO\. 2 HEATING OIL", r"NY HARBOR ULSD"]),
    ("Metals", "Gold", [r"GOLD - COMMODITY EXCHANGE"]),
    ("Metals", "Silver", [r"SILVER - COMMODITY EXCHANGE"]),
    ("Metals", "Copper", [r"COPPER-GRADE #1", r"COPPER - COMMODITY EXCHANGE"]),
    ("Agriculture", "Corn", [r"CORN - CHICAGO BOARD"]),
    ("Agriculture", "Soybeans", [r"SOYBEANS - CHICAGO BOARD"]),
    ("Agriculture", "Wheat", [r"WHEAT-SRW", r"WHEAT - CHICAGO BOARD"]),
]

TFF_ASSETS = [
    ("Equity Indices", "S&P 500", [r"E-MINI S&P 500"]),
    ("Equity Indices", "Nasdaq 100", [r"NASDAQ-100", r"NASDAQ 100"]),
    ("Equity Indices", "Russell 2000", [r"RUSSELL 2000"]),
    ("Rates", "US 2-Year Treasury", [r"2-YEAR U\.S\. TREASURY", r"2-YEAR TREASURY"]),
    ("Rates", "US 5-Year Treasury", [r"5-YEAR U\.S\. TREASURY", r"5-YEAR TREASURY"]),
    ("Rates", "US 10-Year Treasury", [r"10-YEAR U\.S\. TREASURY", r"10-YEAR TREASURY"]),
    ("Rates", "US Treasury Bond", [r"U\.S\. TREASURY BONDS"]),
    ("FX / Crypto", "EUR/USD", [r"EURO FX"]),
    ("FX / Crypto", "GBP/USD", [r"BRITISH POUND"]),
    ("FX / Crypto", "JPY/USD", [r"JAPANESE YEN"]),
    ("FX / Crypto", "Bitcoin", [r"BITCOIN"]),
]


def download_zip(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CFTC-dashboard-updater/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse_zip_csv(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))]
        if not names:
            raise RuntimeError("CFTC zip did not contain a text/CSV file")
        raw = zf.read(names[0])
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def clean_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def get(row: dict[str, str], *candidates: str, default: str = "") -> str:
    normalized = {clean_key(k): v for k, v in row.items() if k is not None}
    for candidate in candidates:
        if clean_key(candidate) in normalized:
            return normalized[clean_key(candidate)]
    return default


def number(value: str | None) -> float:
    if value is None:
        return 0.0
    value = str(value).strip().replace(",", "")
    if value in {"", ".", "-"}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def report_date(row: dict[str, str]) -> str:
    raw = get(row, "As_of_Date_Form_YYYY-MM-DD", "Report_Date_as_MM_DD_YYYY", "As_of_Date_In_Form_YYMMDD")
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m_%d_%Y", "%y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized CFTC report date: {raw!r}")


def match_asset(market: str, definitions: list[tuple[str, str, list[str]]]):
    market = market.upper().strip()
    for category, label, patterns in definitions:
        if any(re.search(pattern, market, flags=re.I) for pattern in patterns):
            return category, label
    return None


def zscore(values: list[float], idx: int, window: int = 156) -> float:
    start = max(0, idx - window + 1)
    sample = values[start : idx + 1]
    if len(sample) < 20:
        return 0.0
    sd = statistics.pstdev(sample)
    return 0.0 if sd == 0 else (values[idx] - statistics.mean(sample)) / sd


def action(long_change: float, short_change: float) -> str:
    if long_change > 0 and short_change < 0:
        return "Long Building / Short Covering"
    if long_change < 0 and short_change > 0:
        return "Long Liquidation / Short Building"
    if long_change > 0 and short_change > 0:
        return "Long & Short Building"
    if long_change < 0 and short_change < 0:
        return "Long & Short Liquidation"
    if long_change > 0:
        return "Long Building"
    if long_change < 0:
        return "Long Liquidation"
    if short_change > 0:
        return "Short Building"
    if short_change < 0:
        return "Short Covering"
    return ""


def crowd(net_z: float, long_z: float, short_z: float, net: float) -> str:
    strongest = max((abs(net_z), "net"), (abs(long_z), "long"), (abs(short_z), "short"))[0]
    if strongest < 2.0:
        return ""
    side = "Long" if net >= 0 else "Short"
    return ("Extreme " if strongest >= 2.75 else "Crowded ") + side


def extract_series(rows: Iterable[dict[str, str]], kind: str) -> dict[str, list[dict]]:
    definitions = DISAGG_ASSETS if kind == "managed" else TFF_ASSETS
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        market = get(row, "Market_and_Exchange_Names")
        match = match_asset(market, definitions)
        if not match:
            continue
        category, asset = match
        oi = number(get(row, "Open_Interest_All"))
        if oi <= 0:
            continue
        if kind == "managed":
            long_pos = number(get(row, "M_Money_Positions_Long_All"))
            short_pos = number(get(row, "M_Money_Positions_Short_All"))
        else:
            long_pos = number(get(row, "Lev_Money_Positions_Long_All"))
            short_pos = number(get(row, "Lev_Money_Positions_Short_All"))
        grouped[asset].append({
            "date": report_date(row), "category": category, "asset": asset,
            "oi": oi, "long": long_pos, "short": short_pos, "net": long_pos - short_pos,
        })
    for asset in grouped:
        # Deduplicate by date, then sort chronologically.
        grouped[asset] = sorted({x["date"]: x for x in grouped[asset]}.values(), key=lambda x: x["date"])
    return grouped


def build_metrics(series: dict[str, list[dict]]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for asset, items in series.items():
        net_ratios = [x["net"] / x["oi"] for x in items]
        long_ratios = [x["long"] / x["oi"] for x in items]
        short_ratios = [x["short"] / x["oi"] for x in items]
        net_changes = [0.0] + [items[i]["net"] - items[i-1]["net"] for i in range(1, len(items))]
        long_changes = [0.0] + [items[i]["long"] - items[i-1]["long"] for i in range(1, len(items))]
        short_changes = [0.0] + [items[i]["short"] - items[i-1]["short"] for i in range(1, len(items))]
        output = []
        for i, x in enumerate(items):
            nz, lz, sz = zscore(net_ratios, i), zscore(long_ratios, i), zscore(short_ratios, i)
            output.append({
                **x,
                "netZ": round(nz, 2), "longZ": round(lz, 2), "shortZ": round(sz, 2),
                "netChange": round(net_changes[i]), "longChange": round(long_changes[i]), "shortChange": round(short_changes[i]),
                "netChangeZ": round(zscore(net_changes, i), 2),
                "longChangeZ": round(zscore(long_changes, i), 2),
                "shortChangeZ": round(zscore(short_changes, i), 2),
                "action": action(long_changes[i], short_changes[i]),
                "crowding": crowd(nz, lz, sz, x["net"]),
                "priceChange": None,
            })
        result[asset] = output
    return result


def collect(kind: str, years: range) -> list[dict[str, str]]:
    template = DISAGG_URL if kind == "managed" else TFF_URL
    rows: list[dict[str, str]] = []
    errors = []
    for year in years:
        url = template.format(year=year)
        try:
            print(f"Downloading {url}")
            rows.extend(parse_zip_csv(download_zip(url)))
        except Exception as exc:
            errors.append(f"{year}: {exc}")
            print(f"Warning: could not load {year}: {exc}")
    if not rows:
        raise RuntimeError(f"No {kind} data downloaded. " + "; ".join(errors))
    return rows


def main() -> None:
    current_year = date.today().year
    years = range(current_year - YEARS_BACK, current_year + 1)
    managed = build_metrics(extract_series(collect("managed", years), "managed"))
    leveraged = build_metrics(extract_series(collect("leveraged", years), "leveraged"))

    reports: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"leveraged": [], "managed": []})
    for kind, dataset in (("leveraged", leveraged), ("managed", managed)):
        for items in dataset.values():
            for item in items:
                reports[item["date"]][kind].append(item)

    # Only publish dates that contain at least one tracked market.
    clean_reports = {}
    for d, report in sorted(reports.items(), reverse=True):
        for kind in ("leveraged", "managed"):
            report[kind].sort(key=lambda x: (x["category"], x["asset"]))
        if report["leveraged"] or report["managed"]:
            clean_reports[d] = report

    if not clean_reports:
        raise RuntimeError("No tracked CFTC markets found; market-name mappings may need updating")

    payload = {
        "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "latestDate": next(iter(clean_reports)),
        "source": "U.S. Commodity Futures Trading Commission",
        "priceDataIncluded": False,
        "reports": clean_reports,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Wrote {OUT} with {len(clean_reports)} report dates; latest={payload['latestDate']}")


if __name__ == "__main__":
    main()
