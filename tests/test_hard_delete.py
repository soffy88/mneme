"""合规硬删除（P1-7）：软删超宽限期 → 物理清除用户及全部 PII；宽限期内保留。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.models import User, UserRole, WrongQuestion
from services.purge_service import purge_deleted_users


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _mk_user(db, *, deleted_days_ago: int | None) -> uuid.UUID:
    sid = uuid.uuid4()
    deleted_at = (
        None
        if deleted_days_ago is None
        else datetime.now(timezone.utc) - timedelta(days=deleted_days_ago)
    )
    db.add(
        User(
            id=sid,
            phone=f"1{str(sid.int)[:10]}",
            role=UserRole.student,
            deleted_at=deleted_at,
        )
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="q",
            correct_answer="a",
            subject="math",
            knowledge_points={"KC": "x"},
        )
    )
    await db.flush()
    return sid


async def _cleanup(db, sid):
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.mark.asyncio
async def test_purge_removes_user_past_grace(db):
    sid = await _mk_user(db, deleted_days_ago=40)
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert sid.__str__() in result["ids"]
        # 用户本体与其错题都被物理清除
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is None
        wq = (
            (
                await db.execute(
                    select(WrongQuestion).where(WrongQuestion.student_id == sid)
                )
            )
            .scalars()
            .all()
        )
        assert wq == []
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_keeps_user_within_grace(db):
    sid = await _mk_user(db, deleted_days_ago=5)
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert str(sid) not in result["ids"]
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is not None
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_ignores_active_user(db):
    """未软删的活跃用户绝不被清。"""
    sid = await _mk_user(db, deleted_days_ago=None)
    try:
        result = await purge_deleted_users(db, grace_days=0)
        assert str(sid) not in result["ids"]
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is not None
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_removes_timed_quiz_and_textbook_file(db):
    """回归：做过限时小测/传过教材的用户也必须能被清（此前 purge 漏了
    timed_quizzes/textbook_files，因外键 NO ACTION 会导致整个删除事务回滚，
    这类未成年 PII 永远删不掉——上线体检发现的删除阻断）。"""
    from services.models import TextbookFile, TimedQuiz

    sid = await _mk_user(db, deleted_days_ago=40)
    tf_id = f"tf-{uuid.uuid4().hex[:8]}"
    db.add(TimedQuiz(id=uuid.uuid4(), student_id=sid, items=[]))
    db.add(
        TextbookFile(
            id=tf_id,
            owner_student_id=sid,
            filename="x.pdf",
            file_type="pdf",
            storage_path="papers/x.pdf",
        )
    )
    await db.flush()
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert str(sid) in result["ids"]
        # 用户本体 + 限时小测 + 教材文件全部物理清除，删除事务未因外键回滚
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is None
        assert (
            (await db.execute(select(TimedQuiz).where(TimedQuiz.student_id == sid)))
            .scalars()
            .all()
        ) == []
        assert (
            (
                await db.execute(
                    select(TextbookFile).where(TextbookFile.owner_student_id == sid)
                )
            )
            .scalars()
            .all()
        ) == []
    finally:
        await db.execute(delete(TimedQuiz).where(TimedQuiz.student_id == sid))
        await db.execute(
            delete(TextbookFile).where(TextbookFile.owner_student_id == sid)
        )
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_every_student_table_is_in_purge_list(db):
    """守卫测试：**任何** schema 里带 student_id/owner_student_id 列的表，都必须在
    purge 清单里。防"新增带未成年PII的表却忘了加进删除清单"的 schema 漂移——上一次
    正是因为缺守卫，timed_quizzes/textbook_files 漏了没人发现。

    扫描**全部**非系统 schema（不再只 public），故 W2 无论在 public 还是 gate 等新
    schema 加带 student_id 的表，只要漏入 purge 清单，本守卫立即失败自曝。无豁免白名单
    （parent_student 除外——它由 purge 里 parent/student 双向单独处理）。名字规范化与
    _STUDENT_TABLES 一致：public 表用裸名，其余 schema 用 `schema.table`。"""
    from services.purge_service import _STUDENT_TABLES

    rows = (
        await db.execute(
            text(
                """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE column_name IN ('student_id','owner_student_id')
                  AND table_schema NOT IN ('information_schema','pg_catalog')
                  AND table_schema NOT LIKE 'pg_%'
                  AND table_name <> 'users'
                """
            )
        )
    ).all()

    def _key(schema: str, table: str) -> str:
        # public 裸名、其余 schema 限定名——与 _STUDENT_TABLES 的写法对齐。
        return table if schema == "public" else f"{schema}.{table}"

    # parent_student 的 student_id 由 purge 单独处理（parent/student 双向），豁免。
    db_tables = {(_key(s, t), c) for s, t, c in rows if _key(s, t) != "parent_student"}
    covered = {(t, c) for t, c in _STUDENT_TABLES}
    missing = db_tables - covered
    assert not missing, (
        f"以下带未成年PII的表不在 purge 清单，删除后数据会残留（合规红线）：{sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_purge_removes_gate_tables(db):
    """gate 三表（pending_question/qualitative_mastery/evidence）有数据 → 硬删 →
    该学生记录清零（合规：门控 PII 随用户删除一并物理清除）。"""
    from services import gate_store

    sid = await _mk_user(db, deleted_days_ago=40)
    qid = f"q-{uuid.uuid4().hex}"
    ev_ref = uuid.uuid4().hex
    kc = "kc-gate-x"
    try:
        await gate_store.pose_question(
            db,
            question_id=qid,
            student_id=sid,
            kc_id=kc,
            prompt="p",
            expected="e",
            qtype="fill",
        )
        await gate_store.save_evidence(
            db,
            evidence_ref=ev_ref,
            student_id=sid,
            kc_id=kc,
            verdict={"passed": True},
            model_id="m",
        )
        await gate_store.upsert_qualitative_mastery(
            db,
            student_id=sid,
            kc_id=kc,
            passed=True,
            evidence_ref=ev_ref,
        )
        await db.flush()

        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert str(sid) in result["ids"]
        for tbl in (
            "gate.pending_question",
            "gate.qualitative_mastery",
            "gate.evidence",
        ):
            cnt = (
                await db.execute(
                    text(
                        f"SELECT count(*) FROM {tbl} "  # noqa: S608 表名来自内部常量
                        "WHERE student_id = CAST(:s AS uuid)"
                    ),
                    {"s": str(sid)},
                )
            ).scalar_one()
            assert cnt == 0, tbl
    finally:
        for tbl in (
            "gate.pending_question",
            "gate.qualitative_mastery",
            "gate.evidence",
        ):
            await db.execute(
                text(
                    f"DELETE FROM {tbl} WHERE student_id = CAST(:s AS uuid)"  # noqa: S608
                ),
                {"s": str(sid)},
            )
        await _cleanup(db, sid)
