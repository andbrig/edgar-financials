"""Benchmark assertions for bellwether companies.

Verifies the production DB returns known-good values (XBRL + research overrides).
Tolerances are generous: these catch systemic breakage, not rounding.

Known gap (documented): ticker XOM maps per the SEC ticker file to CIK 2115436
('ExxonMobil Holdings Corp'), which carries almost no XBRL facts. The classic
Exxon Mobil Corp CIK 34088 is absent from the current SEC ticker universe, so
no XOM assertions are made here.
"""
import sys

from sec_edgar.db import connect
from sec_edgar import query as Q

DB = "edgar.db"
B = 1e9

# (ticker, cik, metric, frame, expected, tolerance)
CASES = [
    # Apple — XBRL recent + researched pre-XBRL
    ("AAPL", 320193, "revenue", "CY2025", 416.161 * B, 1.0 * B),
    ("AAPL", 320193, "net_income", "CY2025", 112.010 * B, 0.5 * B),
    ("AAPL", 320193, "assets", "CY2025", 359.241 * B, 1.0 * B),
    ("AAPL", 320193, "net_income", "CY2003", 57e6, 5e6),      # researched/restated
    ("AAPL", 320193, "revenue", "CY2003", 6.207 * B, 0.05 * B),
    # Microsoft
    ("MSFT", 789019, "revenue", "CY2025", 281.724 * B, 1.0 * B),
    ("MSFT", 789019, "assets", "CY2025", 619.003 * B, 1.0 * B),
    ("MSFT", 789019, "net_income", "CY2003", 7.531 * B, 0.05 * B),
    # JPMorgan Chase — 2024: rev ~177.9B GAAP, ni 58.5B, assets ~4.00T
    ("JPM", 19617, "revenue", "CY2024", 177.9 * B, 3.0 * B),
    ("JPM", 19617, "net_income", "CY2024", 58.5 * B, 1.0 * B),
    ("JPM", 19617, "assets", "CY2024", 4000 * B, 50 * B),
    # GE (post-spinoff GE Aerospace) — 2024
    ("GE", 40545, "revenue", "CY2024", 38.7 * B, 1.0 * B),
    ("GE", 40545, "net_income", "CY2024", 6.6 * B, 0.5 * B),
    # Walmart FY2025 (filed as CY2024 frame)
    ("WMT", 104169, "revenue", "CY2024", 680.9 * B, 10.0 * B),
    ("WMT", 104169, "net_income", "CY2024", 19.4 * B, 1.0 * B),
    # Home Depot FY2024
    ("HD", 354950, "revenue", "CY2024", 159.5 * B, 2.0 * B),
    ("HD", 354950, "net_income", "CY2024", 14.8 * B, 0.5 * B),
    # Johnson & Johnson — 2024
    ("JNJ", 200406, "revenue", "CY2024", 88.8 * B, 1.0 * B),
    ("JNJ", 200406, "net_income", "CY2024", 14.1 * B, 0.5 * B),
    # Procter & Gamble FY2024
    ("PG", 80424, "revenue", "CY2024", 84.0 * B, 1.0 * B),
    ("PG", 80424, "net_income", "CY2024", 14.9 * B, 0.5 * B),
]


def main():
    con = connect(DB)
    fails = 0
    for ticker, cik, metric, frame, expected, tol in CASES:
        facts = Q.get_facts(con, cik)
        actual = facts.get(metric, {}).get(frame)
        if actual is None:
            print(f"FAIL {ticker} {metric} {frame}: missing (expected {expected/1e9:.2f}B)")
            fails += 1
        elif abs(actual - expected) > tol:
            print(f"FAIL {ticker} {metric} {frame}: got {actual/1e9:.3f}B, "
                  f"expected {expected/1e9:.3f}B ± {tol/1e9:.2f}B")
            fails += 1
        else:
            print(f"ok   {ticker} {metric} {frame} = {actual/1e9:.3f}B")
    con.close()
    print(f"\n{len(CASES)-fails}/{len(CASES)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
