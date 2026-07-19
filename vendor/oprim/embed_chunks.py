"""oprim.embed_chunks — PDF/文本分块 + 向量嵌入原子操作。

Red lines:
- 分块最大 800 字符，overlap 100 字符，保留 page/section 元数据
- Embedding 失败不抛异常，返回 embedding=None，允许降级纯文本检索
- 不依赖 pgvector；向量以 Python list[float] 返回，存入 ARRAY(FLOAT8)

Version: oprim v1.0.0
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────

CHUNK_SIZE = 800  # 字符数上限（约 400 中文字 / 600 英文词）
CHUNK_OVERLAP = 100  # 重叠字符数，保留上下文连贯性
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536  # text-embedding-3-small 输出维度
OLLAMA_EMBED_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
)


# ── 数据结构 ──────────────────────────────────────────────────────────────────


@dataclass
class TextChunk:
    """一个文本分块，携带定位元数据。

    char_start/char_end：相对该页提取文本（已 strip）的字符偏移区间
    [char_start, char_end)。段落缓冲区（buf）场景下取"贡献主内容的首尾段落"
    偏移——overlap 前缀本身也是原文字符，但不重新计入偏移起点，即偏移标注的
    是本块的核心内容范围，不是含 overlap 前缀的精确起点。
    """

    chunk_index: int
    content: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    embedding: Optional[list[float]] = field(default=None, repr=False)
    embedding_model: Optional[str] = None

    @property
    def chunk_id(self) -> str:
        """基于内容的确定性 ID（幂等）。"""
        h = hashlib.sha256(self.content.encode()).hexdigest()[:16]
        return f"chunk_{self.chunk_index:05d}_{h}"


# ── PDF 结构化解析 ────────────────────────────────────────────────────────────


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_control_chars(text: str) -> str:
    """去掉 C0 控制字符（保留 \\n\\t，切分逻辑要用）。

    部分数学教材 PDF 的破损/自定义字体在缺字形位置会吐出 \\x00 等控制字符
    （非乱码替换字符，是真的 NUL）——Postgres text 列直接拒绝含 \\x00 的字符串
    （UTF8 encoding 报 CharacterNotInRepertoireError），批量入库时曾整本失败。
    """
    return _CONTROL_CHARS_RE.sub("", text)


def extract_pages_from_pdf(data: bytes) -> list[dict]:
    """
    从 PDF 字节提取带页码的文本列表。
    优先用 pymupdf4llm（保留结构），fallback 到 pypdf（纯文本）。
    返回: [{"page": int, "text": str, "section": str|None}]
    """
    # 尝试 pymupdf4llm（结构化，保留标题/章节）
    try:
        import fitz  # PyMuPDF
        import io

        doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
        pages = []
        current_section: Optional[str] = None
        for i, page in enumerate(doc, 1):
            blocks = page.get_text("dict")["blocks"]
            texts = []
            for block in blocks:
                if block.get("type") != 0:  # 0=text
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = _strip_control_chars(span.get("text", "")).strip()
                        size = span.get("size", 0)
                        if not text:
                            continue
                        # 启发式：大字号为标题
                        if size >= 14 and len(text) < 80:
                            current_section = text
                        texts.append(text)
            pages.append(
                {
                    "page": i,
                    "text": "\n".join(texts),
                    "section": current_section,
                }
            )
        doc.close()
        return pages
    except ImportError:
        pass
    except Exception as e:
        logger.warning("pymupdf parse error: %s, falling back to pypdf", e)

    # Fallback: pypdf
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [
            {
                "page": i + 1,
                "text": _strip_control_chars(page.extract_text() or ""),
                "section": None,
            }
            for i, page in enumerate(reader.pages)
        ]
    except Exception as e:
        logger.warning("pypdf parse error: %s", e)
        return []


def extract_pages_from_text(text: str) -> list[dict]:
    """纯文本（非 PDF）转单页结构。"""
    return [{"page": None, "text": text, "section": None}]


# ── 分块 ──────────────────────────────────────────────────────────────────────

_PARA_SEP = re.compile(r"\n\s*\n")


def _split_paragraphs_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """按空行分段，同时返回每段在 text 中的 [start, end) 字符偏移。"""
    result: list[tuple[str, int, int]] = []
    pos = 0
    for m in _PARA_SEP.finditer(text):
        _append_para_offset(result, text, pos, m.start())
        pos = m.end()
    _append_para_offset(result, text, pos, len(text))
    return result


def _append_para_offset(
    result: list[tuple[str, int, int]], text: str, seg_start: int, seg_end: int
) -> None:
    segment = text[seg_start:seg_end]
    stripped, start, end = _stripped_span(segment, seg_start)
    if stripped:
        result.append((stripped, start, end))


def _stripped_span(raw: str, abs_start: int) -> tuple[str, int, int]:
    """raw 在原文中的绝对起点是 abs_start；返回 strip 后的内容 + 与之精确对齐
    （不含被 strip 掉的首尾空白）的 [start, end) 偏移。

    W3 A5 验收发现：之前直接把 strip 前的原始区间当 char_span 用，含首尾空白
    时 span 会比实际存的 content 宽 1 个字符——4907 个 chunk 里 775 个（约16%）
    命中，Postgres 里存的内容和标注的出处区间对不上。
    """
    lstrip_len = len(raw) - len(raw.lstrip())
    stripped = raw.strip()
    start = abs_start + lstrip_len
    return stripped, start, start + len(stripped)


def chunk_pages(
    pages: list[dict],
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """
    把 pages 列表切成 TextChunk 列表。
    策略：先按段落自然分界，超过 chunk_size 的段落再强制切分。
    每块附带 char_start/char_end（相对该页 strip 后文本的偏移，见 TextChunk 文档）。
    """
    chunks: list[TextChunk] = []
    idx = 0

    for page_info in pages:
        page_num = page_info.get("page")
        section = page_info.get("section")
        text = (page_info.get("text") or "").strip()
        if not text:
            continue

        paragraphs = _split_paragraphs_with_offsets(text)
        buf = ""
        buf_start: Optional[int] = None
        buf_end: Optional[int] = None

        for para, p_start, p_end in paragraphs:
            # 段落本身超过 chunk_size，强制切分
            if len(para) > chunk_size:
                # 先把已有 buf 落一块
                if buf.strip():
                    content, cs, ce = _stripped_span(buf, buf_start)
                    chunks.append(
                        TextChunk(
                            chunk_index=idx,
                            content=content,
                            page_number=page_num,
                            section_title=section,
                            char_start=cs,
                            char_end=ce,
                        )
                    )
                    idx += 1
                    buf = buf[-overlap:] if overlap else ""
                # 强制切 para（偏移精确，直接是 para 的子区间）
                start = 0
                while start < len(para):
                    end = min(start + chunk_size, len(para))
                    content, cs, ce = _stripped_span(para[start:end], p_start + start)
                    chunks.append(
                        TextChunk(
                            chunk_index=idx,
                            content=content,
                            page_number=page_num,
                            section_title=section,
                            char_start=cs,
                            char_end=ce,
                        )
                    )
                    idx += 1
                    start += chunk_size - overlap
                buf = para[-(overlap):] if overlap else ""
                buf_start = max(p_start, p_end - len(buf)) if buf else None
                buf_end = p_end if buf else None
                continue

            # 加段落到 buf
            if buf and len(buf) + len(para) + 2 > chunk_size:
                content, cs, ce = _stripped_span(buf, buf_start)
                chunks.append(
                    TextChunk(
                        chunk_index=idx,
                        content=content,
                        page_number=page_num,
                        section_title=section,
                        char_start=cs,
                        char_end=ce,
                    )
                )
                idx += 1
                if overlap:
                    old_tail = buf[-overlap:]
                    buf = old_tail + "\n\n" + para
                    buf_start = (
                        buf_end - len(old_tail) if buf_end is not None else p_start
                    )
                else:
                    buf = para
                    buf_start = p_start
                buf_end = p_end
            else:
                if buf:
                    buf = (buf + "\n\n" + para).strip()
                else:
                    buf = para
                    buf_start = p_start
                buf_end = p_end

        if buf.strip():
            content, cs, ce = _stripped_span(buf, buf_start)
            chunks.append(
                TextChunk(
                    chunk_index=idx,
                    content=content,
                    page_number=page_num,
                    section_title=section,
                    char_start=cs,
                    char_end=ce,
                )
            )
            idx += 1

    return chunks


# ── Embedding ─────────────────────────────────────────────────────────────────


async def embed_text(text: str) -> Optional[list[float]]:
    """
    用配置的 embedding 模型生成向量。
    优先 OpenAI API，fallback 到 Ollama 本地模型。
    失败返回 None（降级，不抛）。

    只需要向量的调用方（如 retrieve_chunks 给 query 生成向量）用这个；
    需要记录"向量实际来自哪个模型"的调用方（如批量入库）用 embed_text_with_model。
    """
    vec, _model = await embed_text_with_model(text)
    return vec


async def embed_text_with_model(
    text: str,
) -> tuple[Optional[list[float]], Optional[str]]:
    """
    同 embed_text，但同时返回实际产出该向量的模型名——用于出处/入库记录。
    之前的实现固定记 EMBED_MODEL（OpenAI 常量），即便实际走了 Ollama fallback
    也照记不误，导致 embedding_model 字段说谎（W3 A2 dry run 抽验发现）。
    """
    # OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            import openai as _openai

            client = _openai.AsyncOpenAI(api_key=openai_key)
            resp = await client.embeddings.create(
                model=EMBED_MODEL,
                input=text[:8192],  # token 上限保护
            )
            return resp.data[0].embedding, EMBED_MODEL
        except Exception as e:
            logger.warning("OpenAI embed error: %s", e)

    # Ollama fallback
    ollama_model = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_EMBED_URL}/api/embeddings",
                json={"model": ollama_model, "prompt": text[:4096]},
            )
            resp.raise_for_status()
            return resp.json().get("embedding"), ollama_model
    except Exception as e:
        logger.warning("Ollama embed error: %s", e)

    return None, None


async def embed_chunks(chunks: list[TextChunk]) -> list[TextChunk]:
    """
    批量给 chunks 生成 embedding。
    成功率不到 50% 时打 warning 但不抛异常（允许降级为纯文本检索）。
    """
    import asyncio

    ok = 0
    for chunk in chunks:
        vec, model_name = await embed_text_with_model(chunk.content)
        if vec:
            chunk.embedding = vec
            chunk.embedding_model = model_name
            ok += 1
        await asyncio.sleep(0.05)  # 简单限速，避免 API 限流

    if chunks and ok / len(chunks) < 0.5:
        logger.warning(
            "embed_chunks: low success rate %d/%d — RAG will fall back to text search",
            ok,
            len(chunks),
        )
    return chunks


# ── 便捷入口 ──────────────────────────────────────────────────────────────────


async def process_pdf_for_rag(data: bytes) -> list[TextChunk]:
    """
    PDF bytes → 分块 + 嵌入。主入口，供 Celery 任务调用。
    返回带 embedding 的 TextChunk 列表（embedding 可能为 None 若 API 不可用）。
    """
    pages = extract_pages_from_pdf(data)
    if not pages:
        logger.warning("process_pdf_for_rag: no text extracted from PDF")
        return []
    chunks = chunk_pages(pages)
    chunks = await embed_chunks(chunks)
    logger.info(
        "process_pdf_for_rag: %d chunks, %d embedded",
        len(chunks),
        sum(1 for c in chunks if c.embedding),
    )
    return chunks
