#!/usr/bin/env python3
"""
从课程标准 PDF 抽取 KU 骨架。
支持高中数学验证跑，后续可扩展到其他科目。

运行（验证）：
  docker run --rm --network mneme_default \
    -v ~/projects/mneme/curriculum_standards:/data \
    -v ~/projects/mneme:/app \
    -e DEEPSEEK_API_KEY=... \
    mneme-api:latest python scripts/extract_curriculum_ku.py \
    --pdf /data/高中_数学.pdf --subject math --stage hs --out /data/高中_数学_KU.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("缺少 pymupdf")

try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx")


# ── 配置 ─────────────────────────────────────────────────────────────────────

DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


def _deepseek_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        sys.exit("未设置 DEEPSEEK_API_KEY")
    return key


def llm_call(client: httpx.Client, system: str, user: str, max_tokens: int = 4000) -> str:
    resp = client.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── PDF 文本提取 ──────────────────────────────────────────────────────────────

def extract_pages(pdf_path: str, start: int = 0, end: int | None = None) -> str:
    doc = fitz.open(pdf_path)
    total = len(doc)
    end = min(end or total, total)
    pages = []
    for i in range(start, end):
        text = doc[i].get_text()
        if text.strip():
            pages.append(f"[P{i+1}]\n{text}")
    return "\n".join(pages)


def find_content_range(pdf_path: str) -> tuple[int, int]:
    """粗定位'课程内容'章节的起始和结束页（0-indexed）。"""
    doc = fitz.open(pdf_path)
    start = 0
    end = len(doc)
    for i, page in enumerate(doc):
        text = page.get_text()
        if "课程内容" in text and start == 0:
            start = max(0, i - 1)
        if start > 0 and i > start + 10:
            if "实施建议" in text or "学业质量" in text or "教学建议" in text:
                end = i
                break
    return start, end


# ── KU 抽取 ──────────────────────────────────────────────────────────────────

SYSTEM_EXTRACT = """你是中国K12课程标准分析专家。
你的任务是从课程标准文本中提取知识点（KU）层级结构，输出纯 JSON。

JSON 格式：
{
  "curriculum": "高中数学",
  "modules": [
    {
      "module_name": "必修课程",
      "themes": [
        {
          "theme_name": "主题一 预备知识",
          "units": [
            {
              "unit_name": "集合",
              "kus": [
                {"id": "hs-math-req-t1-u1-ku1", "name": "集合的概念与表示",
                 "content_req": "通过实例了解集合的含义，理解元素与集合的属于关系...",
                 "difficulty": 0.3, "grade": "G10"},
                ...
              ]
            },
            ...
          ]
        },
        ...
      ]
    },
    ...
  ]
}

规则：
- id 格式：{stage}-{subject}-{module_abbr}-{theme_abbr}-{unit_abbr}-ku{N}
  stage: hs=高中, ms=义务初中, es=义务小学
  subject: math=数学, phys=物理, eng=英语, chi=语文
  module_abbr: req=必修, sreq=选择性必修, opt=选修
- content_req 只摘要核心内容要求（50字以内），不要教学建议
- difficulty: 0.1(极易)-1.0(极难)，参考课标难度描述
- grade: 按课程安排，必修G10-G11，选择性必修G11-G12，选修G12
- 只提取明确列在"内容要求"下的知识点，不包含教学提示/学业要求中的描述
- 每个 unit 内 KU 数量 2-8 个，不要过细或过粗

