"""Immersive Reading —— 教材原文阅读块 + 每人阅读位置（/v1/reading/*）。

红线：阅读位置只是进度，不进门控（静态断言 reading_service / 路由不碰 kc_mastery /
gate / process_interaction）；位置读写仅本人；系统教材之外的私有上传文件不出现在阅读块里；
新表在 purge 清单里。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import User, UserRole
from services.reading_service import (
    dedupe_overlaps,
    is_readable_chunk,
    textbook_blocks,
    tidy_chunk_text,
)

ROOT = Path(__file__).resolve().parents[1]
BODY = "物理学是研究物质及其运动规律的科学。人类自古以来就对自然界充满好奇，日出日落、春华秋实。"


def test_tidy_chunk_text_joins_cjk_line_breaks() -> None:
    raw = "人类自古以来就对自然界充满好\n奇。日出日落、辰宿 列张\n\n\n\nThe sun\nrises."
    assert (
        tidy_chunk_text(raw)
        == "人类自古以来就对自然界充满好奇。日出日落、辰宿列张\n\nThe sun rises."
    )
    assert (
        tidy_chunk_text("图\n0\n-\n2\n物质世界的空间尺度") == "图0-2物质世界的空间尺度"
    )
    assert (
        tidy_chunk_text("第一段结束。\n第二段开始了") == "第一段结束。\n\n第二段开始了"
    )


def test_readable_chunk_filter() -> None:
    assert is_readable_chunk(BODY)
    assert not is_readable_chunk("2 高中物理必修第一册")
    assert not is_readable_chunk(
        "第16课 三国鼎立........................ 80 第17课 西晋的短暂统一......... 85 第18课"
    )
    assert not is_readable_chunk(
        "目 录 第一章 运动的描述 1. 质点 参考系 2. 时间 位移 3. 位置变化快慢的描述——速度"
    )
    assert not is_readable_chunk(
        "ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆ᑓᄼ߆"
    )


def test_dedupe_overlapping_chunks_on_same_page() -> None:
    from types import SimpleNamespace as R

    rows = [
        R(
            id="a",
            file_id="f",
            page_number=1,
            section_title=None,
            content="0123456789",
            char_start=0,
            char_end=10,
        ),
        R(
            id="b",
            file_id="f",
            page_number=1,
            section_title=None,
            content="789ABC",
            char_start=7,
            char_end=13,
        ),
        R(
            id="c",
            file_id="f",
            page_number=1,
            section_title=None,
            content="9ABC",
            char_start=9,
            char_end=13,
        ),
        R(
            id="d",
            file_id="f",
            page_number=2,
            section_title=None,
            content="xyz",
            char_start=0,
            char_end=3,
        ),
    ]
    out = dedupe_overlaps(rows)
    assert [(c.id, c.content) for c in out] == [("a", "0123456789ABC"), ("d", "xyz")]


@pytest.fixture
async def reading_fixture():
    a, b = uuid.uuid4(), uuid.uuid4()
    tid = f"TEST-READ-{uuid.uuid4().hex[:8]}"
    sys_file, own_file = f"tf-{uuid.uuid4().hex[:12]}", f"tf-{uuid.uuid4().hex[:12]}"
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"175{str(a.int)[:8]}", role=UserRole.student))
        db.add(User(id=b, phone=f"176{str(b.int)[:8]}", role=UserRole.student))
        await db.flush()
        await db.execute(
            text(
                "INSERT INTO textbooks (id, subject, grade, edition, book_name) VALUES (:t, 'physics', 'G10', 'test', '测试物理')"
            ),
            {"t": tid},
        )
        for fid, owner in ((sys_file, None), (own_file, b)):
            await db.execute(
                text(
                    "INSERT INTO textbook_files (id, textbook_id, owner_student_id, filename, file_type, storage_path, index_status, chunk_count) "
                    "VALUES (:f, :t, :o, 'x.pdf', 'pdf', 'x', 'done', 3)"
                ),
                {"f": fid, "t": tid, "o": owner},
            )
        chunks = [
            (
                sys_file,
                0,
                "目 录 第一章 运动的描述 1. 质点 参考系 2. 时间 位移 3. 速度 4. 加速度",
            ),
            (sys_file, 1, BODY),
            (
                sys_file,
                2,
                "第一章 运动的描述。质点是用来代替物体的有质量的点，它是一种理想化的物理模型，研究问题时忽略次要因素。",
            ),
            (sys_file, 3, "短"),
            (
                own_file,
                0,
                "这是别的学生上传的私有笔记内容，不能出现在系统教材阅读里。" * 2,
            ),
        ]
        for fid, idx, content in chunks:
            await db.execute(
                text(
                    "INSERT INTO textbook_chunks (id, file_id, chunk_index, content, content_length, page_number) VALUES (:i, :f, :n, :c, :l, :n)"
                ),
                {
                    "i": f"ch-{uuid.uuid4().hex[:16]}",
                    "f": fid,
                    "n": idx,
                    "c": content,
                    "l": len(content),
                },
            )
        await db.commit()
    yield a, b, tid
    async with SessionLocal() as db:
        await db.execute(
            text("DELETE FROM reading_positions WHERE student_id = ANY(:ids)"),
            {"ids": [a, b]},
        )
        await db.execute(
            text("DELETE FROM textbook_files WHERE textbook_id = :t"), {"t": tid}
        )
        await db.execute(text("DELETE FROM textbooks WHERE id = :t"), {"t": tid})
        await db.execute(delete(User).where(User.id.in_([a, b])))
        await db.commit()


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


@pytest.mark.asyncio
async def test_textbook_blocks_skip_noise_and_private_files(reading_fixture):
    a, _b, tid = reading_fixture
    async with SessionLocal() as db:
        out = await textbook_blocks(db, tid, offset=0, limit=40)
    assert out is not None
    assert out["total"] == 2
    texts = [blk["payload"]["text"] for blk in out["blocks"]]
    assert texts[0] == BODY and texts[1].startswith("第一章")
    assert all("私有笔记" not in t for t in texts)
    assert [blk["index"] for blk in out["blocks"]] == [0, 1]
    async with SessionLocal() as db:
        page2 = await textbook_blocks(db, tid, offset=1, limit=1)
    assert page2 and [blk["index"] for blk in page2["blocks"]] == [1]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/reading/textbooks/{tid}?limit=10", headers=_h(a))
        assert r.status_code == 200 and r.json()["total"] == 2
        assert (
            await c.get("/v1/reading/textbooks/NOPE-NOT-THERE", headers=_h(a))
        ).status_code == 404
        assert (
            await c.get(f"/v1/reading/textbooks/{tid}?limit=1000", headers=_h(a))
        ).status_code == 422
        assert (await c.get(f"/v1/reading/textbooks/{tid}")).status_code == 401
        src = await c.get("/v1/reading/sources", headers=_h(a))
        assert src.status_code == 200
        mine = [t for t in src.json()["textbooks"] if t["textbook_id"] == tid]
        assert mine and mine[0]["has_book"] is False


@pytest.mark.asyncio
async def test_position_roundtrip_self_only(reading_fixture):
    a, b, tid = reading_fixture
    body = {
        "student_id": str(a),
        "source_kind": "textbook",
        "source_id": tid,
        "block_index": 1,
        "block_id": "blk-1",
        "total_blocks": 2,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        q = f"/v1/reading/position/{a}?source_kind=textbook&source_id={tid}"
        assert (await c.get(q, headers=_h(a))).json() == {"position": None}
        r = await c.put("/v1/reading/position", json=body, headers=_h(a))
        assert r.status_code == 200 and r.json()["position"]["block_index"] == 1
        # upsert：同一来源只保留一行，位置被更新
        r2 = await c.put(
            "/v1/reading/position",
            json={**body, "block_index": 0, "block_id": "blk-0"},
            headers=_h(a),
        )
        assert r2.status_code == 200
        got = (await c.get(q, headers=_h(a))).json()["position"]
        assert (
            got["block_index"] == 0
            and got["block_id"] == "blk-0"
            and got["total_blocks"] == 2
        )
        # 仅本人：别人读/写都 403，未登录 401
        assert (await c.get(q, headers=_h(b))).status_code == 403
        assert (
            await c.put("/v1/reading/position", json=body, headers=_h(b))
        ).status_code == 403
        assert (await c.get(q)).status_code == 401
        # 校验：越界 / 来源不存在 / 未知 kind / 多余字段
        assert (
            await c.put(
                "/v1/reading/position", json={**body, "block_index": 2}, headers=_h(a)
            )
        ).status_code == 422
        assert (
            await c.put(
                "/v1/reading/position",
                json={**body, "source_id": "NOPE-NOT-THERE"},
                headers=_h(a),
            )
        ).status_code == 422
        assert (
            await c.put(
                "/v1/reading/position",
                json={**body, "source_kind": "video"},
                headers=_h(a),
            )
        ).status_code == 422
        assert (
            await c.put(
                "/v1/reading/position", json={**body, "p_learned": 1.0}, headers=_h(a)
            )
        ).status_code == 422
        src = (await c.get("/v1/reading/sources", headers=_h(a))).json()
        assert [p for p in src["positions"] if p["source_id"] == tid][0][
            "block_index"
        ] == 0
    async with SessionLocal() as db:
        n = (
            await db.execute(
                text("SELECT count(*) FROM reading_positions WHERE student_id = :s"),
                {"s": a},
            )
        ).scalar()
        mastery = (
            await db.execute(
                text("SELECT count(*) FROM kc_mastery WHERE student_id = :s"), {"s": a}
            )
        ).scalar()
    assert n == 1
    assert mastery == 0, "reading must never write mastery"


def test_reading_positions_in_purge_inventory() -> None:
    from services.purge_service import _STUDENT_TABLES

    assert ("reading_positions", "student_id") in _STUDENT_TABLES


def _code_without_docs_and_comments(path: Path) -> str:
    import ast
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for i in range(node.lineno - 1, (node.end_lineno or node.lineno)):
                lines[i] = ""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines) + "\n").readline):
        if tok.type != tokenize.COMMENT:
            out.append(tok.string)
    return " ".join(out)


@pytest.mark.parametrize(
    "rel", ["services/reading_service.py", "services/routers/reading.py"]
)
def test_reading_never_touches_gating(rel: str) -> None:
    code = _code_without_docs_and_comments(ROOT / rel)
    for bad in (
        "kc_mastery",
        "gate_store",
        "gate.",
        "process_interaction",
        "verdict_guard",
        "KCMastery",
        "submit_answer",
        "providers",
    ):
        assert bad not in code, f"{rel}: {bad}"
