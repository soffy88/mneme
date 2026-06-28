#!/usr/bin/env python3
"""
人教A版数学必修第二册 KU 提取入库脚本。
使用本地 Ollama（qwen2.5:7b）做 KU 提取。
用法:
  docker run --network host ... python /app/scripts/import_bx2_pdf.py /books/xxx.pdf
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys

try:
    import fitz          # PyMuPDF
    import asyncpg
    import httpx
except ImportError as e:
    sys.exit(f"缺少依赖: {e}")

PDF_PATH    = sys.argv[1] if len(sys.argv) > 1 else "/books/人教A版数学必修第二册【高清教材】(1).pdf"
TB_ID       = "RENJIAO-G10-MATH-BX2"
TB_GRADE    = "g10"
TB_BOOK     = "人教A版数学必修第二册"
DB_URL      = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mneme").replace("postgresql+asyncpg://", "postgresql://")
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# 必修二五章（按实际目录顺序，第六章开始是因为必修一是第一～五章）
CHAPTERS_5 = ["第六章", "第七章", "第八章", "第九章", "第十章"]

LLM_SYSTEM = """你是人教A版高中数学教材KU（知识单元）提取专家。

从给定的教材正文中提取所有 KU（知识单元）。
KU = 最小可独立出题/掌握/遗忘的知识点（如"平面向量的加法法则"，不是"向量"整章）。

规则：
- 每个KU是正文中真实存在的独立知识点，不编造
- 粒度：能单独出题的最小单元（定义/定理/公式/方法各自独立）
- 前置依赖：填本册或必修一中其他KU名（可空列表）
- 难度：1=记忆理解，2=应用计算，3=综合证明
- 跳过习题、答案、目录页内容

