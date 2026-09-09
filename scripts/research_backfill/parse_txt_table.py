"""Parse SEC pre-HTML <TABLE> text blocks (e.g. JNJ 2003 Exhibit 13).

Format:
    <TABLE>
                                           2003          2002  ...
                                         ---------     ---------
    <S>                                      <C>           <C> ...
    Sales to customers
     - Domestic                              $  25,274        22,455 ...

Year header positions define fixed-width value columns; data rows are sliced
at those positions. Returns {year: {'revenue':..,'net_income':..,'assets':..}}.
"""
from __future__ import annotations

import re
from pathlib import Path


def _col_spans(header: str) -> list[tuple[int, int, int]]:
    """Find (year, start, end) column spans from the year header line."""
    spans = []
    for m in re.finditer(r"(19|20)\d{2}", header):
        spans.append((int(m.group(0)), m.start(), m.end()))
    # extend each column to the next column's start (or EOL)
    out = []
    for i, (y, s, e) in enumerate(spans):
        end = spans[i + 1][1] if i + 1 < len(spans) else len(header) + 40
        out.append((y, s, end))
    return out


def _num(cell: str) -> float | None:
    cell = cell.strip()
    if not cell or cell in ("-", "--", "..."):
        return None
    neg = cell.startswith("(")
    num = re.sub(r"[^\d.]", "", cell)
    if not num or num == ".":
        return None
    try:
        return float(num) * (-1 if neg else 1)
    except ValueError:
        return None


LABEL_PATTERNS = [
    (re.compile(r"^total sales$"), "revenue"),
    (re.compile(r"^net sales$"), "revenue"),
    (re.compile(r"^net earnings$"), "net_income"),
    (re.compile(r"^total assets$"), "assets"),
]


def _parse_inline_row(line: str, years: list[int], unit: float,
                      result: dict[int, dict]) -> bool:
    """Single-line row: 'Net Sales  $ 43,377  $ 40,238  ...' -> map values."""
    # strip tags, find label = text before first number
    text = re.sub(r"</?[A-Z]+>", " ", line)
    mnum = re.search(r"[\d]", text)
    if not mnum:
        return False
    label = re.sub(r"\s+", " ", text[:mnum.start()]).strip().lower()
    label = re.sub(r"[\$\*]+$", "", label).strip()
    kind = None
    for pat, k in LABEL_PATTERNS:
        if pat.match(label):
            kind = k
            break
    if not kind:
        return False
    rest = text[mnum.start():]
    # tokenize numbers, skipping percentages and per-share rows
    if "%" in rest:
        return False
    toks = re.findall(r"\(?\$?\s*[\d,]+\)?", rest)
    vals = []
    for t in toks:
        neg = t.strip().startswith("(")
        num = re.sub(r"[^\d.]", "", t)
        if num and num != ".":
            try:
                vals.append(float(num) * (-1 if neg else 1))
            except ValueError:
                pass
    if len(vals) != len(years):
        return False
    for y, v in zip(years, vals):
        result.setdefault(y, {}).setdefault(kind, v * unit)
    return True


def parse_txt_tables(text: str, unit: float = 1.0) -> dict[int, dict]:
    result: dict[int, dict] = {}
    # detect unit from nearby text
    m = re.search(r"\(dollars in (millions|thousands)", text, re.I)
    if m:
        unit = 1e6 if m.group(1).lower() == "millions" else 1e3
    else:
        m2 = re.search(r"amounts in millions", text, re.I)
        if m2:
            unit = 1e6
    cands: list[tuple[int, str, bool]] = []  # (pos, block, has_phrase)
    for tm in re.finditer(r"<TABLE>(.*?)</TABLE>", text, re.S | re.I):
        before = text[max(0, tm.start() - 3000):tm.start()]
        before_clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", before)).lower()
        has_phrase = bool(re.search(
            r"financial summary|summary of operations|ten-year|eleven-year|five-year",
            before_clean))
        cands.append((tm.start(), tm.group(1), has_phrase))
    # pass 1: tables near the summary heading
    accepted_years: set[int] = set()
    deferred: list[tuple[int, str]] = []
    for pos, block, has_phrase in sorted(cands):
        yrs = _block_years(block)
        if not yrs:
            continue
        if has_phrase:
            _parse_block(block, unit, result)
            accepted_years |= yrs
        else:
            deferred.append((pos, block))
    # pass 2: continuation tables whose years abut accepted years
    # (multi-page summaries, e.g. JNJ 1993-1998 following 1999-2003).
    # Must be disjoint and adjacent: overlapping year tables are different
    # tables (MD&A details), not continuations.
    for pos, block in deferred:
        yrs = _block_years(block)
        if (accepted_years and yrs and not (yrs & accepted_years)
                and (max(yrs) == min(accepted_years) - 1
                     or min(yrs) == max(accepted_years) + 1)):
            _parse_block(block, unit, result)
            accepted_years |= yrs
    return result


def _block_years(block: str) -> set[int]:
    yrs: set[int] = set()
    for ln in block.splitlines()[:12]:
        yrs.update(int(y) for y in re.findall(r"((?:19|20)\d{2})", ln))
    return yrs


def _parse_block(block: str, unit: float, result: dict[int, dict]) -> None:
    lines = [ln.rstrip() for ln in block.splitlines()]
    # find the year header: line with >=2 years
    hdr_idx, spans = -1, []
    for i, ln in enumerate(lines[:12]):
        clean = re.sub(r"</?[SC]>", " ", ln)
        yrs = re.findall(r"((?:19|20)\d{2})", clean)
        if len(yrs) >= 2:
            spans = _col_spans(clean)
            hdr_idx = i
            break
    if hdr_idx < 0 or not spans:
        return
    years = [y for y, _, _ in spans]
    # PG-style: label and values on one line -> handle inline first
    pending_label = ""
    for ln in lines[hdr_idx + 1:]:
        if _parse_inline_row(ln, years, unit, result):
            continue
        clean = re.sub(r"</?[SC]>", " ", ln)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or set(clean) <= set("- "):
            continue
        # split label from values: values live in the year columns
        raw = re.sub(r"</?[SC]>", " ", ln)
        # label = text before first year column
        first_col = spans[0][1]
        label_part = raw[:first_col]
        label = re.sub(r"\s+", " ", re.sub(r"</?[SC]>", " ", label_part)).strip().lower()
        label = re.sub(r"[\$\*\(\d\)]+$", "", label).strip()
        if not label:
            continue
        kind = None
        for pat, k in LABEL_PATTERNS:
            if pat.match(label):
                kind = k
                break
        if not kind:
            # accumulate multi-line labels (e.g. "Sales to customers" + "- Domestic")
            pending_label = (pending_label + " " + label).strip()
            continue
        vals = []
        for y, s, e in spans:
            cell = raw[s:e] if s < len(raw) else ""
            n = _num(cell)
            if n is None:
                break
            vals.append(n)
        if len(vals) != len(years):
            pending_label = ""
            continue
        for y, v in zip(years, vals):
            result.setdefault(y, {})[kind] = v * unit
        pending_label = ""


def parse(path: str | Path) -> dict[int, dict]:
    return parse_txt_tables(Path(path).read_text(errors="replace"))
