"""
textbook_qa_service.py — 教材问答服务（RAG + 苏格拉底引导）

3O 边界：
  oprim.embed_chunks  → 分块 + 向量化
  oprim.retrieve_chunks → 向量检索 + 格式化
  本服务（oskill 层）→ RAG 检索 + LLM 引导生成 + 会话存储

红线（继承苏格拉底核心）：
  - 不直接给答案，只给引用+引导问题
  - 引用必须溯源到教材 page/section
  - 若无检索结果，明确告知「未在教材中找到」，不瞎编
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import text as sa_text, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.anon import anon_ref

logger = logging.getLogger(__name__)

# ── LLM 调用 ──────────────────────────────────────────────────────────────────


def _get_caller():
    """获取 LLM caller（复用现有 provider 配置）。"""
    from services.providers.ollama_caller import OllamaCaller

    # 优先 OpenAI，若无 key 则用 Ollama
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        import openai as _openai

        class _OpenAICaller:
            def __init__(self):
                self._client = _openai.AsyncOpenAI(api_key=openai_key)
                self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

            async def __call__(self, *, messages, system=None, max_tokens=800, **_):
                msgs = list(messages)
                if system:
                    msgs.insert(0, {"role": "system", "content": system})
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    messages=msgs,
                    max_tokens=max_tokens,
                )
                return {"content": resp.choices[0].message.content or ""}

        return _OpenAICaller()
    return OllamaCaller()


# ── 系统提示（苏格拉底+引用约束）────────────────────────────────────────────────


def _build_system_prompt(context: str, learner_profile: str = "") -> str:
    profile_section = (
        f"\n\n<learner_profile>\n{learner_profile}\n</learner_profile>"
        if learner_profile
        else ""
    )
    return f"""你是一位教学助手，正在帮助学生理解他们上传的教材。

<教学原则>
1. **引用溯源**：你的每个引导都必须基于下方 <context> 中的教材内容，并注明来源（如「根据教材 p.23」）。
2. **苏格拉底引导**：不要直接给出完整答案，而是提出引导性问题，帮助学生自己推导。
3. **诚实边界**：若 <context> 中没有相关内容，明确说「这个问题在你上传的教材中未找到对应内容」，不要凭空编造。
4. **简洁有力**：回答控制在 150 字以内，每次只提一个引导问题。
</教学原则>

