"""Step 2: parse downloaded EDGAR JSON into SQLite."""
from pathlib import Path
from .db import build_all

ROOT = Path(__file__).parent.parent


def main():
    import os
    workers = int(os.environ.get("BUILD_WORKERS", "0"))
    stats = build_all(ROOT / "data", ROOT / "edgar.db", progress_every=500,
                      workers=workers)
    print("BUILD COMPLETE:", stats)


if __name__ == "__main__":
    main()
