"""教材上传 → 知识抽取（item 7）：把内核可信抽取流水线接到运行时。

红线（item 2/7）：抽取候选必须过校验门、带溯源、源/AI 分离，**不得裸 INSERT**。
本服务把内核 ku_extract_pipeline（structural_chunk→llm_extract_ku→ku_gate_validate）
的候选映射成课程 KU，再经 store_curriculum_ku 二次校验门落库。

注意：PDF→文本 与 LLM provider 属运行时基础设施；本模块负责"候选→落库"的可测映射，
文本抽取由调用方（Celery 任务）提供 text。
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from services.ku_ingest_service import store_curriculum_kus


def _candidate_to_curriculum_ku(cand: dict, textbook_id: str, cluster_id: str) -> dict:
    """内核 KU 候选（natural_text/provenance/...）→ 课程 KU dict。"""
    natural = (cand.get("natural_text") or "").strip()
    name = natural[:30] if natural else (cand.get("tags") or ["未命名知识点"])[0]
    return {
        "id": cand.get("ku_id") or f"AUTO-{abs(hash(natural)) % 10**10}",
        "textbook_id": textbook_id,
        "cluster_id": cluster_id,
        "name": name,
        "description": natural,
        "prerequisites": [],
        "difficulty": 0.5,
        "provenance": cand.get("provenance") or {},
        "_source_excerpt": natural,   # 源内容（与 AI 描述同源，但显式留档）
    }


async def ingest_pipeline_candidates(
    db: AsyncSession,
    *,
    textbook_id: str,
    cluster_id: str,
    pipeline_result: dict,
    extract_model: str = "ku_extract_pipeline",
    known_ku_ids: Optional[set[str]] = None,
) -> dict:
    """把 ku_extract_pipeline 的 candidates 经课程校验门落库。

    pipeline_result：{candidates: [...], rejected: [...], chunks_processed: int}
    返回 {stored, rejected, rejected_details, kernel_rejected}。
    """
    candidates = pipeline_result.get("candidates", [])
    kus = [_candidate_to_curriculum_ku(c, textbook_id, cluster_id) for c in candidates]
    src_map = {k["id"]: k.pop("_source_excerpt", "") for k in kus}
    out = await store_curriculum_kus(
        db, kus,
        source_excerpt_map=src_map,
        known_ku_ids=known_ku_ids,
        extract_model=extract_model,
    )
    # 内核门已拒的也透出，便于观测整体可信度
    out["kernel_rejected"] = len(pipeline_result.get("rejected", []))
    return out


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """尽力从 PDF 字节提取文本（优先 pymupdf4llm，降级 pypdf）。无解析器则返回空串（不抛）。"""
    try:
        import pymupdf4llm
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        return pymupdf4llm.to_markdown(doc)
    except ImportError:
        try:
            import io
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            return ""
    except Exception:
        return ""


# 段落切分兜底（当内核 structural_chunk 不可用或纯文本时）
_PARA = re.compile(r"\n\s*\n")
