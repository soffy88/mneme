# oskill/cognitive_update.py
"""cognitive_update：forgetting-aware BKT + FSRS + recognition 统一认知更新。
纯算法，stateless。存储编排（CognitiveStore/DB 写入）由 Mneme 服务层负责。
"""
from datetime import datetime, timezone
from typing import Optional, Literal
from pydantic import BaseModel

from oprim.bkt import bkt_update, classify_error
from oprim.fsrs_engine import fsrs_retrievability, fsrs_review, fsrs_map_rating
from oprim.types import KCState

# 注意：recognition_update 目前还未实现，但在 spec 中列出，
# 在 0.1 阶段我可以先用空实现或者先不调，等 12.1 实现。
# 但为了 DoD 0.1，我应该尽量按 spec 来。
# 我先定义一个 mock 的 recognition_update 或者先不调它直到它被定义。
# 考虑到 spec 中认知更新顺序红线要求调用 recognition_update，我先在 oprim/learning_oprims.py 中占个位。

class CognitiveUpdateInput(BaseModel):
    state: KCState           # 当前认知状态（由调用方从存储取出传入）
    card_dict: dict          # 当前 FSRS card（由调用方从存储取出传入）
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    now: datetime | None = None

class CognitiveUpdateResult(BaseModel):
    state: KCState           # 更新后（调用方负责写回存储）
    card_dict: dict          # 更新后（调用方负责写回存储）
    error_type: str | None   # "careless"|"dontknow"|None（答对时 None）
    rating: str              # FSRS rating 名称
    effective_mastery: float # long_term_mastery × R（含遗忘）

class CognitiveStore:
    """内存版状态存储（生产环境替换为 PostgreSQL）。
    key = (student_id, kc_id) -> {"kc_state": KCState, "card": dict}
    """
    def __init__(self):
        self._store = {}

    def _key(self, student_id: str, kc_id: str):
        return f"{student_id}::{kc_id}"

    def get_or_create(self, student_id: str, kc_id: str):
        from data.guangdong_math_kc import get_bkt_prior
        from oprim.bkt import new_state_from_prior
        from oprim.fsrs_engine import fsrs_new_card
        
        k = self._key(student_id, kc_id)
        if k not in self._store:
            prior = get_bkt_prior(kc_id)
            self._store[k] = {
                "kc_state": new_state_from_prior(kc_id=kc_id, prior=prior),
                "card": fsrs_new_card(),
            }
        return self._store[k]

    def all_for_student(self, student_id: str):
        prefix = f"{student_id}::"
        return {
            k[len(prefix):]: v
            for k, v in self._store.items() if k.startswith(prefix)
        }

def cognitive_update(*, input: CognitiveUpdateInput) -> CognitiveUpdateResult:
    """forgetting-aware BKT + FSRS + recognition 统一更新。

    Internal oprim composition:
    - oprim.fsrs_retrievability  (算 R)
    - oprim.bkt_update           (forgetting-aware 掌握度更新)
    - oprim.classify_error       (粗心/不会判定)
    - oprim.fsrs_review          (FSRS 卡片更新)
    - oprim.recognition_update   (识别维度更新) - 暂时 mock
    - oprim.fsrs_map_rating      (表现→Rating)

    更新顺序（MUST，与 CLAUDE.md 红线一致）：
    1. 用旧卡片算 R
    2. forgetting-aware BKT 更新（R 衰减先验）
    3. 答错则 classify_error
    4. FSRS review
    5. recognition_update
    """
    now = input.now or datetime.now(timezone.utc)
    R = fsrs_retrievability(card_dict=input.card_dict, now=now)
    
    # In-place update for state
    bkt_update(state=input.state, is_correct=input.is_correct, retrievability=R)
    
    error_type = None
    if not input.is_correct:
        error_type = classify_error(state=input.state)
    
    rating = fsrs_map_rating(
        is_correct=input.is_correct, 
        used_answer=input.used_answer,
        struggled=input.struggled, 
        effortless=input.effortless
    )
    
    new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now)
    
    # recognition_update(state=input.state, is_correct=input.is_correct, is_interleaved=input.is_interleaved)
    # 暂时注释掉，因为 learning_oprims.py 还没写。
    
    input.state.last_interaction_ts = now.timestamp()
    
    eff = (input.state.long_term_mastery or input.state.current()) * R
    
    return CognitiveUpdateResult(
        state=input.state,
        card_dict=new_card,
        error_type=error_type,
        rating=rating.name,
        effective_mastery=eff
    )

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
    entry = store.get_or_create(student_id, kc_id)
    
    update_input = CognitiveUpdateInput(
        state=entry["kc_state"],
        card_dict=entry["card"],
        is_correct=is_correct,
        used_answer=used_answer,
        struggled=struggled,
        effortless=effortless,
        now=now
    )
    
    result = cognitive_update(input=update_input)
    
    # Write back (though it's in-place for state, card_dict needs replacement)
    entry["card"] = result.card_dict
    
    from oprim.fsrs_engine import fsrs_due_date
    
    kc_state = result.state
    return {
        "kc_id": kc_id,
        "p_mastery": round(kc_state.current(), 4),
        "long_term_mastery": round(kc_state.long_term_mastery or kc_state.current(), 4),
        "error_type": result.error_type,
        "rating": result.rating,
        "next_review_due": fsrs_due_date(card_dict=result.card_dict),
        "n_attempts": kc_state.n_attempts,
    }

def mastery_overview(store: CognitiveStore, student_id: str, now: Optional[datetime] = None):
    """学生当前所有 KC 的掌握度总览（含遗忘后的 effective 值）。"""
    from oprim.fsrs_engine import fsrs_retrievability
    
    now = now or datetime.now(timezone.utc)
    out = []
    for kc_id, entry in store.all_for_student(student_id).items():
        ks = entry["kc_state"]
        R = fsrs_retrievability(card_dict=entry["card"], now=now)
        out.append({
            "kc_id": kc_id,
            "long_term_mastery": round(ks.long_term_mastery or ks.current(), 4),
            "effective_mastery": round(ks.current() * R, 4),
            "n_attempts": ks.n_attempts,
        })
    return sorted(out, key=lambda x: x["effective_mastery"])

def review_queue(store: CognitiveStore, student_id: str, now: Optional[datetime] = None):
    """今日到期复习池：FSRS due <= now 的卡片。"""
    from oprim.fsrs_engine import fsrs_due_date
    
    now = now or datetime.now(timezone.utc)
    queue = []
    for kc_id, entry in store.all_for_student(student_id).items():
        due_iso = fsrs_due_date(card_dict=entry["card"])
        if due_iso and datetime.fromisoformat(due_iso) <= now:
            queue.append({"kc_id": kc_id, "due": due_iso})
    return queue

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-12",
    "elements": [
        {"name": "cognitive_update", "layer": "oskill", "summary": "BKT+FSRS 统一认知更新"},
    ]
}
