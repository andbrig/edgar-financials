"""Step 1: download all EDGAR data. Resumable - safe to re-run."""
from pathlib import Path
from .universe import load_universe
from .fetch import fetch_all

DATA = Path(__file__).parent.parent / "data"


def main():
    unis = load_universe(DATA / "tickers.json")
    results = fetch_all(unis, DATA, workers=10,
                        progress_path=DATA / "progress.json", log_every=500)
    import json
    errs = [r for r in results if r["error"]]
    print(f"DONE. companies={len(results)} errors={len(errs)}")
    (DATA / "fetch_results.json").write_text(json.dumps(results))


if __name__ == "__main__":
    main()
