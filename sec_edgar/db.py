"""SQLite store for normalized EDGAR financials."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik      INTEGER PRIMARY KEY,
    ticker   TEXT NOT NULL,
    name     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS filings (
    cik         INTEGER NOT NULL,
    accn        TEXT NOT NULL,
    form        TEXT NOT NULL,
    filed       TEXT,
    report_date TEXT,
    doc_url     TEXT,
    PRIMARY KEY (cik, accn)
);
CREATE TABLE IF NOT EXISTS facts (
    cik     INTEGER NOT NULL,
    metric  TEXT NOT NULL,
    frame   TEXT NOT NULL,
    year    INTEGER NOT NULL,
    quarter INTEGER NOT NULL,      -- 0 = annual
    value   REAL NOT NULL,
    form    TEXT,
    filed   TEXT,
    accn    TEXT,
    end     TEXT,
    source  TEXT NOT NULL DEFAULT 'xbrl',  -- 'xbrl' or 'research'
    PRIMARY KEY (cik, metric, frame, source)
);
CREATE TABLE IF NOT EXISTS research_overrides (
    cik     INTEGER NOT NULL,
    metric  TEXT NOT NULL,
    frame   TEXT NOT NULL,
    year    INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    value   REAL NOT NULL,
    source  TEXT,                  -- where the number came from
    note    TEXT,
    PRIMARY KEY (cik, metric, frame)
);
CREATE INDEX IF NOT EXISTS idx_facts_metric_frame ON facts(metric, frame);
CREATE INDEX IF NOT EXISTS idx_filings_cik_filed ON filings(cik, filed);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # WAL + NORMAL makes bulk-load commits cheap; final checkpoint on close.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def upsert_companies(con: sqlite3.Connection, companies: list[dict]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO companies (cik, ticker, name) VALUES (?,?,?)",
        [(c["cik"], c["ticker"], c["name"]) for c in companies],
    )
    con.commit()


def insert_facts(con: sqlite3.Connection, rows: list[dict]) -> int:
    con.executemany(
        """INSERT OR REPLACE INTO facts
           (cik, metric, frame, year, quarter, value, form, filed, accn, end, source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(r["cik"], r["metric"], r["frame"], r["year"], r["quarter"], r["value"],
          r.get("form"), r.get("filed"), r.get("accn"), r.get("end"),
          r.get("source", "xbrl")) for r in rows],
    )
    return len(rows)


def insert_filings(con: sqlite3.Connection, rows: list[dict]) -> int:
    con.executemany(
        """INSERT OR REPLACE INTO filings
           (cik, accn, form, filed, report_date, doc_url) VALUES (?,?,?,?,?,?)""",
        [(r["cik"], r["accn"], r["form"], r.get("filed"), r.get("report_date"),
          r.get("doc_url")) for r in rows if r["accn"]],
    )
    return len(rows)


def add_override(con: sqlite3.Connection, cik: int, metric: str, frame: str,
                 value: float, source: str = "", note: str = "") -> None:
    import re
    m = re.match(r"^CY(\d{4})(Q([1-4]))?I?$", frame)
    if not m:
        raise ValueError(f"bad frame: {frame}")
    year, q = int(m.group(1)), int(m.group(3) or 0)
    norm = f"CY{year}" + (f"Q{q}" if q else "")
    con.execute(
        """INSERT OR REPLACE INTO research_overrides
           (cik, metric, frame, year, quarter, value, source, note)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cik, metric, norm, year, q, value, source, note),
    )
    # also surface it in facts so queries see one unified series
    con.execute(
        """INSERT OR REPLACE INTO facts
           (cik, metric, frame, year, quarter, value, form, filed, accn, end, source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (cik, metric, norm, year, q, value, "research", None, None, None, "research"),
    )
    con.commit()


def _parse_one(args: tuple) -> tuple:
    """Parse a single company (runs in worker process). Returns
    (cik10, cik, fact_rows, filing_rows, has_xbrl)."""
    from .parse import parse_facts, parse_filings, load_company_files
    data_dir_s, co = args
    data_dir = Path(data_dir_s)
    cik10, cik = co["cik10"], co["cik"]
    facts_json, submissions, sub_files = load_company_files(data_dir, cik10)
    fact_rows = parse_facts(cik, facts_json) if facts_json else []
    filing_rows = parse_filings(cik, submissions, sub_files) if submissions else []
    return (cik10, cik, fact_rows, filing_rows, bool(facts_json))


def build_all(data_dir: str | Path, db_path: str | Path,
              progress_every: int = 500, workers: int = 0) -> dict:
    """Parse every downloaded company into the SQLite DB. Returns stats.

    workers>1 enables multiprocessing for the CPU-bound XBRL parsing;
    DB inserts stay serial in the parent process.
    """
    from .universe import load_universe
    import multiprocessing as mp

    data_dir, db_path = Path(data_dir), Path(db_path)
    companies = load_universe(data_dir / "tickers.json")
    con = connect(db_path)
    upsert_companies(con, companies)
    con.execute("CREATE TABLE IF NOT EXISTS _build_done (cik INTEGER PRIMARY KEY)")
    done = {r[0] for r in con.execute("SELECT cik FROM _build_done")}
    todo = [co for co in companies if co["cik"] not in done]
    if done:
        print(f"  resuming: {len(done)} already done, {len(todo)} to go", flush=True)

    if workers <= 1:
        from .parse import parse_facts, parse_filings, load_company_files
        def parse_iter():
            for co in todo:
                yield _parse_one((str(data_dir), co))
    else:
        pool = mp.Pool(workers)
        def parse_iter():
            try:
                yield from pool.imap_unordered(
                    _parse_one, [(str(data_dir), co) for co in todo],
                    chunksize=4)
            finally:
                pool.close()
                pool.join()

    stats = {"companies": 0, "facts": 0, "filings": 0, "no_xbrl": 0}
    for i, (cik10, cik, fact_rows, filing_rows, has_xbrl) in enumerate(parse_iter(), 1):
        if fact_rows:
            stats["facts"] += insert_facts(con, fact_rows)
        else:
            stats["no_xbrl"] += 1
        if filing_rows:
            stats["filings"] += insert_filings(con, filing_rows)
        con.execute("INSERT OR IGNORE INTO _build_done (cik) VALUES (?)", (cik,))
        stats["companies"] += 1
        if i % progress_every == 0:
            con.commit()
            print(f"  parsed {i}/{len(todo)} companies...", flush=True)
    con.commit()
    con.close()
    return stats
