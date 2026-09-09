"""Load reviewed Item 6 backfill values into the DB as research overrides.

Reads scripts/research_backfill/summaries/item6_summaries.json and inserts
each (ticker, year, metric) via db.add_override(), which records provenance
(source document + extraction note) and surfaces the value in `facts` with
source='research'. XBRL rows always win in queries (see query.get_facts).

Nothing here overwrites XBRL data: overrides live in research_overrides and
in facts rows with source='research', which get_facts() deprioritizes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from sec_edgar.db import connect, add_override
from sec_edgar.universe import load_universe

SUMMARIES = ROOT / "scripts" / "research_backfill" / "summaries" / "item6_summaries.json"

METRICS = {"revenue": "revenue", "net_income": "net_income", "assets": "assets"}

# human-review status per source key. Values verified against known company
# histories on 2026-09-09. Where two filings cover the same year with
# different (restated) numbers, the LATER filing wins (see load order below).
REVIEWED: dict[str, str] = {
    "AAPL_FY2003": "reviewed 2026-09-09: matches Apple history; 2003 ni $69M superseded by FY2007 $57M",
    "AAPL_FY2007": "reviewed 2026-09-09: matches Apple history",
    "CVX_FY2002": "reviewed 2026-09-09: matches Chevron history",
    "CVX_FY2003": "reviewed 2026-09-09: matches Chevron history",
    "CVX_FY2007": "reviewed 2026-09-09: matches Chevron history",
    "GE_FY2003": "reviewed 2026-09-09: pre-restatement basis; 2003 superseded by FY2007",
    "GE_FY2007": "reviewed 2026-09-09: restated basis; wins for 2003-2007",
    "HD_10YR": "reviewed 2026-09-09: matches Home Depot 10-year summary",
    "HD_FY2007": "reviewed 2026-09-09: matches Home Depot history; years are FY-end calendar years",
    "JNJ_FY2003": "reviewed 2026-09-09: from Summary of Operations 1993-2003; 2003 ni superseded by FY2007",
    "JNJ_FY2007": "reviewed 2026-09-09: matches J&J history; wins for 2003-2007",
    "JPM_FY2007": "reviewed 2026-09-09: matches JPMorgan history",
    "MSFT_FY2003": "reviewed 2026-09-09: pre-restatement; 2003 ni $9.99B superseded by FY2007 $7.53B",
    "MSFT_FY2007": "reviewed 2026-09-09: restated basis; wins for 2003-2007",
    "PG_FY2003": "reviewed 2026-09-09: from Financial Summary; 2003 ni superseded by FY2007",
    "PG_FY2007": "reviewed 2026-09-09: matches P&G history; wins for 2003-2007",
    "WMT_FY2003": "reviewed 2026-09-09: matches Walmart history",
    "WMT_FY2007": "reviewed 2026-09-09: matches Walmart history",
    "XOM_FY2003": "reviewed 2026-09-09: matches ExxonMobil history",
    "XOM_FY2007": "reviewed 2026-09-09: matches ExxonMobil history",
}

# load order: earlier filings first so later (restated) filings overwrite
# the same (ticker, year, metric) via INSERT OR REPLACE
LOAD_ORDER = [
    "HD_10YR",
    "AAPL_FY2003", "CVX_FY2002", "GE_FY2003", "JNJ_FY2003", "MSFT_FY2003",
    "PG_FY2003", "WMT_FY2003", "XOM_FY2003",
    "CVX_FY2003",
    "AAPL_FY2007", "CVX_FY2007", "GE_FY2007", "HD_FY2007", "JNJ_FY2007",
    "JPM_FY2007", "MSFT_FY2007", "PG_FY2007", "WMT_FY2007", "XOM_FY2007",
]


def main(db_path: str = "edgar.db", only_reviewed: bool = True):
    summaries = json.loads(SUMMARIES.read_text())
    unis = {u["ticker"]: u for u in load_universe(ROOT / "data" / "tickers.json")}
    con = connect(ROOT / db_path)
    n = 0
    keys = [k for k in LOAD_ORDER if k in summaries]
    keys += [k for k in sorted(summaries) if k not in keys]
    for key in keys:
        entry = summaries[key]
        ticker = entry["ticker"]
        if only_reviewed and key not in REVIEWED:
            print(f"SKIP {key}: not reviewed")
            continue
        co = unis.get(ticker)
        if not co:
            print(f"WARN: no CIK for {ticker}")
            continue
        cik = int(co["cik"])
        src = entry["source_doc"]
        for year_s, vals in entry["years"].items():
            year = int(year_s)
            for metric, mkey in METRICS.items():
                if metric not in vals:
                    continue
                note = (f"Item 6 / financial-statement backfill from {src}; "
                        f"filing FY{entry['filing_fy']}; parsed by parse_item6.py; "
                        f"status={REVIEWED.get(key, 'unreviewed')}")
                add_override(con, cik, mkey, f"CY{year}", float(vals[metric]),
                             source=f"EDGAR:{src}", note=note)
                n += 1
    print(f"loaded {n} research overrides into {db_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
