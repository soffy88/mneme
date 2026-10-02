"""GetWordEnrichment（/mcp/GetWordEnrichment）—— 词汇增强层的对外契约。

这是词根词缀（379 条）与象形9000（1,219 条）第一次有了对外读取路径，所以本测试
盯的不是「能不能取到数」，而是**取到之后前端能不能正确区分事实与联想**：

1. `is_source_bearing` 必须随 `etymology_status` 一起返回，且只有
   `reference_confirmed` 为 true —— 否则前端会把散文标注的「记忆联想」当词源讲。
2. `should_display=False`（disputed，与参考表冲突）前端须能据此不展示。
3. `ownership_verified=False` 的象形条目须能被前端识别并降级（多为 OCR 形近字）。
4. `ipa_ascii` 是**粗 ASCII 转写**，不能与 vocabulary_items 的 ARPAbet 混渲染。
5. 查不到的词不报错（呈现层缺失不该打断前端），与 tool_get_book 同约定。

**自包含夹具**：mneme_test 由 ORM metadata 建表而非 alembic（见
tests/test_nce_import_db.py 的 db_session 约定），所以这里自己建表 + 自己播种 +
测完清理，不依赖也不触碰生产库数据。
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from obase.db import SessionLocal
from services.mcp_router import tool_get_word_enrichment

# mneme_test 由 ORM metadata 建表（见文件头说明），不是跑 alembic，所以这里把
# 两条后加的 schema 变更补上：etymology_status 列（a3b4c5d6e7f8）与
# root 可空（b9c8d7e6f5a4，否则只讲清「前缀+后缀」的词根本插不进去）。
AFFIX_ALTERS = (
    "ALTER TABLE vocabulary_affixes ADD COLUMN IF NOT EXISTS "
    "etymology_status VARCHAR(24) NOT NULL DEFAULT 'mnemonic_association'",
    "ALTER TABLE vocabulary_affixes ALTER COLUMN root DROP NOT NULL",
)


@pytest.fixture
async def enriched_words():
    """建表（IF NOT EXISTS）+ 播种三个代表词，测完删掉自己播的行。"""
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    seeded: list[str] = []

    async with engine.begin() as conn:
        for alter in AFFIX_ALTERS:
            await conn.execute(text(alter))

        def _create(sync_conn):
            from services.models import Base, VocabularyXiangxing

            Base.metadata.create_all(
                bind=sync_conn, tables=[VocabularyXiangxing.__table__], checkfirst=True
            )

        await conn.run_sync(_create)

    async with SessionLocal() as db:
        # confirmed：有参考表佐证，可当词源讲
        # mnemonic：散文把后缀写成「词根」，只能当记忆联想
        # disputed：与参考表冲突，前端应默认不展示
        specs = [
            ("zzconfirmed", "ar", "rive", None, "reference_confirmed"),
            ("zzmnemonic", None, None, "less", "mnemonic_association"),
            ("zzdisputed", "pre", None, "able", "disputed"),
        ]
        for word, pre, root, suf, status in specs:
            vid = f"zz-{uuid.uuid4().hex[:12]}"
            seeded.append(vid)
            await db.execute(
                text(
                    "INSERT INTO vocabulary_items (id, word, meaning_cn, pos, source, "
                    "frequency_rank, frequency_band, ai_generated) "
                    "VALUES (:id, :w, '测试义项', 'n', 'TEST', 99999, 3, false)"
                ),
                {"id": vid, "w": word},
            )
            await db.execute(
                text(
                    "INSERT INTO vocabulary_affixes (vocabulary_item_id, prefix, root, "
                    "suffix, source, etymology_status) VALUES (:v, :p, :r, :s, 'TEST', :st)"
                ),
                {"v": vid, "p": pre, "r": root, "s": suf, "st": status},
            )
        # 象形条目：一条已验证、一条未验证（OCR 形近字）
        for word, verified in (("zzxiangxing", True), ("zzxiangxingbad", False)):
            vid = f"zz-{uuid.uuid4().hex[:12]}"
            seeded.append(vid)
            await db.execute(
                text(
                    "INSERT INTO vocabulary_items (id, word, meaning_cn, pos, source, "
                    "frequency_rank, frequency_band, ai_generated) "
                    "VALUES (:id, :w, '测试义项', 'n', 'TEST', 99999, 3, false)"
                ),
                {"id": vid, "w": word},
            )
            await db.execute(
                text(
                    "INSERT INTO vocabulary_xiangxing (vocabulary_item_id, ipa_ascii, pos, "
                    "meaning_cn, example_en, source_volume, ownership_verified) "
                    "VALUES (:v, '[tst]', 'n', '测试释义', 'A zzxiangxing test.', 'TEST', :ok)"
                ),
                {"v": vid, "ok": verified},
            )
        await db.commit()

    yield

    async with SessionLocal() as db:
        for vid in seeded:
            await db.execute(text("DELETE FROM vocabulary_items WHERE id = :v"), {"v": vid})
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_affix_is_source_bearing(enriched_words):
    """已由参考表佐证 -> 可当词源讲，展示串不带任何标注后缀。"""
    async with SessionLocal() as db:
        got = await tool_get_word_enrichment(db, "zzconfirmed")
    affix = got["affix"]
    assert got["found"] is True
    assert affix["chain"] == "ar · rive"
    assert affix["etymology_status"] == "reference_confirmed"
    assert affix["is_source_bearing"] is True
    assert affix["display_chain"] == "ar · rive"


@pytest.mark.asyncio
async def test_mnemonic_affix_is_labelled_and_not_source_bearing(enriched_words):
    """散文把后缀写成「词根」-> 只能当记忆联想讲，必须带标注。"""
    async with SessionLocal() as db:
        got = await tool_get_word_enrichment(db, "zzmnemonic")
    affix = got["affix"]
    assert affix["etymology_status"] == "mnemonic_association"
    assert affix["is_source_bearing"] is False
    assert "记忆联想" in affix["display_chain"]


@pytest.mark.asyncio
async def test_disputed_is_flagged_as_do_not_display(enriched_words):
    """与参考表冲突 -> 前端须能据此不展示。"""
    async with SessionLocal() as db:
        got = await tool_get_word_enrichment(db, "zzdisputed")
    assert got["affix"]["should_display"] is False


@pytest.mark.asyncio
async def test_xiangxing_exposes_ascii_ipa_and_ownership(enriched_words):
    async with SessionLocal() as db:
        ok = await tool_get_word_enrichment(db, "zzxiangxing")
        bad = await tool_get_word_enrichment(db, "zzxiangxingbad")
    # 字段名即隔离：粗 ASCII 转写，不是标准 IPA
    assert "ipa_ascii" in ok["xiangxing"]
    assert "arpabet" not in ok["xiangxing"]
    assert ok["xiangxing"]["ownership_verified"] is True
    # 未验证的须能被前端识别并降级
    assert bad["xiangxing"]["ownership_verified"] is False


@pytest.mark.asyncio
async def test_word_with_only_one_layer(enriched_words):
    """只有象形、没有词缀 -> affix 应为 None 而非空壳。"""
    async with SessionLocal() as db:
        got = await tool_get_word_enrichment(db, "zzxiangxing")
    assert got["affix"] is None
    assert got["xiangxing"] is not None


@pytest.mark.asyncio
async def test_unknown_word_does_not_raise():
    """呈现层缺失不该打断前端（同 tool_get_book 约定）。"""
    async with SessionLocal() as db:
        got = await tool_get_word_enrichment(db, "zzzznotaword")
    assert got == {"word": "zzzznotaword", "found": False, "affix": None, "xiangxing": None}


@pytest.mark.asyncio
async def test_lookup_is_case_insensitive(enriched_words):
    async with SessionLocal() as db:
        lower = await tool_get_word_enrichment(db, "zzconfirmed")
        upper = await tool_get_word_enrichment(db, "  ZZCONFIRMED ")
    assert lower["affix"]["chain"] == upper["affix"]["chain"]


@pytest.mark.asyncio
async def test_rejects_invalid_word():
    """超长/空串必须拒，而不是拿去打库。"""
    async with SessionLocal() as db:
        for bad in ("", "   ", "x" * 65):
            with pytest.raises(ValueError):
                await tool_get_word_enrichment(db, bad)