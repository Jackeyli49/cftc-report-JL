from __future__ import annotations
import csv, io, json, math, statistics, zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reports.json"
YEARS = range(datetime.now(timezone.utc).year - 3, datetime.now(timezone.utc).year + 1)
SOURCES = {
    "Managed Money": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    "Leveraged Funds": "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
}
ALIASES = {
    "CRUDE OIL, LIGHT SWEET": ("WTI Crude Oil", "Energy"),
    "NATURAL GAS": ("Natural Gas", "Energy"),
    "GASOLINE BLENDSTOCK": ("RBOB Gasoline", "Energy"),
    "NO. 2 HEATING OIL": ("Heating Oil", "Energy"),
    "GOLD": ("Gold", "Metals"), "SILVER": ("Silver", "Metals"), "COPPER": ("Copper", "Metals"),
    "CORN": ("Corn", "Agriculture"), "SOYBEANS": ("Soybeans", "Agriculture"), "WHEAT": ("Wheat", "Agriculture"),
    "EURO FX": ("Euro FX", "FX"), "BRITISH POUND": ("British Pound", "FX"), "JAPANESE YEN": ("Japanese Yen", "FX"),
    "E-MINI S&P 500": ("E-mini S&P 500", "Equity Index"), "NASDAQ-100": ("Nasdaq-100", "Equity Index"),
    "10-YEAR U.S. TREASURY NOTES": ("US 10Y Treasury", "Rates"),
}

def num(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            try: return int(float(str(v).replace(",", "")))
            except ValueError: pass
    return 0

def date_value(row):
    for n in ("Report_Date_as_YYYY-MM-DD", "As_of_Date_In_Form_YYMMDD"):
        v = row.get(n)
        if v:
            for f in ("%Y-%m-%d", "%y%m%d"):
                try: return datetime.strptime(v.strip(), f).date().isoformat()
                except ValueError: pass
    return ""

def fetch_zip(url):
    r=requests.get(url,timeout=60,headers={"User-Agent":"FlowAlpha/1.0"}); r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name=next(n for n in z.namelist() if n.lower().endswith((".txt",".csv")))
        raw=z.read(name).decode("utf-8-sig",errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))

def market_alias(name):
    upper=name.upper()
    for key,val in ALIASES.items():
        if key in upper:return val
    return None

def fields(group):
    if group=="Managed Money": return ("M_Money_Positions_Long_All", "M_Money_Positions_Short_All")
    return ("Lev_Money_Positions_Long_All", "Lev_Money_Positions_Short_All")

def main():
    combined=[]
    for group,template in SOURCES.items():
        rows=[]
        for year in YEARS:
            try: rows.extend(fetch_zip(template.format(year=year)))
            except Exception as e: print(f"Skipping {group} {year}: {e}")
        lf,sf=fields(group)
        series={}
        for r in rows:
            name=(r.get("Market_and_Exchange_Names") or "").strip(); alias=market_alias(name); dt=date_value(r)
            if not alias or not dt: continue
            long=num(r,lf); short=num(r,sf); oi=num(r,"Open_Interest_All")
            series.setdefault((name,alias[0],alias[1]),[]).append({"date":dt,"long":long,"short":short,"net":long-short,"oi":oi})
        for (name,short_name,category),vals in series.items():
            vals=sorted({v["date"]:v for v in vals}.values(),key=lambda x:x["date"])
            if not vals:continue
            cur=vals[-1]; prev=vals[-2] if len(vals)>1 else cur
            ratios=[v["net"]/v["oi"]*100 for v in vals[-156:] if v["oi"]]
            cur_ratio=cur["net"]/cur["oi"]*100 if cur["oi"] else 0
            z=0
            if len(ratios)>=8 and statistics.pstdev(ratios)>0:z=(cur_ratio-statistics.mean(ratios))/statistics.pstdev(ratios)
            lc=cur["long"]-prev["long"]; sc=cur["short"]-prev["short"]
            if lc>0 and sc<0: signal="Long building / short covering"
            elif lc<0 and sc>0: signal="Long liquidation / short building"
            elif lc>0 and sc>0: signal="Longs and shorts both increased"
            elif lc<0 and sc<0: signal="Longs and shorts both decreased"
            else: signal="Positioning broadly unchanged"
            combined.append({"category":category,"market":name,"shortName":short_name,"group":group,"long":cur["long"],"short":cur["short"],"net":cur["net"],"longChange":lc,"shortChange":sc,"netChange":cur["net"]-prev["net"],"openInterest":cur["oi"],"netOiPct":round(cur_ratio,2),"zScore":round(z,2),"signal":signal,"date":cur["date"]})
    latest=max((x["date"] for x in combined),default="")
    combined=[x for x in combined if x["date"]==latest]
    for x in combined:x.pop("date",None)
    combined.sort(key=lambda x:(x["category"],x["shortName"],x["group"]))
    payload={"generatedAt":datetime.now(timezone.utc).isoformat(),"latestDate":latest,"source":"U.S. Commodity Futures Trading Commission","markets":combined}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(f"Wrote {len(combined)} rows for {latest}")
if __name__=="__main__":main()
