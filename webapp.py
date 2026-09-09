"""EDGAR Financials dashboard."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, jsonify

from sec_edgar.db import connect
from sec_edgar import query as Q
from sec_edgar import gaps as G
from sec_edgar.taxonomy import METRICS, RATIO_LABELS

DB_PATH = os.environ.get("EDGAR_DB", str(Path(__file__).parent / "edgar.db"))

app = Flask(__name__)


def db() -> sqlite3.Connection:
    return connect(DB_PATH)


def fmt_money(v):
    if v is None:
        return "-"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}${a/1e12:,.2f}T"
    if a >= 1e9:
        return f"{sign}${a/1e9:,.2f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:,.1f}M"
    if a >= 1e3:
        return f"{sign}${a/1e3:,.0f}K"
    return f"{sign}${a:,.0f}"


def fmt_ratio(v):
    if v is None:
        return "-"
    return f"{v*100:,.1f}%" if abs(v) < 10 else f"{v:,.2f}x"


app.jinja_env.filters["money"] = fmt_money
app.jinja_env.filters["ratio"] = fmt_ratio


@app.route("/")
def index():
    con = db()
    q = request.args.get("q", "").strip()
    results = Q.search_companies(con, q) if q else []
    coverage, gap = _cached_stats(con)
    con.close()
    return render_template("index.html", q=q, results=results,
                           coverage=coverage, gap=gap)


def _cached_stats(con):
    """Precomputed dashboard stats (built by scripts/build_stats.py);
    falls back to live queries if the cache table is empty."""
    import json
    row = con.execute(
        "SELECT value FROM dashboard_stats WHERE key='coverage'").fetchone()
    if row:
        coverage = json.loads(row[0])
        gap = {
            "total_companies": _stat(con, "total_companies"),
            "with_xbrl": _stat(con, "with_xbrl"),
            "without_xbrl": _stat(con, "total_companies") - _stat(con, "with_xbrl"),
            "earliest_xbrl_years": json.loads(
                con.execute("SELECT value FROM dashboard_stats WHERE key='earliest'"
                            ).fetchone()[0]),
            "sample_without_xbrl": [],
        }
        return coverage, gap
    coverage = Q.metric_coverage(con)
    gap = G.universe_gap_summary(con)
    return coverage, gap


def _stat(con, key):
    import json
    r = con.execute("SELECT value FROM dashboard_stats WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else 0


@app.route("/c/<int:cik>")
def company(cik: int):
    con = db()
    co = Q.get_company(con, cik)
    if not co:
        con.close()
        return "Unknown company", 404
    annual = Q.annual_series(con, cik)
    filings = Q.recent_filings(con, cik)
    missing = G.missing_annual_frames(con, cik)
    con.close()

    statements = [("income", "Income Statement"),
                  ("balance", "Balance Sheet"),
                  ("cashflow", "Cash Flow")]
    metrics_by_stmt = {}
    for key, _label in statements:
        metrics_by_stmt[key] = [(m, s["label"]) for m, s in METRICS.items()
                                if s["statement"] == key]
    trend = {
        "years": [a["year"] for a in annual][::-1],
        "revenue": [a["metrics"].get("revenue") for a in annual][::-1],
        "net_income": [a["metrics"].get("net_income") for a in annual][::-1],
        "equity": [a["metrics"].get("equity") for a in annual][::-1],
    }
    return render_template("company.html", co=co, annual=annual,
                           statements=statements, metrics_by_stmt=metrics_by_stmt,
                           ratio_labels=RATIO_LABELS, filings=filings,
                           missing=missing, trend=trend)


@app.route("/gaps")
def gaps():
    con = db()
    _, gap = _cached_stats(con)
    con.close()
    return render_template("gaps.html", summary=gap)


@app.route("/api/search")
def api_search():
    con = db()
    rows = Q.search_companies(con, request.args.get("q", ""))
    con.close()
    return jsonify([{"cik": r["cik"], "ticker": r["ticker"], "name": r["name"]}
                    for r in rows])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5057)), debug=False)
