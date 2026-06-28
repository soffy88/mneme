"""服务层伪名化：student_id → 稳定不可逆引用，传给 omodul 作 fingerprint/decision-trail。

3O 边界：omodul 不应接触真实 user_id（尤其涉及未成年人，审计轨迹/指纹里不该留真实学生 UUID）。
服务层在调 omodul 前把 student_id 伪名化为稳定 hash；服务层自己仍用真实 id 做持久化。

注意：
- 无随机盐、用固定应用盐 → 同一学生恒得同一引用，保证 omodul fingerprint 的幂等稳定。
- 仅用于"omodul 仅拿来算指纹/记轨迹"的工作流（socratic/reading/mission/physics）。
  会把 user_id 落库为 student_id 的工作流（如 speaking_practice→speaking_sessions）必须传真实 id，
  其正解是把持久化上移到服务层，属更深重构，未在此处处理。
"""
from __future__ import annotations

import hashlib

_SALT = "mneme-omodul-pseudonym-v1"


def anon_ref(student_id) -> str:
    """把 student_id 伪名化为 24 位稳定引用（供 omodul 指纹/轨迹用，不可逆）。"""
    return hashlib.sha256(f"{_SALT}:{student_id}".encode()).hexdigest()[:24]
