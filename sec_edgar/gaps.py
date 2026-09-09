"""Gap detection: find missing (company, metric, year) cells in the XBRL series.

The systematic gap: XBRL facts only exist from ~2009 (SEC phase-in 2009-2011),
so pre-2009 periods are missing for nearly every company. Gaps are reported
per company/metric; verified numbers can be backfilled via research_overrides.
"""
from __future__ import annotations

import sqlite3

from .taxonomy import METRICS


def company_year_range(con: sqlite3.Connection, cik: int) -> tuple[int, int] | None:
    r = con.execute(
        "SELECT MIN(year) AS a, MAX(year) AS b FROM facts WHERE cik = ? AND quarter = 0",
        (cik,)).fetchone()
    if r and r["a"]:
        return r["a"], r["b"]
    return None


def missing_annual_frames(con: sqlite3.Connection, cik: int,
                          metrics: list[str] | None = None) -> dict[str, list[int]]:
    """metric -> sorted list of missing years within the company's XBRL range."""
    rng = company_year_range(con, cik)
    if not rng:
        return {}
    lo, hi = rng
    metrics = metrics or [m for m, s in METRICS.items() if s["statement"] == "income"]
    have: dict[str, set[int]] = {m: set() for m in metrics}
    for r in con.execute(
            "SELECT metric, year FROM facts WHERE cik = ? AND quarter = 0 AND metric IN (%s)"
            % ",".join("?" * len(metrics)), (cik, *metrics)):
        have[r["metric"]].add(r["year"])
    expected = set(range(lo, hi + 1))
    return {m: sorted(expected - have[m]) for m in metrics if expected - have[m]}


def universe_gap_summary(con: sqlite3.Connection) -> dict:
    """High-level gap stats across all companies."""
    total = con.execute("SELECT COUNT(*) c FROM companies").fetchone()["c"]
    with_xbrl = con.execute(
        "SELECT COUNT(DISTINCT cik) c FROM facts WHERE source='xbrl'").fetchone()["c"]
    earliest = con.execute(
        "SELECT metric, MIN(year) y FROM facts WHERE source='xbrl' AND quarter=0 "
        "GROUP BY metric ORDER BY y LIMIT 5").fetchall()
    no_facts = con.execute(
        """SELECT c.ticker, c.name FROM companies c
           LEFT JOIN facts f ON f.cik = c.cik
           WHERE f.cik IS NULL LIMIT 20""").fetchall()
    return {
        "total_companies": total,
        "with_xbrl": with_xbrl,
        "without_xbrl": total - with_xbrl,
        "earliest_xbrl_years": [dict(r) for r in earliest],
        "sample_without_xbrl": [dict(r) for r in no_facts],
    }
