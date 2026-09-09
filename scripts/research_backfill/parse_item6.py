"""Parse Item 6 tables from downloaded 10-K HTML into a clean per-company summary.

Usage: venv/bin/python parse_item6.py
Reads scripts/research_backfill/docs/*.htm, finds the Selected Financial Data
table, and prints candidate (year -> revenue, net income, total assets).

Human must verify output before loading into the database.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
OUT = ROOT / "summaries"

REV_PAT = re.compile(r"^(net sales|total revenues?|revenues?|net revenues?|sales|total sales|total net revenue|sales and other operating revenues?|operating revenues?|consolidated revenues?)( \(.*\))?$", re.I)
NI_PAT = re.compile(r"^(net income|net earnings|consolidated net earnings|net income attributable.*|net earnings attributable.*|net income \(loss\))( \(.*\))?$", re.I)
ASSET_PAT = re.compile(r"^total assets( \(.*\))?$", re.I)


LABEL_RE = re.compile(r"net sales|total revenues?|revenues|net earnings|net income|sales to customer|total net revenue|consolidated revenues|consolidated net earnings", re.I)


def _tables_after(html: str, tables: list, positions: list[int],
                  anchor: int) -> list[tuple[int, object]]:
    cands = []
    for idx, tbl in enumerate(tables):
        pos = positions[idx] if idx < len(positions) else 0
        if pos < anchor:
            continue
        s = tbl.to_string()
        yh = len(re.findall(r"(19|20)\d{2}", s))
        if yh < 6 or not LABEL_RE.search(s):
            continue
        cands.append((pos - anchor, pos, tbl))
    cands.sort(key=lambda x: x[0])
    return [(pos, tbl) for _, pos, tbl in cands[:2]]


def find_item6_tables(html: str) -> list[tuple[int, object]]:
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return []
    positions = [m.start() for m in re.finditer(r"<table", html, re.I)]
    occs = [m.start() for m in re.finditer(r"selected financial data", html, re.I)]
    if not occs:
        occs = [0]
    # try each occurrence; the real Item 6 has a qualifying table right after it
    # (the TOC mention does not)
    best: list = []
    best_dist = None
    for anchor in occs:
        for pos, tbl in _tables_after(html, tables, positions, anchor):
            dist = pos - anchor
            if best_dist is None or dist < best_dist:
                best_dist, best = dist, [(pos, tbl)]
            break
    return best


EX13_CAPTION_RE = re.compile(
    r"\d+-year financial summary|summary of operations and statistical data"
    r"|five-year summary|ten-year summary|financial summary|selected financial data",
    re.I)


def find_ex13_summary_tables(html: str) -> list[tuple[int, object]]:
    """Financial summary tables inside an Exhibit 13 annual report."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return []
    positions = [m.start() for m in re.finditer(r"<table", html, re.I)]
    occs = [m.start() for m in EX13_CAPTION_RE.finditer(html)]
    if occs:
        res = _tables_after(html, tables, positions, occs[-1])
        if res:
            return res
    # content fallback: any table with 4+ year columns and revenue+NI labels
    scored = []
    for idx, tbl in enumerate(tables):
        s = tbl.to_string()
        years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", s))
        if len(years) >= 4 and LABEL_RE.search(s):
            pos = positions[idx] if idx < len(positions) else 0
            r = parse_table(tbl, detect_unit(html, pos))
            nrev = sum(1 for y, v in r.items() if "revenue" in v)
            if nrev:
                scored.append((nrev, len(r), pos, tbl))
    scored.sort(reverse=True)
    return [(pos, tbl) for _, _, pos, tbl in scored[:1]]


def _year_cell(s: str) -> int | None:
    """Extract a year from a cell, tolerating footnotes ('2004(c)') and
    date-style headers ('Dec. 31 2007', 'January 28, 2007')."""
    mm = re.search(r"((?:19|20)\d{2})", str(s))
    return int(mm.group(1)) if mm else None


def _num_tokens(row) -> list[tuple[float, str]]:
    """Ordered (value, raw) numeric tokens from a row."""
    toks = []
    for v in row:
        raw = str(v).strip()
        if raw.lower() in ("nan", "", "$", "—", "--", "-", "..."):
            continue
        neg = raw.startswith("(")
        num = re.sub(r"[^\d.]", "", raw)
        if not num or num == ".":
            continue
        try:
            toks.append((float(num) * (-1 if neg else 1), raw))
        except ValueError:
            continue
    return toks


