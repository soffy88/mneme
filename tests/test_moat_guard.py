"""moat_eval CI 守卫（T.4）：内核合成判别力回归门。

exp1 快速档（100 学生 × 20 学习日，约 4-5k 交互，单 seed ~1s）断言合成 AUC≥0.65。
任何调度/先验/内核变更若把判别力打回 0.65 以下，此门变红。

- 纯计算不碰任何数据库（common.py 合成群体 + oskill.cognitive_update 回放）。
- 重测试默认跳过（保持常规 pytest 套件速度），MOAT=1 时执行：
    MOAT=1 python -m pytest tests/test_moat_guard.py -q --no-cov
  或走质量门：MOAT=1 bash scripts/check.sh
- 快速档规模选取依据：30 个 seed 扫描 min AUC=0.654 / mean=0.677（与全量档
  200×25 的 0.677 一致）；固定守卫 seed 42/7/2026 → 0.675/0.683/0.673。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.moat,
    pytest.mark.skipif(
        os.environ.get("MOAT") != "1",
        reason="moat 守卫为重测试，MOAT=1 时才运行",
    ),
]

# 快速档规模（见模块 docstring 的稳定性依据）
FAST_N_STUDENTS = 100
FAST_N_STUDY_DAYS = 20
AUC_GATE = 0.65
GUARD_SEEDS = (42, 7, 2026)


def _run_exp1_fast(seed: int) -> dict:
    """加载 scripts/moat_eval/exp1_kernel_auc（脚本目录不在包内，按路径引入）。"""
    moat_dir = str(Path(__file__).resolve().parents[1] / "scripts" / "moat_eval")
    if moat_dir not in sys.path:
        sys.path.insert(0, moat_dir)
    from exp1_kernel_auc import run_exp1

    return run_exp1(
        seed=seed, n_students=FAST_N_STUDENTS, n_study_days=FAST_N_STUDY_DAYS
    )


@pytest.mark.parametrize("seed", GUARD_SEEDS)
def test_kernel_synthetic_auc_gate(seed: int) -> None:
    """内核回放合成 AUC ≥ 0.65（overall 与 warm_only 双门）。"""
    result = _run_exp1_fast(seed)
    assert result["n_events"] > 2000, "快速档交互量异常，规模参数可能被改动"
    assert result["overall"]["auc"] >= AUC_GATE, (
        f"seed={seed}: overall AUC={result['overall']['auc']} < {AUC_GATE}，"
        "内核判别力回归——检查最近的调度/先验/内核变更"
    )
    assert result["warm_only"]["auc"] >= AUC_GATE, (
        f"seed={seed}: warm_only AUC={result['warm_only']['auc']} < {AUC_GATE}"
    )
