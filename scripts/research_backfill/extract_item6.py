"""Extract Item 6 (Selected Financial Data) tables from pre-XBRL 10-Ks.

Usage: python extract_item6.py TICKER FY [FY ...]
  e.g. python extract_item6.py AAPL 2003 2007

Finds the 10-K for each fiscal year via the EDGAR submissions API, downloads
the primary document, and dumps candidate financial tables to text files for
human review. Nothing is written to the database by this script.
"""
from __future__ import annotations

import io
import re
import sys
import json
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_edgar.universe import load_universe, cik10
from sec_edgar.client import get_json, USER_AGENT

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
TABLES = ROOT / "tables"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

TARGETS = ["AAPL", "MSFT", "GE", "XOM", "WMT", "JNJ", "PG", "JPM", "CVX", "HD"]


def find_10k_docs(ticker: str, fys: list[int]) -> dict[int, dict]:
    unis = {u["ticker"]: u for u in load_universe(ROOT.parent / "data" / "tickers.json")}
    co = unis[ticker]
    sub = get_json(SUBMISSIONS_URL.format(cik10=co["cik10"]))
    if not sub:
        raise SystemExit(f"no submissions for {ticker}")
    recent = (sub.get("filings") or {}).get("recent") or {}
    out: dict[int, dict] = {}
    forms = recent.get("form") or []
    for i, form in enumerate(forms):
        if form not in ("10-K", "10-K/A"):
            continue
        rd = (recent.get("reportDate") or [""])[i] or ""
        accn = (recent.get("accessionNumber") or [""])[i] or ""
        doc = (recent.get("primaryDocument") or [""])[i] or ""
        try:
            fy = int(rd[:4])
        except ValueError:
            continue
        if fy in fys and fy not in out and accn and doc:
            nodash = accn.replace("-", "")
            out[fy] = {
                "url": f"https://www.sec.gov/Archives/edgar/data/{co['cik']}/{nodash}/{doc}",
                "accn": accn, "report_date": rd, "form": form,
            }
    # fall back to sub-files for older filings if not all found
    if len(out) < len(fys):
        for f in (sub.get("filings") or {}).get("files", []):
            doc = get_json(f"https://data.sec.gov/submissions/{f['name']}")
            if not doc:
                continue
            forms = doc.get("form") or []
            for i, form in enumerate(forms):
                if form not in ("10-K", "10-K/A"):
                    continue
                rd = (doc.get("reportDate") or [""])[i] or ""
                accn = (doc.get("accessionNumber") or [""])[i] or ""
                pdoc = (doc.get("primaryDocument") or [""])[i] or ""
                try:
                    fy = int(rd[:4])
                except ValueError:
                    continue
                if fy in fys and fy not in out and accn and pdoc:
                    nodash = accn.replace("-", "")
                    out[fy] = {
                        "url": f"https://www.sec.gov/Archives/edgar/data/{co['cik']}/{nodash}/{pdoc}",
                        "accn": accn, "report_date": rd, "form": form,
                    }
    return out


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    r = requests.get(url, headers={"User-Agent": USER_AGENT,
                                   "Accept-Encoding": "gzip"}, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def extract_tables(doc_path: Path, out_path: Path) -> None:
    """Dump candidate financial tables; fall back to text context search."""
    raw = doc_path.read_bytes()
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    out_lines: list[str] = [f"SOURCE: {doc_path.name}", ""]
    # Strategy 1: HTML tables containing year-like columns near Item 6
    if "<table" in text.lower():
        try:
            import pandas as pd
            tables = pd.read_html(io.StringIO(text))
            out_lines.append(f"Found {len(tables)} HTML tables.")
            # locate Item 6 position to prefer nearby tables
            m = re.search(r"selected financial data", text, re.I)
            item6_pos = m.start() if m else 0
            # find char offsets of tables
            positions = [mm.start() for mm in re.finditer(r"<table", text, re.I)]
            scored = []
            for idx, tbl in enumerate(tables):
                pos = positions[idx] if idx < len(positions) else 0
                s = str(tbl.to_string())
                year_hits = len(re.findall(r"19\d{2}|20[0-2]\d", s))
                dist = abs(pos - item6_pos)
                # nearest to the Item 6 heading wins; year-hits break ties
                scored.append((-dist, year_hits, idx, tbl))
            scored.sort(reverse=True)
            for _negdist, year_hits, idx, tbl in scored[:6]:
                if year_hits < 4:
                    continue
                out_lines.append(f"\n===== TABLE {idx} (year-hits={year_hits}) =====")
                tstr = tbl.to_string()
                out_lines.append(tstr[:6000])
        except Exception as e:
            out_lines.append(f"table parse failed: {e}")
    # Strategy 2: text context around "Selected Financial Data"
    for m in re.finditer(r"selected financial data", text, re.I):
        start = max(0, m.start() - 200)
        out_lines.append("\n----- context @ %d -----" % m.start())
        chunk = text[start:m.start() + 6000]
        chunk = re.sub(r"<[^>]+>", " ", chunk)
        chunk = re.sub(r"[ \t]+", " ", chunk)
        out_lines.append(chunk[:4000])
        if len(out_lines) > 60:
            break
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines))
    print(f"wrote {out_path} ({len(out_lines)} lines)")


def main():
    args = sys.argv[1:]
    if not args:
        tickers, fys = TARGETS, [2003, 2007]
    else:
        tickers, fys = [args[0]], [int(a) for a in args[1:]] or [2003, 2007]
    for ticker in tickers:
        docs = find_10k_docs(ticker, fys)
        print(f"{ticker}: found {sorted(docs)}")
        for fy, info in sorted(docs.items()):
            dest = DOCS / f"{ticker}_{fy}_{info['form'].replace('/', '')}.htm"
            try:
                download(info["url"], dest)
            except Exception as e:
                print(f"  FY{fy}: download failed: {e}")
                continue
            extract_tables(dest, TABLES / f"{ticker}_{fy}.txt")


if __name__ == "__main__":
    main()