只输出 JSON，不要任何其他内容。"""


def extract_ku_from_text(client: httpx.Client, text: str, subject: str, stage: str) -> dict:
    """将课标文本发给 LLM 抽取 KU 结构。"""
    user_prompt = f"以下是{subject}课程标准的课程内容部分，请提取 KU 骨架：\n\n{text}"

    raw = llm_call(client, SYSTEM_EXTRACT, user_prompt, max_tokens=6000)

    # 提取 JSON
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"⚠️ LLM 未返回 JSON，raw: {raw[:200]}", file=sys.stderr)
        return {}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析失败: {e}\nraw: {raw[:300]}", file=sys.stderr)
        return {}


def split_by_module(text: str) -> dict[str, str]:
    """把课标内容按模块分割（必修/选择性必修/选修）。"""
    modules = {}
    # 找主要分隔符
    patterns = [
        ("必修课程", r"（一）必修课程"),
        ("选择性必修", r"（二）选择性必修课程"),
        ("选修", r"（三）选修课程"),
    ]
    positions = []
    for name, pat in patterns:
        m = re.search(pat, text)
        if m:
            positions.append((m.start(), name))
    positions.sort()

    for i, (pos, name) in enumerate(positions):
        end_pos = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        modules[name] = text[pos:end_pos]

    if not modules:
        modules["全文"] = text

    return modules


# ── 统计报告 ─────────────────────────────────────────────────────────────────

def print_summary(ku_data: dict) -> None:
    print(f"\n📚 课程: {ku_data.get('curriculum', '未知')}")
    total_kus = 0
    for mod in ku_data.get("modules", []):
        themes = mod.get("themes", [])
        mod_kus = sum(len(u.get("kus", [])) for t in themes for u in t.get("units", []))
        total_kus += mod_kus
        print(f"\n  模块: {mod['module_name']} ({len(themes)} 主题, {mod_kus} KU)")
        for theme in themes:
            units = theme.get("units", [])
            theme_kus = sum(len(u.get("kus", [])) for u in units)
            print(f"    {theme['theme_name']}: {len(units)} 单元, {theme_kus} KU")
            for unit in units:
                kus = unit.get("kus", [])
                print(f"      [{unit['unit_name']}]: {len(kus)} KU")
                for ku in kus[:3]:
                    print(f"        · {ku['name']} (difficulty={ku.get('difficulty')}, grade={ku.get('grade')})")
                if len(kus) > 3:
                    print(f"        … 共 {len(kus)} 个")
    print(f"\n  总计: {total_kus} 个知识点")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--subject", default="math", help="math/phys/eng/chi")
    parser.add_argument("--stage", default="hs", help="hs/ms/es")
    parser.add_argument("--out", default=None)
    parser.add_argument("--pages", default=None, help="手动指定页范围，如 20-75")
    args = parser.parse_args()

    pdf_path = args.pdf
    if not Path(pdf_path).exists():
        sys.exit(f"找不到文件: {pdf_path}")

    client = httpx.Client(headers={"Authorization": f"Bearer {_deepseek_key()}"})

    # 1. 定位课程内容章节
    if args.pages:
        parts = args.pages.split("-")
        pg_start, pg_end = int(parts[0]) - 1, int(parts[1])
    else:
        print("📖 定位课程内容章节...", file=sys.stderr)
        pg_start, pg_end = find_content_range(pdf_path)
    print(f"  页面范围: P{pg_start+1} ~ P{pg_end}", file=sys.stderr)

    # 2. 提取文本
    print("📝 提取 PDF 文本...", file=sys.stderr)
    raw_text = extract_pages(pdf_path, pg_start, pg_end)

    # 高中数学文本约 30k 字符，DeepSeek 支持 64k context，整体发
    # 但为安全起见按模块拆分
    modules = split_by_module(raw_text)
    print(f"  分割成 {len(modules)} 个模块: {list(modules.keys())}", file=sys.stderr)

    # 3. 逐模块 LLM 抽取
    subject_cn = {"math": "数学", "phys": "物理", "eng": "英语", "chi": "语文"}.get(args.subject, args.subject)
    stage_cn = {"hs": "高中", "ms": "初中(义务)", "es": "小学(义务)"}.get(args.stage, args.stage)

    all_modules = []
    for mod_name, mod_text in modules.items():
        print(f"\n🤖 LLM 抽取: [{mod_name}] ({len(mod_text)} chars)...", file=sys.stderr)
        # 限制单次发送长度（避免超 token）
        text_chunk = mod_text[:12000]
        result = extract_ku_from_text(client, text_chunk, f"{stage_cn}{subject_cn}", args.stage)
        if result.get("modules"):
            all_modules.extend(result["modules"])
        elif result:
            all_modules.append(result)

    ku_data = {
        "curriculum": f"{stage_cn}{subject_cn}课程标准（2022年版）" if args.stage != "hs" else f"普通{stage_cn}{subject_cn}课程标准（2017年版2020年修订）",
        "subject": args.subject,
        "stage": args.stage,
        "source_pdf": Path(pdf_path).name,
        "modules": all_modules,
    }

    # 4. 打印摘要
    print_summary(ku_data)

    # 5. 输出 JSON
    out_path = args.out or str(Path(pdf_path).with_suffix("_KU.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ku_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 输出: {out_path}", file=sys.stderr)

    client.close()


if __name__ == "__main__":
    main()
