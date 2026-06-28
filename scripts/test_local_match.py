#!/usr/bin/env python3
"""
本地模型(Ollama qwen2.5:7b) vs DeepSeek 题目→KU 匹配质量对比测试。

用法:
  docker run --network host ... python /app/scripts/test_local_match.py [--limit N] [--model qwen2.5:7b]

输出:
  - 匹配率对比
  - 与DeepSeek结果一致率
  - 每题耗时 + 全量预估
  - 低置信度/异常样本抽查
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

try:
    import asyncpg
    import httpx
except ImportError as e:
    sys.exit(f"缺少依赖: {e}")

import asyncio

DB_URL     = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/mneme")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL      = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
TOTAL_CMM  = 22248  # 全量CMM-Math题目数

# 年级 → 候选教材（与 match_questions_to_ku.py 保持一致）
_HS_TB = [
    "renjiao-math-g10-a",
    "RENJIAO-G10-MATH-BX2",
    "RENJIAO-G11-MATH-A-SBX1",
    "RENJIAO-G11-MATH-A-SBX2",
    "RENJIAO-G12-MATH-A-SBX3",
]
GRADE_TB_MAP: dict[str, list[str]] = {
    "g1":  ["RENJIAO-G1-MATH-S",  "RENJIAO-G1-MATH-X"],
    "g2":  ["RENJIAO-G2-MATH-S",  "RENJIAO-G2-MATH-X"],
    "g3":  ["RENJIAO-G3-MATH-S",  "RENJIAO-G3-MATH-X"],
    "g4":  ["RENJIAO-G4-MATH-S",  "RENJIAO-G4-MATH-X"],
    "g5":  ["RENJIAO-G5-MATH-S",  "RENJIAO-G5-MATH-X"],
    "g6":  ["RENJIAO-G6-MATH-S",  "RENJIAO-G6-MATH-X"],
    "g7":  ["RENJIAO-G7-MATH-S",  "RENJIAO-G7-MATH-X"],
    "g8":  ["RENJIAO-G8-MATH-S",  "RENJIAO-G8-MATH-X"],
    "g9":  ["RENJIAO-G9-MATH-S",  "RENJIAO-G9-MATH-X"],
    "g10": _HS_TB,
    "g11": _HS_TB,
    "g12": _HS_TB,
}

LLM_SYSTEM = """你是人教版数学教材知识点（KU）匹配专家。
给定一道数学题目和候选KU列表，找出该题考察的1-3个最相关KU。

规则：
- 精确匹配：题目考什么就选什么，不强行匹配
- 候选中无合适KU → 返回空数组
- 只输出JSON，不加任何其他文字

