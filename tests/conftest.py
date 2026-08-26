"""共享测试夹具。

`bypass_auth`：把 get_current_user 覆盖为"按请求里的 student_id 返回匹配用户"，
用于那些 IDOR 加固后需要鉴权、但只访问自己数据的正向测试。**opt-in**（不 autouse），
不影响断言 401/403 的鉴权负向测试。

student_id 解析顺序：路径参数 → query 参数 → JSON body →
资源归属反查（session_id/mission_id/paper_id/question_id 等无 student_id 的路由，
按 DB 行的 student_id 回填，保证"资源归属校验"类鉴权也能以 owner 身份通过）。
"""

from __future__ import annotations

import os as _os
import sys as _sys
from pathlib import Path as _Path

# A clean ``uv sync`` environment puts the current checkout before the
# configured pythonpath.  Reassert the same vendor-first order used by CI
# before importing services, so the vendored 3O runtime cannot be shadowed by
# Mneme's small compatibility package.
_ROOT = _Path(__file__).resolve().parents[1]
for _entry in (
    _ROOT,
    _ROOT / "packages" / "event-schema",
    _ROOT / "packages" / "mneme-agent",
    _ROOT / "packages" / "mneme-core",
    _ROOT / "vendor",
):
    _value = str(_entry)
    if _value in _sys.path:
        _sys.path.remove(_value)
    _sys.path.insert(0, _value)

# 测试环境放开注册闸门（生产/部署默认关，见 main._require_registration_open）
_os.environ.setdefault("REGISTRATION_OPEN", "1")

# 必须在 import obase.db / services.main 之前钉测试库。
# 默认 Settings.DATABASE_URL 仍是 postgres:postgres@…/mneme：C4 后口令错，
# 且库名是活库。见 tests/db_guard.py。
from .db_guard import install_pytest_database_url

install_pytest_database_url()

import uuid

import pytest
from starlette.requests import Request

from services.main import app, get_current_user
from services.models import User, UserRole


async def _owner_of_resource(path_params: dict) -> str | None:
    """按资源行反查归属学生（无 student_id 参数的路由用）。"""
    from obase.db import SessionLocal
    from sqlalchemy import select

    from services.models import DailyMission, Paper, SocraticSession, WrongQuestion

    lookups = [
        ("session_id", SocraticSession),
        ("mission_id", DailyMission),
        ("paper_id", Paper),
        ("question_id", WrongQuestion),
    ]
    for key, model in lookups:
        raw = path_params.get(key)
        if not raw:
            continue
        try:
            rid = uuid.UUID(str(raw))
        except ValueError:
            continue
        async with SessionLocal() as db:
            owner = (
                await db.execute(select(model.student_id).where(model.id == rid))
            ).scalar_one_or_none()
        if owner:
            return str(owner)
    return None


async def _auth_from_request(request: Request) -> User:
    """返回 id 与请求 student_id（路径/query/body/资源归属）一致的学生用户，过自访问校验。"""
    sid = request.path_params.get("student_id") or request.query_params.get(
        "student_id"
    )
    if not sid:
        try:
            body = await request.json()
            if isinstance(body, dict):
                sid = body.get("student_id")
        except Exception:
            sid = None
    if not sid:
        sid = await _owner_of_resource(request.path_params)
    uid = uuid.UUID(str(sid)) if sid else uuid.uuid4()
    return User(id=uid, phone=f"test{str(uid.int)[:8]}", role=UserRole.student)


@pytest.fixture
def bypass_auth():
    app.dependency_overrides[get_current_user] = _auth_from_request
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ── g10-a KC 基线夹具（get_kc_info 类测试用）────────────────────────────
# tool_get_kc_info 需要 knowledge_units 里有对应行才能返回 name/gate_type/rubric。
# ku004 的 gate.rubric / gate.qualitative_intent 行在共享测试库里已持久化（无 FK 到
# knowledge_units），敌只补 textbook/cluster/KU 三件套即可。
#
# 关键：KU 一律 verified=False——避免串到 test_daily_plan 的 P4 "verified 优先"过滤
# （那会把未校验的 fixture KU 挤出新学路径）。get_kc_info 不读 verified，故安全。
# 非 autouse（opt-in），不影响其它测试；测完即清，不污染共享库。
_G10A_TB = "renjiao-math-g10-a"
_G10A_KU_QUAL = "renjiao-math-g10-a-ku004"  # 定性（有 rubric/intent）
_G10A_KU_QUANT = "renjiao-math-g10-a-ku-二次函数的零点"  # 量化（无 rubric）


