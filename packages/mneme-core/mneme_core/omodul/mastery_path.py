"""mastery_path — 学生当前路径状态的业务事务包装（omodul）。

FC-6 分类筛：本元素承载 Mneme 教学假设（gate_type 定性/定量分野、rubric 门控、
教材专属 KC 排序均来自 mastery_gate 的 Mneme 语义），留 mneme-core 私有，不进
共享 platform/3O 主库 —— 对照 D3（放弃 mneme-core 7 元素的 platform RFC 路线，
见 MNEME-PHASE1-D1D3-DECISIONS-001.md）。

设计定案（S2，替代任务描述里悬而未决的"Wiki 拍板"）：advance = 纯派生/报告查询，
不做任何持久化写入 —— 与 AA.5"派生式不落新表"原则一致（学生路径位置永远由
kc_mastery 实时推导，NextObjective 已是唯一"移动"入口，见 TASKS.md AA.5）。
同输入永远同输出，天然幂等，故不启用 fingerprint 支柱、不暴露
``compute_fingerprint_for``；只启 decision_trail（审计"这次查询看到了什么、
给出了什么下一步"），对照 append_episode.py 先例（流水查询不去重）而非
register_entity.py 先例（内容态需去重）。若后续真引入"路径 advance"持久化写入
（对 AA.5 的有意识突破），届时需重新拍板启用 fingerprint。

组合 ≥2 oprim（3O 判定标准 1）：``mastery_gate.map_summary``（含 next_objective +
is_mastered 的路径全貌）+ ``spacing.due_reviews``（复习积压量，map_summary 不暴露）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Optional

from mneme_core.omodul._base import BaseConfig, standard_return
from mneme_core.oprim.mastery_gate import map_summary
from mneme_core.oprim.models import LearningProgress
from mneme_core.oprim.spacing import due_reviews


@dataclass
class MasteryPathConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "mastery_path"
    _omodul_version: ClassVar[str] = "0.1.0"
    _fingerprint_fields: ClassVar[frozenset[str]] = frozenset()  # 未启用 fingerprint
    _enabled_pillars: ClassVar[frozenset[str]] = frozenset({"decision_trail"})


@dataclass
class MasteryPathInput:
    progress: LearningProgress
    now: float


def mastery_path(
    config: MasteryPathConfig,
    input_data: MasteryPathInput,
    output_dir: Optional[Path] = None,
) -> dict:
    """给定当前掌握度状态，报告路径位置 + 下一步 + 复习积压（零写入，纯查询）。

    失败不 raise：任何异常 → status="failed" + error，findings=None（§5.4）。
    """
    del output_dir  # 未启用 report 支柱、无落盘产物；签名保留供三件套契约一致
    try:
        summary = map_summary(input_data.progress, now=input_data.now)
        pending_review_count = len(
            due_reviews(input_data.progress.review_queue, input_data.now)
        )
        findings = {**summary, "pending_review_count": pending_review_count}
    except Exception as exc:  # noqa: BLE001 — omodul 契约：失败不 raise
        return standard_return(
            findings=None,
            status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )

    trail = {
        "omodul_name": config._omodul_name,
        "omodul_version": config._omodul_version,
        "next_action": findings["next"]["action"],
        "next_kc_id": findings["next"]["kc_id"],
        "total_mastered": findings["total_mastered"],
        "total_kps": findings["total_kps"],
        "pending_review_count": pending_review_count,
    }
    return standard_return(
        findings=findings,
        status="completed",
        decision_trail=trail,
    )
