"""Query helpers: statements, trends, search."""
from __future__ import annotations

import sqlite3

from .taxonomy import METRICS, compute_ratios


def search_companies(con: sqlite3.Connection, q: str, limit: int = 20) -> list[sqlite3.Row]:
    q = q.strip()
    if q.isdigit():
        rows = con.execute(
            "SELECT * FROM companies WHERE cik = ? LIMIT ?", (int(q), limit)).fetchall()
        if rows:
            return rows
    like = f"%{q.upper()}%"
    return con.execute(
        """SELECT * FROM companies
           WHERE UPPER(ticker) LIKE ? OR UPPER(name) LIKE ?
           ORDER BY ticker LIMIT ?""",
        (like, like, limit)).fetchall()


def get_company(con: sqlite3.Connection, cik: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM companies WHERE cik = ?", (cik,)).fetchone()


def get_facts(con: sqlite3.Connection, cik: int) -> dict[str, dict[str, float]]:
    """metric -> {frame: value}. XBRL wins over research when both exist;
    research rows only fill gaps."""
    out: dict[str, dict[str, float]] = {}
    for r in con.execute(
            """SELECT metric, frame, value FROM facts WHERE cik = ?
               ORDER BY CASE source WHEN 'research' THEN 0 ELSE 1 END""",
            (cik,)):
        out.setdefault(r["metric"], {})[r["frame"]] = r["value"]
    # Research backfills fill (metric, frame) gaps XBRL doesn't cover.
    for r in con.execute(
            "SELECT metric, frame, value FROM research_overrides WHERE cik = ?",
            (cik,)):
        out.setdefault(r["metric"], {}).setdefault(r["frame"], r["value"])
    return out


def annual_series(con: sqlite3.Connection, cik: int) -> list[dict]:
    """Annual frames, newest first: [{frame, year, metrics{...}, ratios{...}}]."""
    facts = get_facts(con, cik)
    frames = sorted({f for m in facts.values() for f in m if f and "Q" not in f},
                    reverse=True)
    series = []
    for fr in frames:
        year = int(fr[2:])
        metrics = {m: facts[m][fr] for m in facts if fr in facts[m]}
        series.append({"frame": fr, "year": year, "metrics": metrics,
                       "ratios": compute_ratios(metrics)})
    return series


def quarterly_series(con: sqlite3.Connection, cik: int, metric: str,
                     limit: int = 40) -> list[dict]:
    rows = con.execute(
        """SELECT frame, year, quarter, value, source FROM facts
           WHERE cik = ? AND metric = ? AND quarter > 0
           ORDER BY year DESC, quarter DESC LIMIT ?""",
        (cik, metric, limit)).fetchall()
    return [dict(r) for r in rows][::-1]


def metric_coverage(con: sqlite3.Connection) -> list[dict]:
    """How many companies have each metric (annual)."""
    rows = con.execute(
        """SELECT metric, COUNT(DISTINCT cik) AS companies,
                  MIN(year) AS first_year, MAX(year) AS last_year
           FROM facts WHERE quarter = 0 GROUP BY metric ORDER BY companies DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def recent_filings(con: sqlite3.Connection, cik: int, limit: int = 25) -> list[dict]:
    rows = con.execute(
        """SELECT form, filed, report_date, doc_url FROM filings
           WHERE cik = ? ORDER BY filed DESC LIMIT ?""",
        (cik, limit)).fetchall()
    return [dict(r) for r in rows]
