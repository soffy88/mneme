"""U.21 小规模试点：给一小批数学 KU 打课标主编码（curriculum_standard）。

范围声明（如实标注，非全量）：这是小规模试点脚本，验证"LLM 选码 → 校验 →
落库 → API 反查"链路能跑通，不是全量批量标注。数学以外学科暂无课标编码体系
（见 data/curriculum_std.py），本脚本只处理 subject=math。

跑法（参考 scripts/enrich_ku_content.py 的 env 约定）：
  set -a; . ./.env; set +a
  LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5vl:3b LLM_API_KEY=ollama \
    python scripts/tag_curriculum_standard_pilot.py --limit 20
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg2
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.curriculum_std import STD_NODES, is_valid_std_code  # noqa: E402

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

# 年级号（G1..G12）用 \b 边界匹配，避免子串误判（"G1" 是 "G10"/"G11"/"G12" 的前缀）。
_JY_GRADE_NUMS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_GZ_GRADE_NUMS = (10, 11, 12)
_JY_TEXT_MARKERS = (
    "小学",
    "初中",
    "一年级",
    "二年级",
    "三年级",
    "四年级",
    "五年级",
    "六年级",
    "七年级",
    "八年级",
    "九年级",
)
_GZ_TEXT_MARKERS = ("高一", "高二", "高三", "高中")


def _has_grade_marker(hay: str, grade_nums: tuple[int, ...]) -> bool:
    return any(re.search(rf"\bG{n}\b", hay, re.IGNORECASE) for n in grade_nums)


def _guess_seg(textbook_id: str, grade: str) -> str | None:
    hay = f"{textbook_id} {grade}"
    if _has_grade_marker(hay, _JY_GRADE_NUMS) or any(
        m in hay for m in _JY_TEXT_MARKERS
    ):
        return "JY"
    if _has_grade_marker(hay, _GZ_GRADE_NUMS) or any(
        m in hay for m in _GZ_TEXT_MARKERS
    ):
        return "GZ"
    return None


def _candidate_codes(seg: str) -> list[dict]:
    return [n for n in STD_NODES if n.get("seg") == seg]


def pick_code(ku_name: str, ku_description: str, seg: str) -> str | None:
    """调 LLM 从候选 topic 码里选一个最匹配的；不合法/选不出返回 None（不硬凑）。"""
    candidates = _candidate_codes(seg)
    if not candidates:
        return None
    listing = "\n".join(f"{c['code']}: {c['name']}({c['domain']})" for c in candidates)
    prompt = (
        f"知识点名称: {ku_name}\n知识点描述: {ku_description or '(无)'}\n\n"
        f"候选课标主题编码（只能从下面选一个，选不出就回复 NONE）：\n{listing}\n\n"
        "只返回编码本身或 NONE，不要多余文字。"
    )
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=32,
            temperature=0,
        )
        code = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"  ❌ LLM 调用失败: {exc}")
        return None
    return code if is_valid_std_code(code) else None


def fetch_pending(conn, limit: int, textbook_id: str | None = None):
    cur = conn.cursor()
    if textbook_id:
        cur.execute(
            """
            SELECT ku.id, ku.name, ku.description, ku.textbook_id, tb.grade
            FROM knowledge_units ku
            JOIN textbooks tb ON tb.id = ku.textbook_id
            WHERE tb.subject = 'math' AND ku.curriculum_standard IS NULL
              AND ku.textbook_id = %s
            ORDER BY ku.id
            LIMIT %s
            """,
            (textbook_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT ku.id, ku.name, ku.description, ku.textbook_id, tb.grade
            FROM knowledge_units ku
            JOIN textbooks tb ON tb.id = ku.textbook_id
            WHERE tb.subject = 'math' AND ku.curriculum_standard IS NULL
            ORDER BY ku.id
            LIMIT %s
            """,
            (limit,),
        )
    rows = cur.fetchall()
    cur.close()
    return rows


def save_code(conn, ku_id: str, code: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE knowledge_units SET curriculum_standard = %s WHERE id = %s",
        (code, ku_id),
    )
    conn.commit()
    cur.close()


def run(limit: int, dry_run: bool, textbook_id: str | None = None) -> None:
    dsn = os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql://postgres:postgres@db:5432/mneme",
    )
    conn = psycopg2.connect(dsn)
    rows = fetch_pending(conn, limit, textbook_id)
    print(f"待标注 {len(rows)} 个 KU（试点批次，limit={limit}）")

    tagged, skipped = 0, 0
    for ku_id, name, description, textbook_id, grade in rows:
        seg = _guess_seg(textbook_id, grade or "")
        if seg is None:
            print(f"  ⏭️  {ku_id}（{name}）：无法判定学段(JY/GZ)，跳过")
            skipped += 1
            continue
        code = pick_code(name, description or "", seg)
        if code is None:
            print(f"  ⏭️  {ku_id}（{name}）：LLM 未选出合法编码，跳过")
            skipped += 1
            continue
        if dry_run:
            print(f"  ✅（dry-run）{ku_id}（{name}）→ {code}")
        else:
            save_code(conn, ku_id, code)
            print(f"  ✅ {ku_id}（{name}）→ {code}")
        tagged += 1

    conn.close()
    print(f"完成：{tagged} 打标 / {skipped} 跳过（共 {len(rows)}）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--textbook-id", type=str, default=None)
    args = parser.parse_args()
    run(args.limit, args.dry_run, args.textbook_id)