def detect_unit(html: str, table_pos: int) -> float:
    """Look for 'in millions' / 'in thousands' near the table."""
    window = html[max(0, table_pos - 4000):table_pos + 500]
    text = re.sub(r"<[^>]+>", " ", window).lower()
    # nearest mention wins: search backwards from the table
    millions = text.rfind("million")
    thousands = text.rfind("thousand")
    if millions == -1 and thousands == -1:
        return 1.0
    return 1e6 if millions > thousands else 1e3


def parse_table(tbl: pd.DataFrame, unit: float = 1.0) -> dict[int, dict]:
    m = tbl.shape[0]
    # find the year row: row with most year-like cells
    year_row, year_cols = -1, {}
    for r in range(min(m, 12)):
        row = tbl.iloc[r]
        found: dict[int, list[int]] = {}
        for ci, v in enumerate(row):
            y = _year_cell(v)
            if y is not None:
                found.setdefault(y, []).append(ci)
        if len(found) >= 2 and len(found) > len(year_cols):
            # duplicate year columns ("2007", "2007"): pick the most numeric
            def _nscore(ci: int) -> int:
                return sum(1 for rr in range(m)
                           if re.match(r"^[\(\d—–-]", str(tbl.iloc[rr, ci]).strip()))
            year_row, year_cols = r, {y: max(cs, key=_nscore)
                                      for y, cs in found.items()}
    # fallback: years in column headers (AAPL layout, or HD date headers)
    header_years: dict[int, int] = {}
    if not year_cols:
        cands: dict[int, list[int]] = {}
        for ci, c in enumerate(tbl.columns):
            parts = [str(p) for p in (c if isinstance(c, tuple) else (c,))]
            for p in parts:
                y = _year_cell(p.strip()) if re.fullmatch(r"\s*(?:19|20)\d{2}(\.\d+)?\s*", p) else None
                if y is None:
                    # date-style header: "January 28, 2007"
                    mm = re.search(r"((?:19|20)\d{2})", p)
                    y = int(mm.group(1)) if mm else None
                if y is not None:
                    cands.setdefault(y, []).append(ci)
        # among duplicate year columns ("2007", "2007.1"), pick the most numeric
        for year, cols in cands.items():
            if len(cols) == 1:
                header_years[year] = cols[0]
                continue
            def numeric_score(ci: int) -> int:
                s = 0
                for v in tbl.iloc[:, ci].head(40):
                    if re.match(r"^[\$\(\d—–-]", str(v).strip()):
                        s += 1
                return s
            header_years[year] = max(cols, key=numeric_score)
        if not header_years:
            return {}
    # unit detection (fallback if not provided)
    if unit == 1.0:
        probe = tbl.to_string()[:1500].lower()
        unit = 1e6 if "million" in probe else (1e3 if "thousand" in probe else 1)

    result: dict[int, dict] = {}
    if year_cols:
        # CRITICAL: keep years in column order (tables often list newest first)
        years = [y for y, _ in sorted(year_cols.items(), key=lambda kv: kv[1])]
        # collect best row per kind: prefer "consolidated" rows, else first match
        best: dict[str, tuple[tuple[int, int], list]] = {}
        for r in range(year_row + 1, m):
            row = tbl.iloc[r]
            label = ""
            for v in row:
                s = str(v).strip()
                if s.lower() not in ("nan", ""):
                    label = re.sub(r"\s+", " ", s).lower()
                    break
            kind = ("revenue" if REV_PAT.match(label) else
                    "net_income" if NI_PAT.match(label) else
                    "assets" if ASSET_PAT.match(label) else None)
            if not kind:
                continue
            # read values from the year columns only (label cell may hold
            # footnote numbers like "(1) (2)" that would corrupt a row scan)
            vals: list[float] = []
            for y in years:
                raw = str(row.iloc[year_cols[y]]).strip()
                nt = _num_tokens([raw])
                if not nt:
                    break
                vals.append(nt[0][0])
            if len(vals) != len(years):
                continue
            score = (1 if "consolidat" in label else 0, -r)
            if kind not in best or score > best[kind][0]:
                best[kind] = (score, vals)
        for kind, (_, vals) in best.items():
            for y, val in zip(years, vals):
                result.setdefault(y, {})[kind] = val * unit
    else:
        years = sorted(header_years)
        for r in range(m):
            row = tbl.iloc[r]
            label = ""
            for v in row:
                s = str(v).strip()
                if s.lower() not in ("nan", ""):
                    label = re.sub(r"\s+", " ", s).lower()
                    break
            kind = ("revenue" if REV_PAT.match(label) else
                    "net_income" if NI_PAT.match(label) else
                    "assets" if ASSET_PAT.match(label) else None)
            if not kind:
                continue
            for y, ci in sorted(header_years.items()):
                raw = str(row.iloc[ci]).strip()
                neg = raw.startswith("(")
                num = re.sub(r"[^\d.]", "", raw)
                if not num:
                    continue
                try:
                    result.setdefault(y, {}).setdefault(kind, float(num) * unit * (-1 if neg else 1))
                except ValueError:
                    continue
    return result


