# EDGAR Financials

Financial statements for every SEC filer with a ticker, parsed from the SEC
EDGAR database into clean balance sheets, income statements, and cash flows.

The universe is the SEC's published ticker file (`company_tickers.json`):
~10,400 ticker records covering ~8,000 unique companies (some CIKs carry more
than one ticker). This is "every SEC filer with a ticker" — not every US
company; private companies don't file with the SEC.

## What it does

- **Downloads** the full filing index + all XBRL financial facts for every SEC
  filer with a ticker (~10,400 ticker records / ~8,000 unique companies) via `data.sec.gov`.
- **Parses** XBRL into normalized annual & quarterly statements: income
  statement, balance sheet, cash flow, plus computed ratios
  (margins, ROE/ROA, debt/equity, current ratio).
- **Detects gaps** (notably the pre-XBRL era before ~2009) and supports
  sourced **research backfills** that fill only the missing cells.
- **Serves** it all through a web dashboard and a CLI.

## Coverage (honest version)

| Data | Range | Source |
|---|---|---|
| Filing index (every 10-K, 10-Q, 8-K, …) with document links | 1994 → present | EDGAR submissions API |
| XBRL financial facts (revenue, net income, assets, …) | ~2009 → present (some filers from 2007) | EDGAR companyfacts API |
| Pre-XBRL financials | filled by hand-researched, sourced overrides | see `research_overrides` table |

The SEC's XBRL mandate phased in from 2009, so machine-readable financials
before ~2009 are the systematic gap. Pre-2009 numbers in the database are
marked `source='research'` with the origin recorded — everything else is
`source='xbrl'`, straight from the filings.

### Known data quirks

- **XOM / ExxonMobil.** The SEC ticker file maps ticker `XOM` to CIK 2115436
  ("ExxonMobil Holdings Corp"), which carries almost no XBRL facts. The
  long-standing Exxon Mobil Corporation CIK 34088 does not appear in the
  current ticker universe, so XOM financials are effectively absent. The
  database faithfully reflects the SEC's published mapping.
- **Duplicate tickers.** Some CIKs appear under more than one ticker, so the
  ~10,400 ticker records resolve to ~8,000 unique companies.

## Quick start

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# 1. Download everything from EDGAR (takes a few hours; resumable)
venv/bin/python -m sec_edgar.run_fetch

# 2. Parse into SQLite
venv/bin/python -m sec_edgar.run_build

# 3a. Web dashboard
EDGAR_DB=edgar.db venv/bin/python webapp.py   # -> http://127.0.0.1:5057

# 3b. CLI
venv/bin/python cli.py --db edgar.db search AAPL
venv/bin/python cli.py --db edgar.db statements MSFT --years 10
venv/bin/python cli.py --db edgar.db gaps XOM
venv/bin/python cli.py --db edgar.db coverage
```

## Layout

```
sec_edgar/
  client.py     rate-limited SEC HTTP client (≤7 req/s, identified User-Agent)
  universe.py   the 10,407 ticker filers
  fetch.py      bulk download of filing indexes + XBRL facts (resumable)
  taxonomy.py   standard line items -> US-GAAP XBRL tags (+ ratio definitions)
  parse.py      XBRL facts -> normalized (company, metric, calendar frame) rows
  db.py         SQLite schema + bulk loader + research overrides
  gaps.py       gap detection across the universe
  query.py      statement/trend/search helpers
  run_fetch.py  step 1 entry point
  run_build.py  step 2 entry point
cli.py          terminal queries
webapp.py       Flask dashboard (search, statements, trends, filings, gaps)
templates/      dashboard pages
data/           raw EDGAR JSON (kept so parsing can be re-run)
edgar.db        the built database
```

## Parsing notes

- **Frames, not fiscal periods.** SEC calendar frames (`CY2023`, `CY2023Q3`)
  normalize every filer's fiscal calendar; restatements resolve to the
  latest-filed value per frame.
- **Balance sheets for fiscal-year filers.** The SEC issues no annual instant
  frame for non-December year-ends, and sometimes leaves 10-K points frameless
  entirely — the parser reconstructs each fiscal year's balance sheet from the
  10-K's own balance-sheet date (including frameless points).
- **XBRL always wins.** Research overrides only fill frames XBRL doesn't have.

## SEC fair access

The fetcher identifies itself, stays under 10 requests/second, retries
gracefully on 429/5xx, and caches everything locally so a re-parse never
re-downloads.