<context>
{context if context else "（未检索到相关教材内容）"}
</context>{profile_section}"""


# ── 会话管理 ──────────────────────────────────────────────────────────────────


async def start_textbook_qa_session(
    db: AsyncSession,
    *,
    file_id: str,
    student_id: uuid.UUID,
    first_question: str,
) -> dict:
    """
    开始教材问答会话。
    返回 {session_id, answer, citations}
    """
    from oprim.retrieve_chunks import retrieve_chunks, format_chunks_as_context
    from oprim.learner_profile_summary import get_latest_learner_profile
    from services.models import SocraticSession, SocraticMode

    # 获取学习者 L2 画像
    learner_profile = await get_latest_learner_profile(db, student_id)

    # 检索相关 chunks
    chunks = await retrieve_chunks(db, file_id=file_id, query=first_question, top_k=5)
    context = format_chunks_as_context(chunks)
    citations = [
        {
            "citation": c.citation,
            "page": c.page_number,
            "section": c.section_title,
            "score": round(c.score, 3),
        }
        for c in chunks
    ]

    # 生成首次引导
    caller = _get_caller()
    system = _build_system_prompt(context, learner_profile)
    result = await caller(
        messages=[{"role": "user", "content": first_question}],
        system=system,
        max_tokens=400,
    )
    answer = result.get("content", "请稍后再试。")

    # 存会话（复用 SocraticSession 表，mode=textbook_qa）
    session_id = uuid.uuid4()
    session = SocraticSession(
        id=session_id,
        student_id=student_id,
        mode=SocraticMode.textbook_qa
        if hasattr(SocraticMode, "textbook_qa")
        else SocraticMode.reading_guide,
        messages={
            "file_id": file_id,
            "history": [
                {"role": "user", "content": first_question},
                {"role": "assistant", "content": answer, "citations": citations},
            ],
        },
    )
    db.add(session)
    await db.commit()

    return {
        "session_id": str(session_id),
        "answer": answer,
        "citations": citations,
    }


async def textbook_qa_stream(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """
    继续教材问答，SSE 流式返回引导回答。
    """
    from sqlalchemy import select
    from oprim.retrieve_chunks import retrieve_chunks, format_chunks_as_context
    from services.models import SocraticSession

    row = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()

    if not row:
        yield f"data: {json.dumps({'error': 'session not found'}, ensure_ascii=False)}\n\n"
        return

    messages_data: dict = row.messages or {}
    file_id: str = messages_data.get("file_id", "")
    history: list[dict] = messages_data.get("history", [])

    # 检索 + 生成
    chunks = await retrieve_chunks(db, file_id=file_id, query=student_message, top_k=5)
    context = format_chunks_as_context(chunks)
    citations = [
        {
            "citation": c.citation,
            "page": c.page_number,
            "section": c.section_title,
            "score": round(c.score, 3),
        }
        for c in chunks
    ]

    # 获取学习者 L2 画像
    from oprim.learner_profile_summary import get_latest_learner_profile

    learner_profile = await get_latest_learner_profile(db, row.student_id)

    # 构建对话历史（只传 role/content，不传内部字段）
    llm_history = [{"role": m["role"], "content": m["content"]} for m in history]
    llm_history.append({"role": "user", "content": student_message})

    caller = _get_caller()
    system = _build_system_prompt(context, learner_profile)
    result = await caller(messages=llm_history, system=system, max_tokens=400)
    reply = result.get("content", "请稍后再试。")

    # 更新会话历史
    history.append({"role": "user", "content": student_message})
    history.append({"role": "assistant", "content": reply, "citations": citations})
    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(messages={**messages_data, "history": history})
    )
    await db.commit()

    payload = json.dumps({"reply": reply, "citations": citations}, ensure_ascii=False)
    yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"


# ── 建立索引（供 Celery 任务调用）──────────────────────────────────────────────


async def index_textbook_file(
    db: AsyncSession,
    *,
    file_id: str,
    file_data: bytes,
    file_type: str = "pdf",
) -> dict:
    """
    对上传的教材文件建立 RAG 索引：
    1. 解析 → 分块 → 嵌入
    2. 写入 textbook_chunks 表
    3. 更新 textbook_files.index_status = 'ready'
    """
    from oprim.embed_chunks import (
        process_pdf_for_rag,
        extract_pages_from_text,
        chunk_pages,
        embed_chunks,
    )

    # 标记「索引中」
    await db.execute(
        sa_text("UPDATE textbook_files SET index_status='indexing' WHERE id=:fid"),
        {"fid": file_id},
    )
    await db.commit()

    try:
        # 分块 + 嵌入
        if file_type == "pdf":
            chunks = await process_pdf_for_rag(file_data)
        else:
            text = file_data.decode("utf-8", errors="replace")
            pages = extract_pages_from_text(text)
            chunks = chunk_pages(pages)
            chunks = await embed_chunks(chunks)

        if not chunks:
            raise ValueError("No text could be extracted from file")

        # 删旧 chunks（幂等重建）
        await db.execute(
            sa_text("DELETE FROM textbook_chunks WHERE file_id=:fid"), {"fid": file_id}
        )

        # 批量插入
        now = datetime.now(timezone.utc)
        for chunk in chunks:
            cid = f"{file_id}_{chunk.chunk_index:05d}"
            await db.execute(
                sa_text("""
                INSERT INTO textbook_chunks
                  (id, file_id, page_number, section_title, chunk_index,
                   content, content_length, char_start, char_end,
                   embedding, embedding_model, embedded_at, created_at)
                VALUES
                  (:id, :file_id, :page, :section, :cidx,
                   :content, :clen, :char_start, :char_end,
                   :emb, :emb_model,
                   :emb_at, :now)
            """),
                {
                    "id": cid,
                    "file_id": file_id,
                    "page": chunk.page_number,
                    "section": chunk.section_title,
                    "cidx": chunk.chunk_index,
                    "content": chunk.content,
                    "clen": len(chunk.content),
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "emb": chunk.embedding,
                    "emb_model": chunk.embedding_model,
                    "emb_at": now if chunk.embedding else None,
                    "now": now,
                },
            )

        # 更新状态
        await db.execute(
            sa_text("""
            UPDATE textbook_files
            SET index_status='ready', chunk_count=:cnt, indexed_at=:now, index_error=NULL
            WHERE id=:fid
        """),
            {"cnt": len(chunks), "now": now, "fid": file_id},
        )
        await db.commit()

        embedded_count = sum(1 for c in chunks if c.embedding)
        logger.info(
            "indexed file_id=%s: %d chunks, %d embedded",
            file_id,
            len(chunks),
            embedded_count,
        )
        return {
            "file_id": file_id,
            "chunk_count": len(chunks),
            "embedded_count": embedded_count,
            "status": "ready",
        }

    except Exception as e:
        logger.exception("indexing failed for file_id=%s: %s", file_id, e)
        # DB 异常（如 INSERT 失败）会让事务进入 aborted 状态，此时任何后续命令
        # 都会被 asyncpg 拒绝（InFailedSQLTransactionError）——必须先 rollback
        # 才能执行下面这条"记录失败状态"的 UPDATE，否则该 UPDATE 本身也会抛异常，
        # 把真正的错误吞掉，index_status 永远卡在 'indexing'（W3 A2 批量入库时发现）。
        await db.rollback()
        await db.execute(
            sa_text("""
            UPDATE textbook_files SET index_status='error', index_error=:err WHERE id=:fid
        """),
            {"err": str(e)[:500], "fid": file_id},
        )
        await db.commit()
        return {"file_id": file_id, "status": "error", "error": str(e)}