格式：{"matched":[{"id":"KU-ID","name":"KU名","role":"main|related"}],"confidence":0.9,"reason":"理由"}"""


def extract_grade_from_kp(kp: dict) -> str | None:
    """从knowledge_points的key推断年级。"""
    for k in kp.keys():
        # RENJIAO-G7-... → g7
        m = re.match(r'(?:RENJIAO|renjiao)[^-]*-G?(\d+)-', k, re.I)
        if m:
            n = int(m.group(1))
            return f"g{n}" if n <= 12 else None
        # cmm-math-g7-... → g7
        m2 = re.match(r'cmm-math-(g\d+)-', k)
        if m2:
            return m2.group(1)
    return None


def keyword_filter(question: str, kus: list[dict], top_n: int = 40) -> list[dict]:
    """
    用关键词重叠预筛候选KU，把大候选集压到 top_n 个。
    原理：题目和KU名/描述的分词重叠度越高，越可能相关。
    """
    # 提取题目中长度≥2的中文词（简单切词：每2字符一组滑动窗口）
    def tokenize(text: str) -> set[str]:
        clean = re.sub(r'[^一-鿿\w]', ' ', text)
        tokens: set[str] = set()
        words = clean.split()
        for w in words:
            if len(w) >= 2:
                tokens.add(w)
            for i in range(len(w) - 1):
                tokens.add(w[i:i+2])  # bigram
        return tokens

    q_tokens = tokenize(question[:400])

    def score(ku: dict) -> int:
        ku_text = f"{ku['name']} {ku.get('description','')}"
        ku_tokens = tokenize(ku_text)
        return len(q_tokens & ku_tokens)

    scored = sorted(kus, key=score, reverse=True)
    # 保证至少有内容（取top_n，但最少10个保证多样性）
    return scored[:top_n]


def build_candidates_text(kus: list[dict]) -> str:
    """格式化候选KU列表。"""
    lines = [f'- id:"{k["id"]}" | {k["name"]} | {(k.get("description") or "")[:50]}' for k in kus]
    return "\n".join(lines)


def ollama_match(client: httpx.Client, question_text: str, grade: str, ku_text: str) -> dict:
    """调Ollama匹配一道题。qwen3.5系列不支持format:json，用/no_think替代。"""
    grade_cn = {
        "g1":"一年级","g2":"二年级","g3":"三年级","g4":"四年级","g5":"五年级","g6":"六年级",
        "g7":"七年级","g8":"八年级","g9":"九年级","g10":"高一","g11":"高二","g12":"高三"
    }.get(grade, grade)

    # qwen3.5 thinking模型：format:json 和 /no_think 均无效（全塞<think>里）
    # 正确做法：顶层 "think": false 参数（Ollama API 支持）
    is_thinking_model = "qwen3" in MODEL.lower() or "3.5" in MODEL

    user = f"题目（{grade_cn}数学）：\n{question_text[:600]}\n\n候选KU列表：\n{ku_text}"
    t0 = time.time()
    try:
        payload: dict = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.05, "num_predict": 800},
        }
        if is_thinking_model:
            payload["think"] = False   # 关闭思考链，直接输出答案
        else:
            payload["format"] = "json"  # 非thinking模型用JSON mode

        resp = client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}
    except Exception as e:
        data = {"error": str(e)[:80]}
    elapsed = time.time() - t0
    data["_elapsed"] = elapsed
    return data


def compare_matches(deepseek_kp: dict, ollama_matched: list[dict]) -> str:
    """比较DeepSeek和Ollama的匹配结果。"""
    ds_ids = set(deepseek_kp.keys())
    ol_ids = set(m["id"] for m in ollama_matched if "id" in m)
    if not ds_ids and not ol_ids:
        return "both_empty"
    if not ol_ids:
        return "ollama_miss"
    if not ds_ids:
        return "deepseek_miss"
    if ds_ids & ol_ids:
        return "agree"          # 至少一个KU相同
    # 不同KU，检查是否同章
    ds_chapter = set(k.split('-ku-')[0] if '-ku-' in k else k[:30] for k in ds_ids)
    ol_chapter = set(k.split('-ku-')[0] if '-ku-' in k else k[:30] for k in ol_ids)
    if ds_chapter & ol_chapter:
        return "same_chapter"   # 同章不同KU（可接受）
    return "disagree"           # 完全不同


async def run(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(DB_URL)

    # 1. 拉题目（只拉已有KU的）
    rows = await conn.fetch("""
        SELECT id, question_text, knowledge_points
        FROM wrong_questions
        WHERE knowledge_points IS NOT NULL
          AND knowledge_points != '{}'::jsonb
        ORDER BY id
        LIMIT $1
    """, args.limit or 9999)

    print(f"题目总数: {len(rows)}")

    # 2. 加载KU候选
    ku_cache: dict[str, list[dict]] = {}
    for grade, tb_ids in GRADE_TB_MAP.items():
        kus = await conn.fetch(
            "SELECT id, name, description FROM knowledge_units WHERE textbook_id = ANY($1::text[])",
            tb_ids
        )
        ku_cache[grade] = [dict(r) for r in kus]
    total_kus = sum(len(v) for v in ku_cache.values())
    hs_kus = len(ku_cache.get("g10", []))
    print(f"KU缓存: 共{total_kus}条 (高中候选池:{hs_kus}条)")

    await conn.close()

    # 3. 逐题测试
    client = httpx.Client(timeout=180)
    results = []
    timings = []
    grade_stats: dict[str, dict] = defaultdict(lambda: {"total":0,"matched":0,"agree":0,"same_ch":0})

    for i, row in enumerate(rows):
        wq_id = str(row["id"])
        kp_raw = row["knowledge_points"]
        kp = kp_raw if isinstance(kp_raw, dict) else json.loads(kp_raw)
        qtxt = (row["question_text"] or "").strip()

        grade = extract_grade_from_kp(kp)
        if not grade:
            grade = "g10"   # 未知年级按高中处理

        kus = ku_cache.get(grade, [])
        if not kus:
            print(f"  [{i+1:03d}] ⚠ {grade} 无KU候选")
            continue

        # 关键词预筛：从全量候选压到≤40个
        filtered_kus = keyword_filter(qtxt, kus, top_n=40)
        ku_text = build_candidates_text(filtered_kus)

        result = ollama_match(client, qtxt, grade, ku_text)
        elapsed = result.pop("_elapsed", 0)
        timings.append(elapsed)

        matched = result.get("matched", [])
        conf = result.get("confidence", 0)
        reason = result.get("reason", "")
        error = result.get("error", "")

        comparison = compare_matches(kp, matched)
        g = grade_stats[grade]
        g["total"] += 1
        if matched:
            g["matched"] += 1
        if comparison == "agree":
            g["agree"] += 1
        elif comparison == "same_chapter":
            g["same_ch"] += 1

        # 获取DeepSeek原始匹配
        ds_kus = list(kp.keys())[:2]

        status = {
            "agree": "✅", "same_chapter": "🔶",
            "ollama_miss": "❌", "disagree": "❌", "both_empty": "⚪"
        }.get(comparison, "?")

        print(f"  [{i+1:03d}] {status} {grade} {elapsed:.1f}s | conf={conf:.1f}")
        if args.verbose:
            print(f"       DS: {ds_kus}")
            if matched:
                print(f"       OL: {[m.get('id','')[:50] for m in matched[:2]]}")
            if error:
                print(f"       ERR: {error}")
            if reason:
                print(f"       理由: {reason[:70]}")

        results.append({
            "wq_id": wq_id, "grade": grade,
            "deepseek_kus": ds_kus,
            "ollama_matched": [m.get("id","") for m in matched],
            "confidence": conf,
            "comparison": comparison,
            "elapsed": elapsed,
            "reason": reason,
        })

    client.close()

    # 4. 汇总报告
    total = len(results)
    n_matched    = sum(1 for r in results if r["ollama_matched"])
    n_agree      = sum(1 for r in results if r["comparison"] == "agree")
    n_same_ch    = sum(1 for r in results if r["comparison"] == "same_chapter")
    n_miss       = sum(1 for r in results if r["comparison"] == "ollama_miss")
    n_disagree   = sum(1 for r in results if r["comparison"] == "disagree")
    avg_t        = sum(timings) / len(timings) if timings else 0
    p50          = sorted(timings)[len(timings)//2] if timings else 0
    p95          = sorted(timings)[int(len(timings)*0.95)] if timings else 0

    # 全量预估
    est_h_single  = avg_t * TOTAL_CMM / 3600
    # 可并发（每次请求串行但Ollama单实例），假设4并发
    est_h_4w      = est_h_single / 4

    print(f"""
{'='*55}
  本地模型匹配质量报告（{MODEL}）
{'='*55}
  测试题数 : {total}
  Ollama匹配成功: {n_matched}/{total}  ({100*n_matched/max(total,1):.0f}%)
  DeepSeek基准  : ~90%

  与DeepSeek比较:
    ✅ 完全一致(同KU)   : {n_agree}/{total}  ({100*n_agree/max(total,1):.0f}%)
    🔶 同章不同KU       : {n_same_ch}/{total}  ({100*n_same_ch/max(total,1):.0f}%)
    ❌ 本地未匹配       : {n_miss}/{total}
    ❌ 完全不同章       : {n_disagree}/{total}
    有效命中(一致+同章) : {n_agree+n_same_ch}/{total}  ({100*(n_agree+n_same_ch)/max(total,1):.0f}%)

  速度:
    avg: {avg_t:.1f}s/题  p50: {p50:.1f}s  p95: {p95:.1f}s
    全量{TOTAL_CMM}条预估:
      串行   ~{est_h_single:.0f}h  ({est_h_single*60:.0f}min)
      4并发  ~{est_h_4w:.1f}h    ({est_h_4w*60:.0f}min)

  年级细分:""")

    for grade, gs in sorted(grade_stats.items()):
        if gs["total"] == 0:
            continue
        rate = 100*gs["matched"]/gs["total"]
        agree_r = 100*(gs["agree"]+gs["same_ch"])/gs["total"]
        print(f"    {grade}: 匹配{rate:.0f}% 有效命中{agree_r:.0f}% ({gs['total']}题)")

    # 5. 低质量样本（disagree）
    bad = [r for r in results if r["comparison"] in ("disagree", "ollama_miss") and r["ollama_matched"]][:5]
    if bad:
        print(f"\n  ⚠ 分歧样本（前{len(bad)}条）:")
        for r in bad:
            print(f"    [{r['grade']}] DS: {r['deepseek_kus'][:1]}")
            print(f"              OL: {r['ollama_matched'][:1]}")

    # 6. 结论
    effective = 100*(n_agree+n_same_ch)/max(total,1)
    if effective >= 80:
        verdict = "✅ 可用于全量（质量达标）"
    elif effective >= 65:
        verdict = "🔶 可用于批量初匹配 + 人工复核关键题"
    else:
        verdict = "❌ 质量不足，建议换更大模型或仍用云端"
    print(f"\n  结论: {verdict}")

    if avg_t > 3:
        print(f"  ⚠ 速度: {avg_t:.1f}s/题，全量需{est_h_single:.0f}h串行")
        print(f"     建议: {'本地4并发约' + str(round(est_h_4w,1)) + 'h，或混合方案（初中本地+高中云端）'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="测试题数（默认全部）")
    parser.add_argument("--model", type=str, default=None, help="Ollama模型名")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    if args.model:
        global MODEL
        MODEL = args.model
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