@pytest.fixture
async def g10a_kc_baseline():
    """种入 g10-a 教材 + 2 cluster + 2 KU（ku004 定性 / 二次函数零点量化）。

    幂等：先查存在性，只插缺失的行（避免 PK 冲突）；teardown 只清自己种的 id。
    """
    from sqlalchemy import delete, select

    from obase.db import SessionLocal
    from services.models import KnowledgeCluster, KnowledgeUnit, Textbook

    c_qual = "renjiao-math-g10-a-c02"
    c_quant = "renjiao-math-g10-a-kc-一元二次不等式及其解法"
    created_textbook = False
    created_clusters: list[str] = []
    created_units: list[str] = []

    async def _exists(db, model, pk):
        return (
            await db.execute(select(model.id).where(model.id == pk))
        ).first() is not None

    async with SessionLocal() as db:
        if not await _exists(db, Textbook, _G10A_TB):
            db.add(
                Textbook(
                    id=_G10A_TB,
                    subject="math",
                    grade="高一",
                    edition="2017修订",
                    book_name="人教版·高中数学必修一（A版）",
                )
            )
            created_textbook = True
            await db.flush()
        if not await _exists(db, KnowledgeCluster, c_qual):
            db.add(
                KnowledgeCluster(
                    id=c_qual,
                    textbook_id=_G10A_TB,
                    name="函数与基本初等函数",
                    display_order=2,
                )
            )
            created_clusters.append(c_qual)
        if not await _exists(db, KnowledgeCluster, c_quant):
            db.add(
                KnowledgeCluster(
                    id=c_quant,
                    textbook_id=_G10A_TB,
                    name="一元二次不等式及其解法",
                    display_order=14,
                )
            )
            created_clusters.append(c_quant)
        await db.flush()
        if not await _exists(db, KnowledgeUnit, _G10A_KU_QUAL):
            db.add(
                KnowledgeUnit(
                    id=_G10A_KU_QUAL,
                    textbook_id=_G10A_TB,
                    cluster_id=c_qual,
                    name="函数的概念与表示",
                    description="理解函数的定义（映射视角），掌握定义域、值域、对应法则",
                    difficulty=0.4,
                    exam_frequency="high",
                    ku_type="concept",
                    verified=False,
                )
            )
            created_units.append(_G10A_KU_QUAL)
        if not await _exists(db, KnowledgeUnit, _G10A_KU_QUANT):
            db.add(
                KnowledgeUnit(
                    id=_G10A_KU_QUANT,
                    textbook_id=_G10A_TB,
                    cluster_id=c_quant,
                    name="二次函数的零点",
                    description="使ax²+bx+c=0的实数x称为二次函数y=ax²+bx+c的零点。",
                    difficulty=0.4,
                    exam_frequency="mid",
                    ku_type="concept",
                    verified=False,
                )
            )
            created_units.append(_G10A_KU_QUANT)
        await db.commit()

    yield {
        "textbook_id": _G10A_TB,
        "ku_qual": _G10A_KU_QUAL,
        "ku_quant": _G10A_KU_QUANT,
    }

    async with SessionLocal() as db:
        # 顺序清：KU → cluster → textbook（FK 无 CASCADE）。只清自己种的 id。
        if created_units:
            await db.execute(
                delete(KnowledgeUnit).where(KnowledgeUnit.id.in_(created_units))
            )
        if created_clusters:
            await db.execute(
                delete(KnowledgeCluster).where(
                    KnowledgeCluster.id.in_(created_clusters)
                )
            )
        if created_textbook:
            await db.execute(delete(Textbook).where(Textbook.id == _G10A_TB))
        await db.commit()
