#!/usr/bin/env python3
"""List (or check) the 3O modules statically imported by mneme runtime code.

Usage:
  python scripts/vendor_edu_closure.py           # print closure
  python scripts/vendor_edu_closure.py --check  # exit 1 if finance-named paths imported
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("services", "tasks", "cli", "packages", "tests", "data")
IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+((?:oprim|oskill|omodul|obase)(?:\.[\w]+)*)",
    re.M,
)
FINANCE_KEYS = (
    "crypto",
    "ohlcv",
    "backtest",
    "trading",
    "exchange",
    "market_making",
    "derivatives",
    "volatility",
    "funding",
    "portfolio",
    "alpha_signal",
    "regime",
    "microstructure",
    "defi",
    "timeseries",
    "factor",
    "walk_forward",
    "orderbook",
    "scalper",
    "quant_analysis",
)


def collect_imports() -> set[str]:
    found: set[str] = set()
    for name in SCAN_ROOTS:
        root = ROOT / name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in IMPORT_RE.finditer(text):
                found.add(match.group(1))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mods = sorted(collect_imports())
    if not args.check:
        for mod in mods:
            print(mod)
        print(f"# total {len(mods)}", file=sys.stderr)
        return 0

    bad = [m for m in mods if any(k in m.lower() for k in FINANCE_KEYS)]
    if bad:
        print("finance-named 3O imports from mneme runtime:", file=sys.stderr)
        for m in bad:
            print(f"  {m}", file=sys.stderr)
        return 1
    print(f"ok: {len(mods)} 3O imports, none finance-named")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
