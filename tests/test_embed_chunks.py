"""oprim.embed_chunks —— 分块出处（char_span）+ 本地 Ollama embedding 真实产出验证。

W3 A1：Knowledge Hub 索引管道复用既有 embed_chunks/chunk_pages，本文件补两类测试：
1. chunk_pages 的 char_start/char_end 偏移必须能精确回指原页文本（出处红线）。
2. embed_text 在 Ollama qwen3-embedding 配置下真实产出向量（非 mock/非 None）。
"""

from __future__ import annotations

import os

import pytest

from oprim.embed_chunks import (
    TextChunk,
    _strip_control_chars,
    chunk_pages,
    embed_text,
    embed_text_with_model,
)


def _assert_span_matches(page_text: str, chunk: TextChunk) -> None:
    stripped = page_text.strip()
    assert chunk.char_start is not None
    assert chunk.char_end is not None
    assert 0 <= chunk.char_start < chunk.char_end <= len(stripped)
    span_text = stripped[chunk.char_start : chunk.char_end]
    # overlap 前缀场景下 content 以 span_text 结尾；无 overlap 时应完全相等
    assert chunk.content.endswith(span_text) or chunk.content == span_text


def test_chunk_pages_char_span_matches_short_page():
    text = "第一段：等差数列是一种特殊数列。\n\n第二段：通项公式为 a_n = a_1 + (n-1)d。"
    chunks = chunk_pages([{"page": 3, "text": text, "section": "数列"}])
    assert len(chunks) == 1
    assert chunks[0].page_number == 3
    _assert_span_matches(text, chunks[0])


def test_chunk_pages_char_span_matches_forced_split_and_overlap():
    text = (
        "第一段：等差数列是一种特殊数列。\n\n"
        + "第二段："
        + ("数" * 900)
        + "\n\n"
        + "第三段：这是最后一段落，用于测试overlap后缀是否正确。"
    )
    chunks = chunk_pages(
        [{"page": 7, "text": text, "section": "数列"}], chunk_size=800, overlap=100
    )
    assert len(chunks) > 1
    for c in chunks:
        assert c.page_number == 7
        _assert_span_matches(text, c)


def test_chunk_pages_char_span_exact_when_strip_boundary_falls_inside_split():
    """回归测试：W3 A5 全库验收发现 775/4907 个 chunk（约16%）的 char_span 比实际
    content 宽 1 个字符——强制切分长段落时，若切点边界恰好落在空白字符上，
    `.strip()` 会吃掉 content 里的这个字符，但 char_start/char_end 当时没跟着调整。
    这里构造一个长段落，在切点附近安排空格，确保命中这个边界情况。
    """
    long_para = "甲" * 799 + " " + "乙" * 799  # 空格恰好在第一刀 (0:800) 的末尾
    chunks = chunk_pages(
        [{"page": 9, "text": long_para, "section": None}], chunk_size=800, overlap=100
    )
    assert len(chunks) > 1
    for c in chunks:
        assert c.char_end - c.char_start == len(c.content), (
            f"chunk {c.chunk_index}: span width {c.char_end - c.char_start} != "
            f"content length {len(c.content)}"
        )
        _assert_span_matches(long_para, c)


def test_chunk_pages_char_span_distinct_per_page():
    pages = [
        {"page": 1, "text": "第一页内容。", "section": None},
        {"page": 2, "text": "第二页内容，和第一页不同。", "section": None},
    ]
    chunks = chunk_pages(pages)
    assert {c.page_number for c in chunks} == {1, 2}
    for c in chunks:
        page_text = next(p["text"] for p in pages if p["page"] == c.page_number)
        _assert_span_matches(page_text, c)


def test_strip_control_chars_removes_nul_but_keeps_newlines_and_chinese():
    """回归测试：A2 批量入库时，某些破损字体的缺字形位置吐出真实 \\x00 字节，
    Postgres text 列直接拒绝（CharacterNotInRepertoireError），整本索引失败。
    """
    raw = "边长\x00相等\n下一行\t制表符"
    cleaned = _strip_control_chars(raw)
    assert "\x00" not in cleaned
    assert cleaned == "边长相等\n下一行\t制表符"


@pytest.mark.asyncio
async def test_embed_text_produces_real_ollama_vector():
    """A-4 验收：Ollama embedding 真实产出向量（非空非 mock），非 OpenAI 路径。"""
    assert not os.environ.get("OPENAI_API_KEY"), (
        "此测试要验证 Ollama fallback 路径；OPENAI_API_KEY 若配置会短路到 OpenAI"
    )
    vec = await embed_text("等差数列的通项公式是什么？")
    assert vec is not None, "embed_text 返回 None——Ollama 不可达或模型未配置"
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(x, float) for x in vec)

    # 非 mock 佐证：不同文本产出不同向量，且向量非全零
    vec2 = await embed_text("完全不相关的另一句话，关于光合作用。")
    assert vec != vec2
    assert any(x != 0.0 for x in vec)


@pytest.mark.asyncio
async def test_embed_text_with_model_reports_actual_provider_not_static_constant():
    """回归测试：A2 dry run 发现 embed_chunks() 曾固定记录 EMBED_MODEL（OpenAI 常量），
    即便实际走 Ollama fallback 也照记不误——embedding_model 字段说谎。
    OPENAI_API_KEY 未配时，返回的模型名必须是 OLLAMA_EMBED_MODEL，不是 EMBED_MODEL。
    """
    assert not os.environ.get("OPENAI_API_KEY")
    vec, model = await embed_text_with_model("等差数列的通项公式是什么？")
    assert vec is not None
    assert model == os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    assert model != "text-embedding-3-small"
