"""Parse Home Depot's 10-Year Summary from the FY2003 text annual report (Exhibit 13).

Two fixed-width tables:
  part 1: fiscal 2002, 2001 (with growth-rate columns)
  part 2: fiscal 2000 .. 1993
Fiscal year N ended in Jan/Feb of calendar N+1 -> CY = fiscal + 1.
All dollar values are in millions.
"""
import re
from pathlib import Path

DOC = Path(__file__).parent / "docs" / "HD_2003_EX13.txt"

WANT = {
    "net sales": "revenue",
    "net earnings": "net_income",
    "total assets": "assets",
}


def _num(cell: str) -> float | None:
    c = cell.strip()
    if not c or c == "--":
        return None
    neg = c.startswith("(")
    num = re.sub(r"[^\d.]", "", c)
    if not num or num == ".":
        return None
    try:
        return float(num) * (-1 if neg else 1)
    except ValueError:
        return None


def _col_positions(header: str, years: list[int]) -> list[int]:
    """Character offsets where each year's column starts."""
    pos = []
    for y in years:
        m = re.search(rf"\b{y}\b", header)
        assert m, f"year {y} not in header: {header!r}"
        pos.append(m.start())
    return pos


def parse() -> dict[int, dict]:
    lines = DOC.read_text(errors="replace").splitlines()
    p1_hdr = next(i for i, l in enumerate(lines)
                if l.startswith("amounts in millions") and "Growth Rate" in l)
    p2_hdr = next(i for i, l in enumerate(lines)
                  if re.match(r"\s*2000\s+1999\s+1998", l))
    parts = [
        (p1_hdr, [2002, 2001]),
        (p2_hdr, [2000, 1999, 1998, 1997, 1996, 1995, 1994, 1993]),
    ]
    result: dict[int, dict] = {}
    for hdr_idx, fiscal_years in parts:
        header = lines[hdr_idx]
        starts = _col_positions(header, fiscal_years)
        # column ends: next start (or line end)
        for i in range(hdr_idx + 1, hdr_idx + 75):
            line = lines[i]
            if line.startswith("<") or line.startswith("===") or line.startswith("---"):
                continue
            if not line.strip() or line.strip().startswith("("):
                continue
            low = line.lower()
            if "increase(" in low or "% of sales" in low:
                continue
            kind = None
            for label, k in WANT.items():
                if re.match(rf"^{label}(\s|$)", low):
                    kind = k
                    break
            if not kind:
                continue
            for fy, s in zip(fiscal_years, starts):
                e = starts[fiscal_years.index(fy) + 1] if fiscal_years.index(fy) + 1 < len(starts) else len(line)
                v = _num(line[s:e])
                if v is None:
                    continue
                cy = fy + 1
                result.setdefault(cy, {})[kind] = v * 1e6
    return result


if __name__ == "__main__":
    r = parse()
    for y in sorted(r):
        print(y, {k: f"{v/1e9:.3f}B" for k, v in r[y].items()})
