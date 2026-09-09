"""Parse raw EDGAR JSON into normalized fact + filing rows.

XBRL company facts -> one row per (company, metric, calendar frame).
Filing indexes -> one row per filing with a direct EDGAR document URL.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .taxonomy import METRICS, TAXONOMIES

FRAME_RE = re.compile(r"^CY(\d{4})(Q([1-4]))?I?$")
FORM_PRIORITY = {"10-K": 3, "10-Q": 2, "20-F": 3, "40-F": 3}


def _parse_frame(frame: str, period: str):
    """Parse an SEC frame. Instant facts use an 'I' suffix (CY2025I);
    duration facts don't (CY2025). Returns (year, quarter, norm_frame)."""
    m = FRAME_RE.match(frame or "")
    if not m:
        return None
    is_instant = (frame or "").endswith("I")
    # frame kind must match the metric's period type
    if (period == "instant") != is_instant:
        return None
    year, q = int(m.group(1)), int(m.group(3) or 0)
    norm = f"CY{year}" + (f"Q{q}" if q else "")
    return year, q, norm


def parse_facts(cik: int, facts: dict) -> list[dict]:
    """Normalize one company's facts JSON into statement rows."""
    facts_root = facts.get("facts") or {}
    # tag -> list of (metric, unit) that claim it, in mapping priority order
    tag_claims: dict[str, list[tuple[str, str]]] = {}
    for metric, spec in METRICS.items():
        for tag in spec["tags"]:
            tag_claims.setdefault(tag, []).append((metric, spec["unit"]))

    best: dict[tuple[str, str], dict] = {}  # (metric, frame) -> row
    # (metric, end-year) -> best 10-K instant point, even when SEC gave no frame
    k10: dict[tuple[str, int], dict] = {}
    ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}
    for taxonomy in TAXONOMIES:
        for tag, tag_data in (facts_root.get(taxonomy) or {}).items():
            claims = tag_claims.get(tag)
            if not claims:
                continue
            units = tag_data.get("units") or {}
            for metric, want_unit in claims:
                period = METRICS[metric]["period"]
                points = units.get(want_unit)
                if not points:
                    continue
                for p in points:
                    if (period == "instant" and p.get("val") is not None
                            and p.get("end") and (p.get("form") or "") in ANNUAL_FORMS):
                        ey = int(p["end"][:4])
                        key10 = (metric, ey)
                        cur10 = k10.get(key10)
                        if cur10 is None or (p["end"], p.get("filed") or "") > (cur10["end"], cur10["filed"]):
                            k10[key10] = {
                                "cik": cik, "metric": metric, "frame": f"CY{ey}",
                                "year": ey, "quarter": 0, "value": float(p["val"]),
                                "form": p.get("form"), "filed": p.get("filed"),
                                "accn": p.get("accn"), "end": p.get("end"),
                                "source": "xbrl",
                            }
                    parsed = _parse_frame(p.get("frame"), period)
                    if not parsed or p.get("val") is None:
                        continue
                    year, q, frame = parsed
                    key = (metric, frame)
                    cur = best.get(key)
                    filed = p.get("filed") or ""
                    form = p.get("form") or ""
                    prio = FORM_PRIORITY.get(form, 1)
                    # Latest filed wins (handles restatements); tie-break on form priority.
                    if cur is None or (filed, prio) > (cur["filed"], cur["form_prio"]):
                        best[key] = {
                            "cik": cik,
                            "metric": metric,
                            "frame": frame,
                            "year": year,
                            "quarter": q,
                            "value": float(p["val"]),
                            "form": form,
                            "form_prio": prio,
                            "filed": filed,
                            "accn": p.get("accn"),
                            "end": p.get("end"),
                            "fy": p.get("fy"),
                            "fp": p.get("fp"),
                            "source": "xbrl",
                        }
                break  # first tag with data wins for this metric+taxonomy
    rows = list(best.values())

    # For fiscal-year companies the SEC never emits an annual instant frame;
    # the FY-end balance sheet is the quarterly instant frame of the FYE quarter
    # (e.g. AAPL's Sep FYE -> CY2025Q3I for FY2025). Synthesize annual instant
    # frames, preferring each 10-K's own balance-sheet date (k10, which also
    # catches 10-K points the SEC left frameless), then the latest quarterly
    # instant point in the calendar year.
    instant_metrics = {m for m, s in METRICS.items() if s["period"] == "instant"}
    have_annual: set[tuple[str, int]] = set()
    quarterly: list[dict] = []
    for r in rows:
        if r["metric"] not in instant_metrics:
            continue
        if r["quarter"] == 0:
            have_annual.add((r["metric"], r["year"]))
        else:
            quarterly.append(r)
    for (metric, year), src in sorted(k10.items()):
        if (metric, year) in have_annual or metric not in instant_metrics:
            continue
        rows.append(dict(src))
        have_annual.add((metric, year))
    # Fallback: latest quarterly instant point in the calendar year.
    by_my: dict[tuple[str, int], list[dict]] = {}
    for r in quarterly:
        by_my.setdefault((r["metric"], r["year"]), []).append(r)
    for (metric, year), pts in by_my.items():
        if (metric, year) in have_annual:
            continue
        pts.sort(key=lambda p: (p.get("end") or "", p["quarter"]))
        src = pts[-1]
        synth = {k: v for k, v in src.items() if k != "form_prio"}
        synth["frame"] = f"CY{year}"
        synth["quarter"] = 0
        rows.append(synth)
    for r in rows:
        r.pop("form_prio", None)
    return rows


def parse_filings(cik: int, submissions: dict, sub_files: list[dict]) -> list[dict]:
    """Flatten filing indexes into rows with direct document URLs."""
    rows: list[dict] = []

    def add(recent: dict):
        forms = recent.get("form") or []
        accns = recent.get("accessionNumber") or []
        filed = recent.get("filingDate") or []
        report = recent.get("reportDate") or []
        docs = recent.get("primaryDocument") or []
        for i, form in enumerate(forms):
            accn = accns[i] if i < len(accns) else ""
            nodash = accn.replace("-", "")
            doc = docs[i] if i < len(docs) else ""
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{doc}"
                   if nodash and doc else None)
            rows.append({
                "cik": cik,
                "form": form,
                "accn": accn,
                "filed": filed[i] if i < len(filed) else None,
                "report_date": report[i] if i < len(report) else None,
                "doc_url": url,
            })

    filings = submissions.get("filings") or {}
    if filings.get("recent"):
        add(filings["recent"])
    for sf in sub_files:
        recent = (sf.get("filings") or {}).get("recent") if isinstance(sf, dict) else None
        # sub-files store the arrays directly at top level of the JSON
        if isinstance(sf, dict) and sf.get("form"):
            add(sf)
        elif recent:
            add(recent)
    # de-dupe on accn
    seen, out = set(), []
    for r in rows:
        if r["accn"] and r["accn"] not in seen:
            seen.add(r["accn"])
            out.append(r)
    return out


def load_company_files(data_dir: Path, cik10: str):
    """Read a company's raw files from disk. Returns (facts, submissions, sub_files)."""
    data_dir = Path(data_dir)
    fp = data_dir / "facts" / f"{cik10}.json"
    facts = json.loads(fp.read_text()) if fp.exists() else None
    sp = data_dir / "submissions" / f"{cik10}.json"
    submissions = json.loads(sp.read_text()) if sp.exists() else None
    sub_files = []
    if submissions:
        for f in (submissions.get("filings") or {}).get("files", []):
            p = data_dir / "submissions" / f["name"]
            if p.exists():
                sub_files.append(json.loads(p.read_text()))
    return facts, submissions, sub_files