def get_ex13_url(ticker: str, fy: int) -> str | None:
    """Find the Exhibit 13 annual-report document for a filing."""
    sys.path.insert(0, str(ROOT))
    from extract_item6 import find_10k_docs, download
    docs = find_10k_docs(ticker, [fy])
    if fy not in docs:
        return None
    accn = docs[fy]["accn"]
    dir_url = docs[fy]["url"].rsplit("/", 1)[0]
    try:
        idx = requests.get(dir_url + "/index.json",
                           headers={"User-Agent": UA, "Accept": "application/json"},
                           timeout=60).json()
    except Exception:
        return None
    for it in idx.get("directory", {}).get("item", []):
        n = it.get("name", "")
        nl = n.lower()
        if n.endswith((".htm", ".txt")) and ("ex13" in nl or "ex-13" in nl or "exv13" in nl
                                   or "ex_13" in nl or "exhibit13" in nl):
            ext = ".htm" if n.endswith(".htm") else ".txt"
            dest = DOCS / f"{ticker}_{fy}_EX13{ext}"
            if not dest.exists():
                print(f"  downloading Exhibit 13 {n} ...")
                download(dir_url + "/" + n, dest)
            return str(dest)
    return None


UA = f"Alfred-EDGAR-Research/1.0 (contact: {os.environ.get('EDGAR_CONTACT_EMAIL', 'alfred-research@example.com')})"
import requests  # noqa: E402


def find_financial_statement_tables(html: str) -> list[tuple[int, object]]:
    """Fallback: locate the Consolidated Statement(s) of Income and Balance
    Sheet by their headings, then take the first table after each heading
    that parses into revenue / net income / assets. (For filers like HD/XOM
    whose Item 6 is incorporated by reference or is just a page pointer.)"""
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return []
    positions = [m.start() for m in re.finditer(r"<table", html, re.I)]
    heading_res = [
        re.compile(r"consolidated\s+statements?\s+of\s+(income|earnings|operations)", re.I),
        re.compile(r"consolidated\s+balance\s+sheets?", re.I),
    ]
    out = []
    for hre in heading_res:
        anchors = []
        for m in hre.finditer(html):
            # skip MD&A references like "Selected Consolidated Statements of
            # Earnings Data" and table-of-contents occurrences
            context = html[max(0, m.start() - 120):m.start()].lower()
            after = html[m.end():m.end() + 30].lower()
            if "selected" in context or after.strip().startswith("data"):
                continue
            before = html[max(0, m.start() - 200):m.start()]
            if re.search(r"<t[dr][ >]", before, re.I):
                continue
            anchors.append(m.start())
        # from every anchor, take the first table after it that parses; keep
        # the candidate closest to its anchor (kills false text mentions)
        best = None
        for anchor in anchors:
            for idx, tbl in enumerate(tables):
                pos = positions[idx] if idx < len(positions) else 0
                if pos < anchor or tbl.shape[0] < 4 or tbl.shape[1] < 3:
                    continue
                parsed = parse_table(tbl, detect_unit(html, pos))
                kinds = {k for d in parsed.values() for k in d}
                if parsed and kinds:
                    gap = pos - anchor
                    if best is None or gap < best[0]:
                        best = (gap, pos, tbl)
                    break
        if best:
            out.append((best[1], best[2]))
    return out


