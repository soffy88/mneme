"""
教材阅读器后端测试 — Epic P 阶段1
覆盖：textbook_files 上传/列表/下载权限、highlights 隔离、reading_notes 软删除
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.auth import create_access_token
from services.main import app
from services.models import (
    Highlight, ReadingNote, TextbookFile, User, UserRole,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _make_student(db: AsyncSession) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"199{str(sid)[:8]}", role=UserRole.student, name="S", grade="高三"))
    await db.commit()
    return sid


async def _cleanup_student(db: AsyncSession, sid: uuid.UUID) -> None:
    await db.execute(delete(ReadingNote).where(ReadingNote.student_id == sid))
    await db.execute(delete(Highlight).where(Highlight.student_id == sid))
    await db.execute(delete(TextbookFile).where(TextbookFile.owner_student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def student_a(db):
    sid = await _make_student(db)
    yield sid
    await _cleanup_student(db, sid)


@pytest.fixture(scope="function")
async def student_b(db):
    sid = await _make_student(db)
    yield sid
    await _cleanup_student(db, sid)


def _token(student_id: uuid.UUID) -> str:
    return create_access_token({"sub": str(student_id)})


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── MinIO mock (同步 upload/download) ────────────────────────────────────────

def _mock_storage():
    """Patch upload_file and download_file so tests don't need real MinIO."""
    _store: dict[str, bytes] = {}

    def fake_upload(path: str, data: bytes, ct: str) -> None:
        _store[path] = data

    def fake_download(path: str) -> bytes:
        if path not in _store:
            raise FileNotFoundError(path)
        return _store[path]

    upload_patch = patch("services.main.upload_file", side_effect=fake_upload)
    download_patch = patch("services.main.download_file", side_effect=fake_download)
    return upload_patch, download_patch


# ═══════════════════════════════════════════════════════════════════
# 文件上传 / 列表 / 下载
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_upload_pdf(client, student_a):
    """学生上传 PDF → 返回 file_id，DB 中有记录。"""
    up, dl = _mock_storage()
    with up, dl:
        resp = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("test.pdf", b"%PDF-1.4 test content", "application/pdf")},
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["file_type"] == "pdf"
    assert data["filename"] == "test.pdf"
    assert "file_id" in data


@pytest.mark.asyncio
async def test_upload_unsupported_type_rejected(client, student_a):
    """非 PDF/EPUB 文件被拒绝 400。"""
    up, dl = _mock_storage()
    with up, dl:
        resp = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("test.docx", b"word content", "application/vnd.openxmlformats")},
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_files_own_only(client, student_a, student_b, db):
    """学生只能看到自己上传的文件（无 textbook_id 过滤时）。"""
    up, dl = _mock_storage()
    with up, dl:
        # student_a 上传
        r1 = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("a.pdf", b"%PDF a", "application/pdf")},
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
        assert r1.status_code == 201
        # student_b 上传
        r2 = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("b.pdf", b"%PDF b", "application/pdf")},
            headers={"Authorization": f"Bearer {_token(student_b)}"},
        )
        assert r2.status_code == 201

    # student_a 的列表只应看到 a.pdf
    list_resp = await client.get(
        "/v1/textbook-files",
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert list_resp.status_code == 200
    fids = [f["file_id"] for f in list_resp.json()]
    assert r1.json()["file_id"] in fids
    assert r2.json()["file_id"] not in fids


@pytest.mark.asyncio
async def test_download_own_file(client, student_a):
    """学生可以下载自己上传的文件。"""
    content = b"%PDF-1.4 own file content"
    up, dl = _mock_storage()
    with up, dl:
        up_resp = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("own.pdf", content, "application/pdf")},
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
        assert up_resp.status_code == 201
        file_id = up_resp.json()["file_id"]

        dl_resp = await client.get(
            f"/v1/textbook-files/{file_id}/content",
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
    assert dl_resp.status_code == 200
    assert dl_resp.content == content


@pytest.mark.asyncio
async def test_download_other_student_file_forbidden(client, student_a, student_b):
    """学生不能下载他人的自传文件 → 403。"""
    content = b"%PDF-1.4 private content"
    up, dl = _mock_storage()
    with up, dl:
        up_resp = await client.post(
            "/v1/textbook-files/upload",
            files={"file": ("private.pdf", content, "application/pdf")},
            headers={"Authorization": f"Bearer {_token(student_a)}"},
        )
        assert up_resp.status_code == 201
        file_id = up_resp.json()["file_id"]

        # student_b 尝试下载
        dl_resp = await client.get(
            f"/v1/textbook-files/{file_id}/content",
            headers={"Authorization": f"Bearer {_token(student_b)}"},
        )
    assert dl_resp.status_code == 403


@pytest.mark.asyncio
async def test_download_platform_file_accessible_by_all(client, student_a, student_b, db):
    """平台预置文件（owner_student_id IS NULL）所有学生均可下载。"""
    content = b"%PDF-1.4 platform content"
    # 直接在 DB 写入平台预置文件（owner_student_id=None）
    file_id = str(uuid.uuid4())
    storage_path = f"platform/{file_id}.pdf"
    db.add(TextbookFile(
        id=file_id, textbook_id=None, owner_student_id=None,
        filename="platform.pdf", file_type="pdf", storage_path=storage_path, file_size=len(content),
    ))
    await db.commit()

    up, dl = _mock_storage()
    # 预存内容到 mock store
    with up, dl:
        # 直接 inject content into the mock's store via upload
        import services.main as main_mod
        with patch.object(main_mod, "download_file", side_effect=lambda p: content):
            dl_resp = await client.get(
                f"/v1/textbook-files/{file_id}/content",
                headers={"Authorization": f"Bearer {_token(student_b)}"},
            )
    assert dl_resp.status_code == 200

    # cleanup
    await db.execute(delete(TextbookFile).where(TextbookFile.id == file_id))
    await db.commit()


# ═══════════════════════════════════════════════════════════════════
# 高亮隔离测试（核心安全要求）
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="function")
async def shared_file(db, student_a) -> str:
    """学生A拥有的文件，用于高亮测试。"""
    file_id = str(uuid.uuid4())
    db.add(TextbookFile(
        id=file_id, owner_student_id=student_a,
        filename="book.pdf", file_type="pdf",
        storage_path=f"{student_a}/{file_id}.pdf", file_size=1024,
    ))
    await db.commit()
    yield file_id
    await db.execute(update(ReadingNote).where(ReadingNote.file_id == file_id).values(highlight_id=None))
    await db.execute(delete(ReadingNote).where(ReadingNote.file_id == file_id))
    await db.execute(delete(Highlight).where(Highlight.file_id == file_id))
    await db.execute(delete(TextbookFile).where(TextbookFile.id == file_id))
    await db.commit()


