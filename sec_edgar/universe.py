"""Company universe: all SEC filers with a ticker symbol (~10k companies)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .client import get_json

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def cik10(cik: int) -> str:
    return str(int(cik)).zfill(10)


def load_universe(cache_path: str | Path) -> list[dict]:
    """Load [{cik, cik10, ticker, name}]. Caches the tickers file locally."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
    else:
        # www.sec.gov serves this one gzipped
        import requests
        from .client import _session
        r = _session.get(TICKERS_URL, timeout=60)
        r.raise_for_status()
        raw = r.content
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
        data = json.loads(raw)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))
    out = []
    for _k, v in data.items():
        c = int(v["cik_str"])
        out.append({
            "cik": c,
            "cik10": cik10(c),
            "ticker": v["ticker"],
            "name": v["title"],
        })
    out.sort(key=lambda d: d["ticker"])
    return out