必须输出合法JSON，不加markdown代码块，格式：
{"chapter":"章节名","kus":[{"name":"KU名≤20字","description":"说明≤60字","prerequisites":[],"difficulty":1}]}"""


def clean_math_text(text: str) -> str:
    """去除PDF数学字体乱码（不在常用Unicode范围内的字符）。"""
    result = []
    for ch in text:
        cp = ord(ch)
        # 保留：ASCII + CJK + 常用标点 + 数字 + 换行
        if (cp < 0x80 or                          # ASCII
                0x4E00 <= cp <= 0x9FFF or         # CJK基本区
                0x3000 <= cp <= 0x303F or         # CJK符号标点
                0xFF00 <= cp <= 0xFFEF or         # 全角
                0x2000 <= cp <= 0x206F or         # 通用标点
                0x2200 <= cp <= 0x22FF or         # 数学运算符 ∈∑∏...
                ch in '（）【】《》""''·…—'):
            result.append(ch)
        elif ch in '\n\t ':
            result.append(ch)
        else:
            result.append(' ')  # 替换为空格
    # 压缩多余空格
    return re.sub(r'  +', ' ', ''.join(result))


def extract_chapters(pdf_path: str) -> list[dict]:
    """从PDF提取正文，按章分组（跳过TOC短段）。"""
    doc = fitz.open(pdf_path)
    pages_text = []
    for i, page in enumerate(doc):
        t = page.get_text().strip()
        pages_text.append((i + 1, t))
    doc.close()

    # 合并全文（跳过前10页目录/封面），清洗数学乱码
    body_pages = [(p, t) for p, t in pages_text if p > 10 and len(t) > 80]
    full = clean_math_text("\n".join(t for _, t in body_pages))

    # 找章节切割点（匹配 "第X章\n" 或 "第X章 " 开头，后跟中文标题）
    chapter_pat = re.compile(r'(第[六七八九十]+章\s*[^\n\d⋯…]{2,20})\n')
    hits = [(m.start(), m.group(1).strip()) for m in chapter_pat.finditer(full)]

    # 去重：同一章名只保留第一次出现（正文）
    seen: dict[str, int] = {}
    deduped_hits = []
    for pos, title in hits:
        key = re.sub(r'\s+', '', title)[:6]  # 前6字为键
        # 过滤正文中散落的章节引用（如"第六章，我们..."）
        clean = re.sub(r'\s+', '', title)
        if not re.search(r'^第[六七八九十]+章[一-鿿]', clean):
            continue
        if key not in seen:
            seen[key] = pos
            deduped_hits.append((pos, title))

    if not deduped_hits:
        return [{"chapter": "全书正文", "text": full[:18000]}]

    # 合并同章的多段文本（同 key 只保留首次，但末尾延伸到下一个不同章）
    chunks = []
    for i, (start, title) in enumerate(deduped_hits):
        end = deduped_hits[i + 1][0] if i + 1 < len(deduped_hits) else len(full)
        chunk_text = full[start:end]
        if len(chunk_text) < 500:
            continue
        # 拆大章为多个 5000 字符子块
        sub_size = 5000
        if len(chunk_text) <= sub_size:
            chunks.append({"chapter": title.replace('\n', ' '), "text": chunk_text})
        else:
            for j in range(0, len(chunk_text), sub_size):
                sub = chunk_text[j:j + sub_size]
                if len(sub) > 300:
                    chunks.append({"chapter": title.replace('\n', ' '), "text": sub})

    print(f"  切分 {len(chunks)} 块: {list(dict.fromkeys(c['chapter'] for c in chunks))}")
    return chunks


def llm_extract(client: httpx.Client, chapter: str, text: str) -> list[dict]:
    """调 Ollama 提取一段教材正文的 KU 列表。强制 JSON 格式输出。"""
    user = f"章节：{chapter}\n\n教材正文：\n{text}"
    try:
        resp = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",   # 强制 JSON 输出（Ollama 支持）
                "options": {"temperature": 0.05, "num_predict": 4000},
            },
            timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        # format:json 下应已是合法 JSON，直接解析
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 兜底：正则提取第一个 {...}
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}
        kus = data.get("kus", [])
        print(f"    → {len(kus)} KU")
        return kus
    except Exception as e:
        print(f"    [ERROR] {chapter[:20]}: {e}")
    return []


async def run(pdf_path: str) -> None:

    conn = await asyncpg.connect(DB_URL)

    # 1. 确保 textbook stub 存在（更新书名为准确描述）
    await conn.execute("""
        INSERT INTO textbooks (id, subject, grade, edition, book_name)
        VALUES ($1, 'math', $2, '人教A版', $3)
        ON CONFLICT (id) DO UPDATE SET book_name=EXCLUDED.book_name, edition=EXCLUDED.edition
    """, TB_ID, TB_GRADE, TB_BOOK)
    print(f"✅ textbook upsert: {TB_ID}")

    # 2. 清理旧 KU（若有）
    old_ku = await conn.fetchval("SELECT COUNT(*) FROM knowledge_units WHERE textbook_id=$1", TB_ID)
    if old_ku:
        await conn.execute("DELETE FROM knowledge_units WHERE textbook_id=$1", TB_ID)
        await conn.execute("DELETE FROM knowledge_clusters WHERE textbook_id=$1", TB_ID)
        print(f"  清理旧数据: {old_ku} 条KU")

    # 3. 提取文本
    print(f"📖 读取PDF: {pdf_path}")
    chapters = extract_chapters(pdf_path)

    # 4. LLM 提取（Ollama）
    client = httpx.Client(timeout=300)
    all_kus: list[dict] = []

    for ch in chapters:
        chname = ch["chapter"]
        print(f"  ⟳ {chname[:20]}... ({len(ch['text'])}字符)")
        kus = llm_extract(client, chname, ch["text"])
        for ku in kus:
            ku["_chapter"] = chname
        all_kus.extend(kus)

    client.close()

    # 5. 去重（按名称）
    seen: set[str] = set()
    deduped: list[dict] = []
    for ku in all_kus:
        nm = ku.get("name", "").strip()
        if nm and nm not in seen:
            seen.add(nm)
            deduped.append(ku)
    print(f"\n原始 {len(all_kus)} KU → 去重后 {len(deduped)} KU")

    if not deduped:
        print("❌ 未提取到任何KU，中止")
        await conn.close()
        return

    # 6. 按章建立 knowledge_cluster，插入 knowledge_units
    chapter_to_kc: dict[str, str] = {}
    ku_order = 0

    for ku in deduped:
        chname = ku.get("_chapter", "其他")

        # 建 KC（每章一个）
        if chname not in chapter_to_kc:
            kc_id = f"{TB_ID}-kc-{len(chapter_to_kc)+1:02d}"
            await conn.execute("""
                INSERT INTO knowledge_clusters (id, textbook_id, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
            """, kc_id, TB_ID, chname[:80])
            chapter_to_kc[chname] = kc_id

        kc_id = chapter_to_kc[chname]
        ku_name = ku.get("name", "").strip()[:80]
        ku_id   = f"{TB_ID}-ku-{ku_name}"[:120]

        # 难度映射：LLM 可能返回 1/2/3 或 "简单"/"中等"/"困难"
        diff_raw = ku.get("difficulty") or 1
        _diff_str_map = {"简单": 0.3, "低": 0.3, "中": 0.6, "中等": 0.6, "困难": 0.9, "高": 0.9}
        if isinstance(diff_raw, str) and not diff_raw.isdigit():
            diff_float = _diff_str_map.get(diff_raw.strip(), 0.3)
        else:
            diff_float = {1: 0.3, 2: 0.6, 3: 0.9}.get(int(str(diff_raw).strip() or "1"), 0.3)

        # 插入 KU
        await conn.execute("""
            INSERT INTO knowledge_units
              (id, textbook_id, cluster_id, name, description, prerequisites, difficulty)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            ON CONFLICT (id) DO UPDATE
              SET name=EXCLUDED.name, description=EXCLUDED.description,
                  prerequisites=EXCLUDED.prerequisites, difficulty=EXCLUDED.difficulty
        """,
            ku_id, TB_ID, kc_id,
            ku_name,
            (ku.get("description") or "")[:200],
            json.dumps(ku.get("prerequisites") or [], ensure_ascii=False),
            diff_float,
        )

    await conn.close()

    # 7. 汇总
    kc_count = len(chapter_to_kc)
    print(f"""
========================================
  必修第二册 KU 入库完成
========================================
  textbook_id : {TB_ID}
  KU 入库     : {len(deduped)} 个
  章节(KC)    : {kc_count} 个
  章节分布:""")
    for chname, kc_id in chapter_to_kc.items():
        n = sum(1 for k in deduped if k.get("_chapter") == chname)
        print(f"    {chname[:30]}: {n} KU")


if __name__ == "__main__":
    asyncio.run(run(PDF_PATH))
