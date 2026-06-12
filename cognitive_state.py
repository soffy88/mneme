"""
认知状态协调器（统一 KT + FSRS）
================================
这是 v1.3 第4章「forgetting-aware 统一模型」的落地：
让 BKT（掌握了吗）和 FSRS（何时复习）共享「遗忘」这一事实，互为输入。

处理一次答题/回顾事件的完整流程：
  事件 → FSRS 更新卡片 & 算出 R → 用 R 衰减做 forgetting-aware BKT 更新
       → 若答错则判定粗心/不会 → 返回统一的认知状态
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from core import bkt
from core import fsrs_engine as fsrs
from data.guangdong_math_kc import get_bkt_prior


class CognitiveStore:
    """内存版状态存储（生产环境替换为 PostgreSQL）。
    key = (student_id, kc_id) -> {"kc_state": KCState, "card": dict}
    """
    def __init__(self):
        self._store = {}

    def _key(self, student_id, kc_id):
        return f"{student_id}::{kc_id}"

    def get_or_create(self, student_id, kc_id):
        k = self._key(student_id, kc_id)
        if k not in self._store:
            prior = get_bkt_prior(kc_id)
            self._store[k] = {
                "kc_state": bkt.new_state_from_prior(kc_id, prior),
                "card": fsrs.new_card(),
            }
        return self._store[k]

    def all_for_student(self, student_id):
        prefix = f"{student_id}::"
        return {
            k[len(prefix):]: v
            for k, v in self._store.items() if k.startswith(prefix)
        }


def process_interaction(
    store: CognitiveStore,
    student_id: str,
    kc_id: str,
    is_correct: bool,
    *,
    used_answer: bool = False,
    struggled: bool = False,
    effortless: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """处理一次答题事件，统一更新 KT 与 FSRS。返回认知状态快照。"""
    now = now or datetime.now(timezone.utc)
    entry = store.get_or_create(student_id, kc_id)
    kc_state = entry["kc_state"]
    card = entry["card"]

    # 1) 先用「当前」卡片算出可提取性 R（衰减用的是这次复习前的记忆状态）
    R = fsrs.retrievability(card, now=now)

    # 2) forgetting-aware BKT 更新（用 R 衰减先验掌握度）
    bkt.bkt_update(kc_state, is_correct, retrievability=R)

    # 3) 答错则判定粗心 vs 不会
    error_type = None
    if not is_correct:
        error_type = bkt.classify_error(kc_state)

    # 4) FSRS 更新卡片 & 调度下次复习
    rating = fsrs.map_performance_to_rating(
        is_correct, used_answer=used_answer,
        struggled=struggled, effortless=effortless,
    )
    new_card = fsrs.review(card, rating, now=now)
    entry["card"] = new_card
    kc_state.last_interaction_ts = now.timestamp()

    return {
        "kc_id": kc_id,
        "p_mastery": round(kc_state.current(), 4),
        "long_term_mastery": round(kc_state.long_term_mastery or kc_state.current(), 4),
        "retrievability_before": round(R, 4),
        "error_type": error_type,
        "rating": rating.name,
        "next_review_due": fsrs.due_date(new_card),
        "n_attempts": kc_state.n_attempts,
    }


def mastery_overview(store: CognitiveStore, student_id: str, now=None):
    """学生当前所有 KC 的掌握度总览（含遗忘后的 effective 值）。"""
    now = now or datetime.now(timezone.utc)
    out = []
    for kc_id, entry in store.all_for_student(student_id).items():
        ks = entry["kc_state"]
        R = fsrs.retrievability(entry["card"], now=now)
        out.append({
            "kc_id": kc_id,
            "long_term_mastery": round(ks.long_term_mastery or ks.current(), 4),
            "effective_mastery": round(ks.current() * R, 4),
            "n_attempts": ks.n_attempts,
        })
    return sorted(out, key=lambda x: x["effective_mastery"])


def review_queue(store: CognitiveStore, student_id: str, now=None):
    """今日到期复习池：FSRS due <= now 的卡片。"""
    now = now or datetime.now(timezone.utc)
    queue = []
    for kc_id, entry in store.all_for_student(student_id).items():
        due_iso = fsrs.due_date(entry["card"])
        if due_iso and datetime.fromisoformat(due_iso) <= now:
            queue.append({"kc_id": kc_id, "due": due_iso})
    return queue
