"""P0: mneme 运行时代码不得 import 共享 3O 的金融/交易语义路径。"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("services", "tasks", "cli", "packages")
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
    "funding_rate",
    "portfolio",
    "alpha_signal",
    "microstructure",
    "defi",
    "timeseries",
    "walk_forward",
    "orderbook",
    "scalper",
    "quant_analysis",
    "regime.",
    "regime_",
    ".regime",
)


def _runtime_3o_imports() -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for name in SCAN_ROOTS:
        root = ROOT / name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in IMPORT_RE.finditer(text):
                hits.append((str(path.relative_to(ROOT)), match.group(1)))
    return hits


def test_runtime_does_not_import_finance_3o_paths():
    bad = [
        (src, mod)
        for src, mod in _runtime_3o_imports()
        if any(k in mod.lower() for k in FINANCE_KEYS)
    ]
    assert bad == [], f"finance 3O imports in runtime: {bad}"


def test_vendor_edu_boundary_doc_exists():
    assert (ROOT / "vendor" / "EDU_BOUNDARY.md").is_file()


def test_paper_grading_does_not_import_services_models_errortype():
    """oskill 应使用 obase.domain_enums.ErrorType，禁止 from services.models import ErrorType。"""
    text = (ROOT / "vendor" / "oskill" / "paper_grading.py").read_text(
        encoding="utf-8"
    )
    assert "from services.models import" in text  # WrongQuestion 仍可能
    assert re.search(r"from services\.models import[^\n]*ErrorType", text) is None
    assert "from obase.domain_enums import ErrorType" in text


def test_learner_profile_does_not_import_textbook_qa_service():
    text = (ROOT / "vendor" / "oprim" / "learner_profile_summary.py").read_text(
        encoding="utf-8"
    )
    assert "textbook_qa_service" not in text
    assert "provider_registry" in text


def test_oprim_bkt_is_single_source_alias():
    """掌握度写路径必须走 vendor oprim.bkt → _cognitive，不是 mneme_core 那份。"""
    text = (ROOT / "vendor" / "oprim" / "bkt.py").read_text(encoding="utf-8")
    assert "from oprim._cognitive import" in text
    assert "single_source" in text or "_cognitive" in text
