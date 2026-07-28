name: Update CFTC data

on:
  workflow_dispatch:
  schedule:
    # CFTC normally publishes Friday at 3:30 p.m. ET. Run after release,
    # then retry Saturday in case of a delay or a transient network error.
    - cron: "17 22 * * 5"
    - cron: "17 10 * * 6"

permissions:
  contents: write

concurrency:
  group: cftc-weekly-update
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Download and process official CFTC data
        run: python scripts/update_cftc.py
      - name: Commit new report when changed
        run: |
          if git diff --quiet -- data/reports.json; then
            echo "No new CFTC report is available yet."
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/reports.json
          git commit -m "Update CFTC report data"
          git push