def process_doc(doc: Path, ticker: str, fy: int, finder) -> dict[int, dict]:
    html = doc.read_text(errors="replace")
    merged: dict[int, dict] = {}
    for pos, tbl in finder(html):
        unit = detect_unit(html, pos)
        # first table (closest to caption) wins; later tables only fill gaps
        for year, vals in parse_table(tbl, unit).items():
            slot = merged.setdefault(year, {})
            for kind, val in vals.items():
                # zero usually means a parse failure (e.g. "$" column read as
                # the value); never let it overwrite or seed real data
                if val == 0:
                    continue
                slot.setdefault(kind, val)
    # drop years left with no usable values
    return {y: v for y, v in merged.items() if v}


def _score(merged: dict[int, dict]) -> float:
    """Plausibility score: consolidated statements dwarf segment/per-share
    tables, so the candidate with the largest typical revenue wins."""
    revs = [v["revenue"] for v in merged.values() if v.get("revenue")]
    if not revs:
        return 0.0
    import statistics
    nkinds = sum(len(v) for v in merged.values()) / max(1, len(merged))
    return statistics.median(revs) * (1 + 0.1 * nkinds)


def main():
    OUT.mkdir(exist_ok=True)
    all_summaries = {}
    for doc in sorted(DOCS.glob("*_10-K*.htm*")):
        parts = doc.stem.split("_")
        ticker, fy = parts[0], int(parts[1])
        # try every finder; keep the most plausible (largest consolidated)
        candidates = []
        r1 = process_doc(doc, ticker, fy, find_item6_tables)
        if r1:
            candidates.append((r1, doc.name))
        ex13 = get_ex13_url(ticker, fy)
        if ex13:
            r2 = process_doc(Path(ex13), ticker, fy, find_ex13_summary_tables)
            if r2:
                candidates.append((r2, Path(ex13).name))
        r3 = process_doc(doc, ticker, fy, find_financial_statement_tables)
        if r3:
            candidates.append((r3, doc.name + " [F-statements]"))
        if not candidates:
            # pre-HTML <TABLE> text exhibits (e.g. JNJ/PG 2003 EX13 .txt)
            ex13t = DOCS / f"{ticker}_{fy}_EX13.txt"
            if ex13t.exists():
                try:
                    sys.path.insert(0, str(ROOT / "scripts" / "research_backfill"))
                    from parse_txt_table import parse as parse_txt
                    r4 = parse_txt(str(ex13t))
                    # filter zeros like process_doc does
                    r4 = {y: {k: v for k, v in d.items() if v != 0}
                          for y, d in r4.items()}
                    r4 = {y: d for y, d in r4.items() if d}
                    if r4:
                        candidates.append((r4, ex13t.name))
                except Exception as e:
                    print(f"  txt parse failed for {ticker} FY{fy}: {e}")
        if not candidates:
            print(f"{ticker} FY{fy}: NO usable table found")
            continue
        merged, src = max(candidates, key=lambda c: _score(c[0]))
        key = f"{ticker}_FY{fy}"
        all_summaries[key] = {
            "ticker": ticker, "filing_fy": fy,
            "source_doc": src, "years": merged,
        }
    # HD special case: 10-Year Summary from the FY2003 text annual report
    # (Exhibit 13), parsed by scripts/research_backfill/parse_hd_10yr.py
    try:
        from parse_hd_10yr import parse as parse_hd_10yr
        hd10 = parse_hd_10yr()
        if hd10:
            all_summaries["HD_10YR"] = {
                "ticker": "HD", "filing_fy": 2003,
                "source_doc": "HD_2003_EX13.txt (10-Year Summary of Financial and Operating Results)",
                "years": hd10,
            }
            print(f"HD_10YR: years={sorted(hd10)}")
    except Exception as e:
        print(f"HD 10-year summary failed: {e}")
        rev = {y: merged[y].get("revenue") for y in sorted(merged)}
        ni = {y: merged[y].get("net_income") for y in sorted(merged)}
        print(f"{key}: years={sorted(merged)}\n  rev={rev}\n  ni ={ni}")
    (OUT / "item6_summaries.json").write_text(json.dumps(all_summaries, indent=1))
    print(f"\nwrote {OUT / 'item6_summaries.json'}")


if __name__ == "__main__":
    main()
