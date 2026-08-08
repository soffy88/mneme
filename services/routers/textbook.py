"""教材绑定 / 阅读器 / 高亮笔记 / RAG 问答（自 main 拆出）。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user, require_student_access
from services.models import Highlight, ReadingNote, Textbook, TextbookFile, User
from services.route_helpers import grade_sort_key as _grade_sort_key
from services.storage import content_type_for, download_file, upload_file
from services.textbook_bindings_service import (
    get_textbook_bindings,
    set_textbook_bindings,
)
from services.textbook_qa_service import (
    index_textbook_file,
    start_textbook_qa_session,
    textbook_qa_stream,
)

router = APIRouter(tags=["textbook"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_SUBJECT_ORDER = ["math", "physics", "chinese", "english", "history"]
_SUBJECT_NAMES = {
    "math": "数学",
    "physics": "物理",
    "chinese": "语文",
    "english": "英语",
    "history": "历史",
}


def _new_file_id() -> str:
    return str(uuid.uuid4())


def _new_str_id() -> str:
    return str(uuid.uuid4())


class TextbookBindingsReq(BaseModel):
    math: str | None = None
    physics: str | None = None
    chinese: str | None = None
    english: str | None = None


@router.get("/v1/users/{student_id}/textbook-bindings")
async def get_user_textbook_bindings(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return await get_textbook_bindings(db, student_id)


@router.post("/v1/users/{student_id}/textbook-bindings")
async def post_user_textbook_bindings(
    student_id: UUID,
    body: TextbookBindingsReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人偏好")
    updates = body.model_dump(exclude_unset=True)
    result = await set_textbook_bindings(db, student_id, updates)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/v1/textbooks")
async def list_textbooks_by_subject(
    subject: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Textbook).where(
        Textbook.subject == subject,
        ~Textbook.id.like("tb-lp-%"),
        Textbook.book_name != "练习教材",
    )
    rows = (await db.execute(stmt)).scalars().all()
    books = [
        {
            "textbook_id": tb.id,
            "book_name": tb.book_name,
            "grade": tb.grade,
            "edition": tb.edition,
        }
        for tb in rows
    ]
    books.sort(key=lambda x: _grade_sort_key(x["grade"]))
    return books


@router.post("/v1/textbook-files/upload", status_code=201)
async def upload_textbook_file(
    file: UploadFile = File(...),
    textbook_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or "untitled"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "epub"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 EPUB 文件")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（上限 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB）",
        )
    file_id = _new_file_id()
    from obase.admin_identity import is_admin

    is_platform = textbook_id is not None and is_admin(current_user)
    owner_id = None if is_platform else current_user.id
    storage_path = (
        f"{'platform' if is_platform else str(current_user.id)}/{file_id}.{ext}"
    )

    await asyncio.to_thread(upload_file, storage_path, data, content_type_for(ext))

    tf = TextbookFile(
        id=file_id,
        textbook_id=textbook_id,
        owner_student_id=owner_id,
        filename=filename,
        file_type=ext,
        storage_path=storage_path,
        file_size=len(data),
    )
    db.add(tf)
    await db.commit()

    extraction_triggered = False
    if textbook_id:
        try:
            from tasks.textbook_tasks import extract_textbook_file_task

            extract_textbook_file_task.delay(file_id)
            extraction_triggered = True
        except Exception:
            pass

    return {
        "file_id": file_id,
        "filename": filename,
        "file_type": ext,
        "file_size": len(data),
        "storage_path": storage_path,
        "extraction_triggered": extraction_triggered,
    }


@router.get("/v1/textbook-files/{file_id}/meta")
async def get_textbook_file_meta(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")
    return {
        "file_id": tf.id,
        "textbook_id": tf.textbook_id,
        "owner_student_id": str(tf.owner_student_id) if tf.owner_student_id else None,
        "filename": tf.filename,
        "file_type": tf.file_type,
        "file_size": tf.file_size,
        "has_text_layer": tf.has_text_layer,
        "uploaded_at": tf.uploaded_at.isoformat(),
    }


@router.get("/v1/textbook-files")
async def list_textbook_files(
    textbook_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if textbook_id:
        stmt = (
            select(TextbookFile)
            .where(
                or_(
                    (TextbookFile.textbook_id == textbook_id)
                    & (TextbookFile.owner_student_id == None),  # noqa: E711
                    (TextbookFile.textbook_id == textbook_id)
                    & (TextbookFile.owner_student_id == current_user.id),
                )
            )
            .order_by(TextbookFile.uploaded_at.desc())
        )
    else:
        stmt = (
            select(TextbookFile)
            .where(TextbookFile.owner_student_id == current_user.id)
            .order_by(TextbookFile.uploaded_at.desc())
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "file_id": r.id,
            "textbook_id": r.textbook_id,
            "owner_student_id": str(r.owner_student_id) if r.owner_student_id else None,
            "filename": r.filename,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "has_text_layer": r.has_text_layer,
            "uploaded_at": r.uploaded_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/v1/library/textbooks")
async def list_library_textbooks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(TextbookFile, Textbook)
        .join(Textbook, TextbookFile.textbook_id == Textbook.id)
        .where(
            TextbookFile.owner_student_id == None,  # noqa: E711
            ~Textbook.id.like("tb-lp-%"),
            Textbook.book_name != "练习教材",
        )
    )
    rows = (await db.execute(stmt)).all()

    grouped: dict[str, list] = {s: [] for s in _SUBJECT_ORDER}
    for tf, tb in rows:
        if tb.subject not in grouped:
            continue
        grouped[tb.subject].append(
            {
                "textbook_id": tb.id,
                "book_name": tb.book_name,
                "grade": tb.grade,
                "edition": tb.edition,
                "file_id": tf.id,
                "has_text_layer": tf.has_text_layer,
            }
        )

    subjects = []
    for subject in _SUBJECT_ORDER:
        books = sorted(grouped[subject], key=lambda x: _grade_sort_key(x["grade"]))
        subjects.append(
            {
                "subject": subject,
                "name": _SUBJECT_NAMES[subject],
                "textbooks": books,
            }
        )
    return {"subjects": subjects}


@router.get("/v1/textbook-files/{file_id}/content")
async def get_textbook_file_content(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    try:
        data = await asyncio.to_thread(download_file, tf.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="存储对象不存在") from None

    ct = content_type_for(tf.file_type)
    import urllib.parse

    safe_name = urllib.parse.quote(tf.filename, safe="")
    return Response(
        content=data,
        media_type=ct,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
        },
    )


class HighlightCreate(BaseModel):
    file_id: str
    color: str = "yellow"
    text: str
    note: str | None = None
    location_json: dict = {}


class HighlightPatch(BaseModel):
    color: str | None = None
    note: str | None = None


def _hl_dict(hl: Highlight) -> dict:
    return {
        "id": hl.id,
        "file_id": hl.file_id,
        "student_id": str(hl.student_id),
        "color": hl.color,
        "text": hl.highlighted_text,
        "note": hl.note,
        "location_json": hl.location_json,
        "created_at": hl.created_at.isoformat(),
        "updated_at": hl.updated_at.isoformat(),
    }


@router.post("/v1/highlights", status_code=201)
async def create_highlight(
    body: HighlightCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == body.file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")
    if body.color not in ("yellow", "green", "blue", "red"):
        raise HTTPException(
            status_code=400, detail="color 必须是 yellow/green/blue/red 之一"
        )

    hl = Highlight(
        id=_new_str_id(),
        student_id=current_user.id,
        file_id=body.file_id,
        color=body.color,
        highlighted_text=body.text,
        note=body.note,
        location_json=body.location_json,
    )
    db.add(hl)
    await db.commit()
    await db.refresh(hl)
    return _hl_dict(hl)


@router.get("/v1/highlights")
async def list_highlights(
    file_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Highlight).where(Highlight.student_id == current_user.id)
    if file_id:
        stmt = stmt.where(Highlight.file_id == file_id)
    stmt = stmt.order_by(Highlight.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_hl_dict(r) for r in rows]


@router.patch("/v1/highlights/{highlight_id}")
async def patch_highlight(
    highlight_id: str,
    body: HighlightPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hl = (
        await db.execute(
            select(Highlight).where(
                Highlight.id == highlight_id, Highlight.student_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if not hl:
        raise HTTPException(status_code=404, detail="高亮不存在")
    if body.color is not None:
        hl.color = body.color
    if body.note is not None:
        hl.note = body.note
    hl.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(hl)
    return _hl_dict(hl)


@router.delete("/v1/highlights/{highlight_id}", status_code=204)
async def delete_highlight(
    highlight_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hl = (
        await db.execute(
            select(Highlight).where(
                Highlight.id == highlight_id, Highlight.student_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if not hl:
        raise HTTPException(status_code=404, detail="高亮不存在")
    await db.execute(
        update(ReadingNote)
        .where(ReadingNote.highlight_id == highlight_id)
        .values(highlight_id=None)
    )
    await db.delete(hl)
    await db.commit()


class ReadingNoteCreate(BaseModel):
    file_id: str | None = None
    title: str | None = None
    content: str | None = None
    highlight_id: str | None = None


class ReadingNotePatch(BaseModel):
    title: str | None = None
    content: str | None = None


def _rn_dict(rn: ReadingNote) -> dict:
    return {
        "id": rn.id,
        "student_id": str(rn.student_id),
        "file_id": rn.file_id,
        "title": rn.title,
        "content": rn.content,
        "highlight_id": rn.highlight_id,
        "created_at": rn.created_at.isoformat(),
        "updated_at": rn.updated_at.isoformat(),
    }


@router.post("/v1/reading-notes", status_code=201)
async def create_reading_note(
    body: ReadingNoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.highlight_id:
        hl = (
            await db.execute(
                select(Highlight).where(
                    Highlight.id == body.highlight_id,
                    Highlight.student_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if not hl:
            raise HTTPException(status_code=404, detail="高亮不存在")

    rn = ReadingNote(
        id=_new_str_id(),
        student_id=current_user.id,
        file_id=body.file_id,
        title=body.title,
        content=body.content,
        highlight_id=body.highlight_id,
    )
    db.add(rn)
    await db.commit()
    await db.refresh(rn)
    return _rn_dict(rn)


@router.get("/v1/reading-notes")
async def list_reading_notes(
    file_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ReadingNote).where(
        ReadingNote.student_id == current_user.id,
        ReadingNote.deleted_at == None,  # noqa: E711
    )
    if file_id:
        stmt = stmt.where(ReadingNote.file_id == file_id)
    stmt = stmt.order_by(ReadingNote.updated_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_rn_dict(r) for r in rows]


@router.patch("/v1/reading-notes/{note_id}")
async def patch_reading_note(
    note_id: str,
    body: ReadingNotePatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rn = (
        await db.execute(
            select(ReadingNote).where(
                ReadingNote.id == note_id,
                ReadingNote.student_id == current_user.id,
                ReadingNote.deleted_at == None,  # noqa: E711
            )
        )
    ).scalar_one_or_none()
    if not rn:
        raise HTTPException(status_code=404, detail="笔记不存在")
    if body.title is not None:
        rn.title = body.title
    if body.content is not None:
        rn.content = body.content
    rn.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(rn)
    return _rn_dict(rn)


@router.delete("/v1/reading-notes/{note_id}", status_code=204)
async def delete_reading_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rn = (
        await db.execute(
            select(ReadingNote).where(
                ReadingNote.id == note_id,
                ReadingNote.student_id == current_user.id,
                ReadingNote.deleted_at == None,  # noqa: E711
            )
        )
    ).scalar_one_or_none()
    if not rn:
        raise HTTPException(status_code=404, detail="笔记不存在")
    rn.deleted_at = datetime.now(UTC)
    await db.commit()


@router.post("/v1/textbook-kb/index/{file_id}")
async def index_textbook_for_rag(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")

    storage_prefix = os.environ.get("STORAGE_LOCAL_DIR", "/tmp/mneme_storage")
    file_path = os.path.join(storage_prefix, tf.storage_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件实体不存在")

    with open(file_path, "rb") as f:
        file_data = f.read()

    return await index_textbook_file(
        db, file_id=file_id, file_data=file_data, file_type=tf.file_type
    )


class TextbookQARequest(BaseModel):
    file_id: str
    question: str


@router.post("/v1/textbook-files/{file_id}/qa")
async def start_textbook_qa(
    file_id: str,
    req: TextbookQARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404)

    return await start_textbook_qa_session(
        db, file_id=file_id, student_id=current_user.id, first_question=req.question
    )


@router.post("/v1/textbook-files/qa/{session_id}/message")
async def continue_textbook_qa(
    session_id: uuid.UUID,
    req: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student_message = req.get("message", "")
    return StreamingResponse(
        textbook_qa_stream(db, session_id=session_id, student_message=student_message),
        media_type="text/event-stream",
    )
