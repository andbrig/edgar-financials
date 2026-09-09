"""Bulk downloader: per-company filing metadata + all XBRL company facts.

For each company we fetch:
  1. https://data.sec.gov/submissions/CIK{cik10}.json        (filing index)
     + any additional CIK{cik10}-sub-001.json style files it references
  2. https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json  (all XBRL facts)

Raw JSON is kept on disk so parsing can be re-run without re-downloading.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .client import get_json
from .universe import cik10

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SUB_FILE_URL = "https://data.sec.gov/submissions/{name}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


def fetch_company(co: dict, data_dir: Path) -> dict:
    """Fetch everything for one company. Returns a small status dict."""
    c10 = co["cik10"]
    status = {"ticker": co["ticker"], "cik": co["cik"], "filings": 0, "facts": False,
              "fact_tags": 0, "error": None}
    try:
        sub_dir = data_dir / "submissions"
        facts_dir = data_dir / "facts"
        sub_dir.mkdir(parents=True, exist_ok=True)
        facts_dir.mkdir(parents=True, exist_ok=True)

        sub_path = sub_dir / f"{c10}.json"
        if sub_path.exists():
            sub = json.loads(sub_path.read_text())
        else:
            sub = get_json(SUBMISSIONS_URL.format(cik10=c10))
            if sub is None:
                status["error"] = "no submissions"
                return status
            sub_path.write_text(json.dumps(sub))

        # Older filings live in separate sub-files; fetch them too.
        for f in (sub.get("filings") or {}).get("files", []):
            name = f["name"]
            fp = sub_dir / name
            if not fp.exists():
                doc = get_json(SUB_FILE_URL.format(name=name))
                if doc is not None:
                    fp.write_text(json.dumps(doc))

        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        status["filings"] = len(forms)

        facts_path = facts_dir / f"{c10}.json"
        if facts_path.exists():
            facts = json.loads(facts_path.read_text())
        else:
            facts = get_json(FACTS_URL.format(cik10=c10))
            if facts is None:
                return status  # no XBRL data for this filer; not an error
            facts_path.write_text(json.dumps(facts))

        status["facts"] = True
        status["fact_tags"] = sum(len(t) for t in (facts.get("facts") or {}).values())
    except Exception as e:  # keep the bulk run going
        status["error"] = f"{type(e).__name__}: {e}"
    return status


def _atomic_write(path: str | Path, text: str) -> None:
    """Write via temp file + rename so concurrent readers never see a
    truncated file."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def fetch_all(companies: list[dict], data_dir: str | Path, workers: int = 4,
              progress_path: str | Path | None = None,
              log_every: int = 100) -> list[dict]:
    """Download everything for all companies. Resumable via progress file."""
    data_dir = Path(data_dir)
    done: set[str] = set()
    if progress_path and Path(progress_path).exists():
        done = set(json.loads(Path(progress_path).read_text()))

    todo = [c for c in companies if c["cik10"] not in done]
    results: list[dict] = []
    lock = threading.Lock()
    n = 0
    total = len(todo)
    print(f"Fetching {total} companies ({len(done)} already done), {workers} workers...")

    def one(co: dict):
        nonlocal n
        st = fetch_company(co, data_dir)
        with lock:
            done.add(co["cik10"])
            results.append(st)
            n += 1
            if progress_path and n % 25 == 0:
                _atomic_write(progress_path, json.dumps(sorted(done)))
            if n % log_every == 0 or n == total:
                errs = sum(1 for r in results if r["error"])
                print(f"  {n}/{total}  errors={errs}", flush=True)
        return st

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))

    if progress_path:
        _atomic_write(progress_path, json.dumps(sorted(done)))
    return results
