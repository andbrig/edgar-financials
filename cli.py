"""CLI: query the EDGAR financials database."""
from __future__ import annotations

import argparse
import sqlite3

from sec_edgar.db import connect
from sec_edgar import query as Q
from sec_edgar import gaps as G
from sec_edgar.taxonomy import METRICS


def money(v):
    if v is None:
        return "-"
    a = abs(v)
    s = "-" if v < 0 else ""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{s}${a/div:,.2f}{suf}"
    return f"{s}${a:,.0f}"


def main():
    ap = argparse.ArgumentParser(description="Query EDGAR financials")
    ap.add_argument("--db", default="edgar.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="find companies")
    p.add_argument("q")

    p = sub.add_parser("statements", help="annual statements for a ticker/CIK")
    p.add_argument("company")
    p.add_argument("--years", type=int, default=10)

    p = sub.add_parser("gaps", help="show data gaps for a ticker/CIK")
    p.add_argument("company")

    p = sub.add_parser("coverage", help="metric coverage across universe")

    args = ap.parse_args()
    con = connect(args.db)

    def resolve(ident: str) -> sqlite3.Row:
        rows = Q.search_companies(con, ident, limit=5)
        if not rows:
            raise SystemExit(f"no company matching {ident!r}")
        exact = [r for r in rows if r["ticker"].upper() == ident.upper()]
        return (exact or rows)[0]

    if args.cmd == "search":
        for r in Q.search_companies(con, args.q):
            print(f"{r['ticker']:8} {r['cik']:<10} {r['name']}")
    elif args.cmd == "statements":
        co = resolve(args.company)
        print(f"{co['ticker']} — {co['name']} (CIK {co['cik']})\n")
        for a in Q.annual_series(con, co["cik"])[:args.years]:
            m = a["metrics"]
            print(f"{a['year']}: rev={money(m.get('revenue'))} "
                  f"ni={money(m.get('net_income'))} "
                  f"assets={money(m.get('assets'))} "
                  f"equity={money(m.get('equity'))} "
                  f"cfo={money(m.get('cfo'))}")
    elif args.cmd == "gaps":
        co = resolve(args.company)
        missing = G.missing_annual_frames(con, co["cik"])
        if not missing:
            print("no gaps in XBRL range")
        for m, years in missing.items():
            print(f"{m:16} missing: {years}")
    elif args.cmd == "coverage":
        for c in Q.metric_coverage(con):
            print(f"{c['metric']:18} {c['companies']:6} companies  "
                  f"{c['first_year']}-{c['last_year']}")
    con.close()


if __name__ == "__main__":
    main()
