"""exp5 外部真实数据 AUC 守卫（GH-1，对标 ASSISTments 2009-2010）。

动机（outputs/GAP-REVIEW-20260817.md P0-1）：内核此前只有合成数据 AUC 验证。
本守卫用公开匿名化的 ASSISTments 真实作答序列回放生产算法路径，断言外部真实
数据判别力不回退。

- 纯计算不碰任何数据库（data/external 公开数据 + oskill.cognitive_update 回放）。
- 快速档（max_students=200, max_len=25）保持常规套件速度；MOAT=1 跑全量档：
    MOAT=1 python -m pytest tests/test_external_auc.py -q --no-cov
- 门槛依据（2026-08-17 首跑，全量 4029 生 / 325k 事件）：
    generic 冷启动 overall AUC=0.650 / warm=0.673；
    calibrated(train→test) overall AUC=0.707 / warm=0.710。
  快速档样本小、校准臂样本不足会跳过，故只守 generic 臂 warm AUC≥0.60
  （低于合成门 0.65——真实数据噪声更大，且无时间戳/难度信号，见 exp5 局限声明）。
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
        reason="外部数据守卫为重测试，MOAT=1 时才运行",
    ),
    pytest.mark.skipif(
        not (
            Path(__file__).resolve().parents[1]
            / "data"
            / "external"
            / "assist2009_updated_train.csv"
        ).exists(),
        reason="外部数据不入主库（data/external 本地存放），缺数据时跳过",
    ),
]

# 快速档规模：200 生 × ≤25 步，保证 generic 臂有足够 warm 事件且不拖慢套件。
FAST_MAX_STUDENTS = 200
FAST_MAX_LEN = 25
# 真实数据判别力门（低于合成 0.65，见模块 docstring 依据）。
WARM_AUC_GATE = 0.60


def _run_exp5_fast() -> dict:
    moat_dir = str(Path(__file__).resolve().parents[1] / "scripts" / "moat_eval")
    if moat_dir not in sys.path:
        sys.path.insert(0, moat_dir)
    from exp5_external_auc import run_exp5

    return run_exp5(max_students=FAST_MAX_STUDENTS, max_len=FAST_MAX_LEN)


def test_external_data_files_present() -> None:
    """外部数据集文件在位（GH-1 数据落 data/external，不入主库）。"""
    data_dir = Path(__file__).resolve().parents[1] / "data" / "external"
    for fn in ("assist2009_updated_train.csv", "assist2009_updated_test.csv"):
        assert (data_dir / fn).exists(), f"缺少外部数据集文件 {fn}"


def test_external_generic_warm_auc_gate() -> None:
    """ASSISTments 真实序列回放：generic 臂 warm AUC ≥ 0.60（判别力不回退）。"""
    result = _run_exp5_fast()
    warm = result["generic_priors"]["warm_only"]
    assert warm["n"] > 500, "快速档 warm 事件量异常，数据/规模参数可能被改动"
    assert warm["auc"] >= WARM_AUC_GATE, (
        f"外部真实数据 warm AUC={warm['auc']} < {WARM_AUC_GATE}，"
        "内核在真实作答序列上的判别力回退——检查 BKT/先验/更新顺序变更"
    )