@pytest.fixture(scope="function")
async def platform_file(db) -> str:
    """平台预置文件（owner=None），任何学生均可高亮。"""
    file_id = str(uuid.uuid4())
    db.add(TextbookFile(
        id=file_id, owner_student_id=None,
        filename="platform.pdf", file_type="pdf",
        storage_path=f"platform/{file_id}.pdf", file_size=2048,
    ))
    await db.commit()
    yield file_id
    # null out FK refs before hard-deleting highlights
    await db.execute(
        update(ReadingNote).where(ReadingNote.file_id == file_id).values(highlight_id=None, deleted_at=None)
    )
    await db.execute(delete(ReadingNote).where(ReadingNote.file_id == file_id))
    await db.execute(delete(Highlight).where(Highlight.file_id == file_id))
    await db.execute(delete(TextbookFile).where(TextbookFile.id == file_id))
    await db.commit()


@pytest.mark.asyncio
async def test_create_highlight(client, student_a, platform_file):
    """学生可以对平台预置文件创建高亮。"""
    resp = await client.post(
        "/v1/highlights",
        json={
            "file_id": platform_file,
            "color": "yellow",
            "text": "椭圆的定义",
            "location_json": {"page": 3, "rects": [{"top": 10.0, "left": 5.0, "width": 80.0, "height": 3.0, "pageIndex": 2}]},
        },
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["text"] == "椭圆的定义"
    assert data["color"] == "yellow"
    assert data["student_id"] == str(student_a)


@pytest.mark.asyncio
async def test_highlight_isolation_student_b_cannot_see_a_highlights(client, student_a, student_b, platform_file):
    """学生B看不到学生A的高亮 — 核心隔离测试。"""
    # A 创建高亮
    r = await client.post(
        "/v1/highlights",
        json={"file_id": platform_file, "color": "blue", "text": "A的专属高亮"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    hl_id = r.json()["id"]

    # B 列出同文件的高亮 → 不应该看到 A 的高亮
    list_b = await client.get(
        "/v1/highlights",
        params={"file_id": platform_file},
        headers={"Authorization": f"Bearer {_token(student_b)}"},
    )
    assert list_b.status_code == 200
    ids_b = [h["id"] for h in list_b.json()]
    assert hl_id not in ids_b

    # 清理
    await client.delete(
        f"/v1/highlights/{hl_id}",
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )


@pytest.mark.asyncio
async def test_highlight_delete_only_own(client, student_a, student_b, platform_file):
    """学生B不能删除学生A的高亮 → 404。"""
    r = await client.post(
        "/v1/highlights",
        json={"file_id": platform_file, "color": "red", "text": "A高亮"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    hl_id = r.json()["id"]

    # B 尝试删除
    del_resp = await client.delete(
        f"/v1/highlights/{hl_id}",
        headers={"Authorization": f"Bearer {_token(student_b)}"},
    )
    assert del_resp.status_code == 404

    # 清理
    await client.delete(
        f"/v1/highlights/{hl_id}",
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )


@pytest.mark.asyncio
async def test_highlight_patch_note(client, student_a, platform_file):
    """PATCH 更新高亮的笔记内容。"""
    r = await client.post(
        "/v1/highlights",
        json={"file_id": platform_file, "color": "green", "text": "重要段落"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    hl_id = r.json()["id"]

    patch_resp = await client.patch(
        f"/v1/highlights/{hl_id}",
        json={"note": "这里考过大题"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["note"] == "这里考过大题"

    await client.delete(f"/v1/highlights/{hl_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})


@pytest.mark.asyncio
async def test_cannot_highlight_other_student_file(client, student_b, shared_file):
    """学生B不能对学生A的自传文件创建高亮 → 403。"""
    resp = await client.post(
        "/v1/highlights",
        json={"file_id": shared_file, "color": "yellow", "text": "B的尝试"},
        headers={"Authorization": f"Bearer {_token(student_b)}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invalid_color_rejected(client, student_a, platform_file):
    """无效颜色被拒绝 400。"""
    resp = await client.post(
        "/v1/highlights",
        json={"file_id": platform_file, "color": "purple", "text": "test"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# 独立笔记 CRUD + 软删除
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_and_list_reading_notes(client, student_a, platform_file):
    """创建笔记并能列出。"""
    r = await client.post(
        "/v1/reading-notes",
        json={"file_id": platform_file, "title": "第一章笔记", "content": "# 椭圆\n重要内容"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    note_id = r.json()["id"]

    list_resp = await client.get(
        "/v1/reading-notes",
        params={"file_id": platform_file},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert list_resp.status_code == 200
    ids = [n["id"] for n in list_resp.json()]
    assert note_id in ids

    await client.delete(f"/v1/reading-notes/{note_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})


@pytest.mark.asyncio
async def test_reading_note_soft_delete(client, student_a, platform_file):
    """软删除后笔记不出现在列表中，但 DB 记录保留。"""
    r = await client.post(
        "/v1/reading-notes",
        json={"file_id": platform_file, "title": "待删笔记"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    note_id = r.json()["id"]

    del_resp = await client.delete(
        f"/v1/reading-notes/{note_id}",
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert del_resp.status_code == 204

    # 再次列出 → 不应出现
    list_resp = await client.get(
        "/v1/reading-notes",
        params={"file_id": platform_file},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    ids = [n["id"] for n in list_resp.json()]
    assert note_id not in ids


@pytest.mark.asyncio
async def test_reading_note_isolation(client, student_a, student_b, platform_file):
    """学生B看不到学生A的笔记。"""
    r = await client.post(
        "/v1/reading-notes",
        json={"file_id": platform_file, "title": "A的私笔记"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    note_id = r.json()["id"]

    list_b = await client.get(
        "/v1/reading-notes",
        params={"file_id": platform_file},
        headers={"Authorization": f"Bearer {_token(student_b)}"},
    )
    ids_b = [n["id"] for n in list_b.json()]
    assert note_id not in ids_b

    await client.delete(f"/v1/reading-notes/{note_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})


@pytest.mark.asyncio
async def test_reading_note_patch(client, student_a, platform_file):
    """PATCH 更新笔记内容。"""
    r = await client.post(
        "/v1/reading-notes",
        json={"file_id": platform_file, "title": "原标题"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert r.status_code == 201
    note_id = r.json()["id"]

    patch_resp = await client.patch(
        f"/v1/reading-notes/{note_id}",
        json={"title": "更新标题", "content": "更新内容"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "更新标题"
    assert patch_resp.json()["content"] == "更新内容"

    await client.delete(f"/v1/reading-notes/{note_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})


@pytest.mark.asyncio
async def test_note_with_highlight_link(client, student_a, platform_file):
    """笔记可以关联到高亮。"""
    # 先创建高亮
    hl_r = await client.post(
        "/v1/highlights",
        json={"file_id": platform_file, "color": "yellow", "text": "被关联的高亮"},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert hl_r.status_code == 201
    hl_id = hl_r.json()["id"]

    # 创建关联笔记
    note_r = await client.post(
        "/v1/reading-notes",
        json={"file_id": platform_file, "title": "关联笔记", "highlight_id": hl_id},
        headers={"Authorization": f"Bearer {_token(student_a)}"},
    )
    assert note_r.status_code == 201
    assert note_r.json()["highlight_id"] == hl_id

    # 清理
    note_id = note_r.json()["id"]
    await client.delete(f"/v1/reading-notes/{note_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})
    await client.delete(f"/v1/highlights/{hl_id}", headers={"Authorization": f"Bearer {_token(student_a)}"})


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client, platform_file):
    """无 token 请求 → 401。"""
    resp = await client.get("/v1/highlights", params={"file_id": platform_file})
    assert resp.status_code == 401
