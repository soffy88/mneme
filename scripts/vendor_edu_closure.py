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
    r"^\s*(?:from|import)\s+(?:(?:vendor)\.)?((?:oprim|oskill|omodul|obase)(?:\.[\w]+)*)",
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
    # 文件存在性守卫扩展键（2026-08-16 第二轮裁剪）：整仓 dump 历史遗留的
    # 支付/支付系统与量化工作流文件名，随文件一并纳入禁止清单。
    "alipay",
    "stripe",
    "appstore",
    "okx",
    "stat_arb",
    "cointegration",
    "pbo_compute",
    "cpcv",
    "sharpe",
    "kdj",
    "zscore_signal",
    "price_store",
    "ohlcv_store",
    "macro_cycle",
    "macro_surprise",
    "liquidation",
    "market_impact",
    "sector_strength",
    "universe_selection",
    "bear_analyst",
    "bull_analyst",
    "seat_winrate",
    "unknown_seats",
    "candidate_universe",
    "equity_curve",
    "deflated_sharpe",
    "industry_valuation",
    "trend_compose",
    "dcf_valuation",
    "beneish",
    "stamp_tax",
    "compute_commission",
    "seat_t3",
    "fetch_macro",
    "detect_daily_limit",
    "detect_hot_money",
    "detect_northbound",
    "detect_sector_collapse",
    "detect_volume_dryup",
    "detect_volume_spike",
    "detect_news_shock",
    "theme_to_sw_industry",
    "industry_attribution",
    "policy_event_extraction",
    "signal_analysis",
    "signal_processing",
    "financial_metric",
    "timeframes_compute",
    "symbol_dim_score",
    "risk_models",
    "risk_limit_check",
    "autoheal_cycle",
    "backup_app_data",
    "generative_video_pipeline",
)


VENDOR_ROOT = ROOT / "vendor"

# 命中 FINANCE_KEYS 但属合法教育基础设施的文件（存在性守卫白名单）：
# - obase/crypto/*：密码学（口令哈希/密钥派生/token 加密），认证链路在用；
#   "crypto" 此处是 cryptography，非数字资产交易。
# - oprim/crypto/hashing.py：sha256_hash 被 omodul._decision_trail /
#   oprim.signature.compute 使用（决策轨迹指纹）。
# - omodul/refactor_transaction.py：DB 事务语义，被 omodul/__init__ 导入。
FINANCE_FILE_ALLOW = {
    "obase/crypto/__init__.py",
    "obase/crypto/key_derivation.py",
    "obase/crypto/token_encryptor.py",
    "oprim/crypto/__init__.py",
    "oprim/crypto/hashing.py",
    "omodul/refactor_transaction.py",
}


def collect_finance_files() -> list[Path]:
    """vendor/ 下文件名命中 FINANCE_KEYS 的 3O 文件（存在性守卫）。

    防止刷新 vendor（git archive 整仓 dump）时金融/支付/量化文件回流：
    光守运行时 import 不够，文件本身不允许躺在教育生产树里。
    """
    bad: list[Path] = []
    for root in ("oprim", "oskill", "omodul", "obase"):
        base = VENDOR_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(VENDOR_ROOT)
            if str(rel) in FINANCE_FILE_ALLOW:
                continue
            if any(k in str(rel).lower() for k in FINANCE_KEYS):
                bad.append(rel)
    return sorted(bad)


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
    # 存在性守卫：vendor 文件本身也不得命中（防整仓 dump 回流）
    bad_files = collect_finance_files()
    if bad_files:
        print("finance-named 3O files present in vendor/ (应删除):", file=sys.stderr)
        for rel in bad_files:
            print(f"  vendor/{rel}", file=sys.stderr)
        return 1
    print(f"ok: {len(mods)} 3O imports + vendor 文件存在性, none finance-named")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
