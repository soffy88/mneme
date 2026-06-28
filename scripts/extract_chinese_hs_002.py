#!/usr/bin/env python3
"""
AII知识本体002框架 · 高中语文KU试抽脚本（必修上验证用）。

三个核心改进落地验证：
  1. knowledge_kind: declarative / procedural / explanatory (know-what/how/why)
  2. surrogate原则: 鉴赏/表达ku的name是知识替身，课文进example
  3. 同方法跨课文合并：后处理按name去重+合并examples

输出：scripts/chinese_002_audit.md（供人工审核）
默认dry-run，不入库。

用法：
  DEEPSEEK_API_KEY=... .venv/bin/python scripts/extract_chinese_hs_002.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("缺少 pymupdf: pip install pymupdf")
try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
DS_KEY         = os.environ.get("DEEPSEEK_API_KEY", "")
CHUNK          = 3_000
FAILED_CHUNKS: list[str] = []  # 失败的chunk，末尾报告
PDF     = PDF_DIR / "H_语文_普通高中教科书·语文必修上册.pdf"
TB_ID   = "TONGBIAN-G10-CHINESE-BXS"
SKIP    = {"第五单元", "第八单元"}  # 乡土中国 + 词语积累

VALID_KU_TYPES = {
    "wenyan_word", "wenyan_syntax", "mingpian", "chengyu", "wenhua_changshi",
    "xinxi_yuedu", "xiaoshuo_yuedu", "sanwen_yuedu", "wenyan_yuedu", "shici_jianshang",
    "xiezuo", "kouyu_jiaoji", "goutong_chushi",
}

# 鉴赏+表达：必须满足surrogate，know_why不得为空（可为"why待补"）
SURROGATE_TYPES = {
    "xinxi_yuedu", "xiaoshuo_yuedu", "sanwen_yuedu", "wenyan_yuedu",
    "shici_jianshang", "xiezuo", "kouyu_jiaoji", "goutong_chushi",
}

TRACK_MAP = {
    "wenyan_word": "积累", "wenyan_syntax": "积累", "mingpian": "积累",
    "chengyu": "积累", "wenhua_changshi": "积累",
    "xinxi_yuedu": "鉴赏", "xiaoshuo_yuedu": "鉴赏", "sanwen_yuedu": "鉴赏",
    "wenyan_yuedu": "鉴赏", "shici_jianshang": "鉴赏",
    "xiezuo": "表达", "kouyu_jiaoji": "表达", "goutong_chushi": "表达",
}

# ── 002框架 System Prompt ────────────────────────────────────────────────────

LLM_SYSTEM = """你是AII知识本体002框架的KU（知识单元）提取专家，当前处理【高中语文·统编版必修上册】。

▌什么是002框架的KU
  KU = "可迁移知识的替身（surrogate）"。
  不是某篇课文的论据，是学生未来遇到任何同类文本时会用到的知识。

▌三类知识性质(knowledge_kind)——必须标注:
  declarative  事实性 know-what：文言词义/名句/文化常识/成语
               → 填 know_what；know_how/know_why 可为null
  procedural   程序性 know-how：阅读方法/写作步骤/分析流程
               → 填 know_what + know_how；know_why 尽力填
  explanatory  解释性 know-why：机制/规律/审美原理（解释"为什么有效"）
               → 这类ku专门存深层原因
  ⚠️ 鉴赏/写作类ku通常是procedural（有时附explanatory），不是declarative

▌★know_why 诚实原则（核心约束，最重要）:

  判断标准：know_why只回答"为什么这样做有效/成立"（机制/认知规律）
  不是"这有什么用"（用途/活动目标）

  填真机制的情况（示例）：
    ✅ "情景交融比直抒胸臆更有感染力，因为景物是情感的客观对应物，
       读者通过感官体验自然领悟情感而非被告知，符合审美参与感原理"
    ✅ "对比使差异更显著，读者在反差中自动判断优劣，
       符合认知心理学中的对比效应"
    ✅ "典型事件+细节让读者自行推导人物品质，
       符合'展示而非讲述'叙事原理"

  以下情况诚实填"无深层机制(操作性知识)":
    × "高考常考X"（用途，不是机制）
    × "促进合作""激发写作动力"（活动理由）
    × "这样能更好地理解X"（同义复述）
    × "找到核心意象才能分析主题"（步骤合理性，不是深层机制）

  ⚠️ 预期填充率约70-80%，不是100%：
     积累轨(wenyan_word/mingpian/chengyu/wenhua_changshi) → know_why填null
     纯操作性方法且无深层机制 → 诚实填"无深层机制(操作性知识)"
     有深层机制的鉴赏/写作类 → 填真why

  严禁：随手编一个看似合理的机制冒充why！
  注意：填充率降到70-80%是健康的，反映真实情况；
        100%填充率反而说明有假why。

▌surrogate原则——名字必须是知识替身，不是课文标签:
  ❌ "《喜看稻菽千重浪》·通讯报道角度"  （这是课文论据，不是知识）
  ❌ "百合花·细节描写"                  （同上）
  ✅ "通讯报道阅读法"                    （可迁移的知识单元）
  ✅ "小说细节描写赏析法"                （同上）
  课文名放进 example 字段作为实例。
  规则：鉴赏/写作类ku的name中绝对不出现《》书名号！
        文言词/名句/文化常识/成语的name可以含篇名。

▌合并原则（强化）:
  同一方法/概念在多篇课文中出现 → 只出一个ku，多课文进example。
  同一方法不同措辞 → 合并为一个ku，不建雷同ku：
    ❌ 同时出现"小说主题分析法"+"小说主题提炼法"+"小说主题归纳法"
    ✅ 只保留"小说主题分析法"，三篇课文进example
    ❌ 同时出现"小说心理描写分析法"+"小说心理描写赏析法"（核心步骤相同）
    ✅ 合并为一个，取最准确的名字
  判断：核心操作步骤基本相同 → 合并；真正不同侧重 → 可分开

▌高中13类ku_type（精确选一）:
  积累轨(declarative为主):
    wenyan_word     文言词语（词·义项格式）
    wenyan_syntax   文言句式（一类句式+例句+分析）
    mingpian        名篇名句（背诵原文句+出处）
    chengyu         成语（含义+出处，必须抽尽！）
    wenhua_changshi 文学文化常识（作家/纪年/典章/通用概念）
  鉴赏轨(procedural/explanatory):
    xinxi_yuedu     信息类文本（论述/新闻/实用文）阅读方法
    xiaoshuo_yuedu  小说阅读方法
    sanwen_yuedu    散文阅读方法
    wenyan_yuedu    文言文整体阅读方法
    shici_jianshang 诗词鉴赏方法（古典+现代诗）
  表达轨(procedural):
    xiezuo          写作方法（高考议论思辨）
    kouyu_jiaoji    口语交际方法
    goutong_chushi  沟通处世（有则抽）

▌积累轨各类抽取要求:
  wenyan_word: 每篇文言文≥10条，义项用原文例句，
               填 extra: {词性,是否通假,是否古今异义,是否词类活用,活用类型,义项,例句}
  wenyan_syntax: 每篇文言文≥3条（判断/省略/倒装/被动/固定结构各类型都抽）
  mingpian: 课标必背句，逐句单独一条，原文完整句+出处
  chengyu: ★必须尽量抽尽！必修上含大量成语（如残羹冷炙/洗耳恭听/循循善诱等）
  wenhua_changshi: 作家简介、文化常识、通用文学概念定义

▌鉴赏+表达类每个ku输出结构:
  name:           ≤20字，纯知识名称，无《》
  ku_type:        类型
  knowledge_kind: "procedural"（方法）或"explanatory"（纯机制）
  know_what:      ≤60字：这个方法/概念是什么
  know_how:       ≤120字：操作步骤/如何识别/怎么运用
  know_why:       ≤120字：★为什么有效/深层机制（无法推出填"why待补"）
  example:        课文实例，格式"《篇名》(关键细节)"，多个用"；"分隔

▌积累类每个ku输出结构:
  name:           词/句/概念本身（≤30字）
  ku_type:        类型
  knowledge_kind: "declarative"
  know_what:      ≤80字：释义或全文（名句/成语）
  know_how:       null（文言词可填"考点：辨别通假/活用"）
  know_why:       null（积累类通常没有why，填null）
  example:        null（已在name/source_text中体现）
  extra:          wenyan_word时填详细字段，其余null

▌通用字段（所有ku）:
  source_text:    篇名+作者 或 "第X单元·写作"
  difficulty:     0.1-0.9
  prerequisites:  前置ku名（≤3个，只列名字）

═══ 输出格式（纯JSON，无代码块标记）═══
{
  "unit": "单元名",
  "kus": [
    {
      "id": "ku-001",
      "name": "通讯报道阅读法",
      "ku_type": "xinxi_yuedu",
      "knowledge_kind": "procedural",
      "know_what": "以真实事件为材料，通过典型事件和细节展现人物精神品质的新闻文体阅读方法",
      "know_how": "1.找典型事件切入点（而非平铺事件）；2.识别细节描写（动作/语言/神态）；3.分析细节如何支撑中心论点；4.警惕高考设错：偷换概念/以偏概全",
      "know_why": "典型事件+细节使读者自行推导人物品质，而非被告知——符合'展示而非讲述'原则，具体性增强可信度，情景再现让读者产生共鸣",
      "example": "《喜看稻菽千重浪》(袁隆平发现天然杂交稻株)；《心有一团火，温暖众人心》",
      "source_text": "第一单元·通讯报道",
      "difficulty": 0.5,
      "prerequisites": [],
      "extra": null
    },
    {
      "id": "ku-002",
      "name": "属·劝酒义（赤壁赋）",
      "ku_type": "wenyan_word",
      "knowledge_kind": "declarative",
      "know_what": "属，动词，劝人饮酒。例：举酒属客，诵明月之诗，歌窈窕之章。",
      "know_how": null,
      "know_why": null,
      "example": null,
      "source_text": "《赤壁赋》苏轼",
      "difficulty": 0.4,
      "prerequisites": [],
      "extra": {"词性":"动词","是否通假":false,"是否古今异义":false,"是否词类活用":false,"活用类型":null,"义项":"劝人饮酒","例句":"举酒属客，诵明月之诗"}
    }
  ]
}
只输出JSON，不加任何其他文字。"""


# ── PDF 解析（复用已成熟逻辑）────────────────────────────────────────────────

def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(str(pdf_path))
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


def split_into_units(pages: dict[int, str]) -> list[tuple[str, str]]:
    CHARS = "一二三四五六七八九十"
    unit_occurrences: dict[str, list[int]] = {}

    for pg in sorted(pages):
        text = pages[pg]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue
        m = re.match(r"^第([一二三四五六七八九十]+)单元$", lines[0])
        if m:
            unit_ch = m.group(1)
            intro = next((l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)), None)
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue
        m2 = re.match(r"^第([一二三四五六七八九十]+)单元\d+$", lines[0])
        if m2:
            unit_ch = m2.group(1)
            intro = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)
                 and "语文" not in l[:4] and "必修" not in l[:4]),
                None,
            )
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue
        mc = re.match(r"^第([一二三四五六七八九十]+)单元[\s　]+\S", lines[0])
        if mc:
            unit_ch = mc.group(1)
            intro = next((l for l in lines[1:] if len(l) > 5 and not re.match(r"^\d+$", l)), None)
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue
        if len(text) < 600:
            m3 = re.search(r"第([一二三四五六七八九十]+)单元", text)
            if m3 and not re.search(r"\d{2,}", text[:50]):
                unit_occurrences.setdefault(m3.group(1), []).append(pg)

    if not unit_occurrences:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    all_u = sorted(unit_occurrences.keys(), key=lambda x: CHARS.index(x) if x in CHARS else 99)
    unit_starts: dict[str, int] = {}
    prev = 0
    for uch in all_u:
        valid = [p for p in unit_occurrences[uch] if p > prev]
        if valid:
            unit_starts[uch] = valid[0]
            prev = valid[0]

    if not unit_starts:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    ordered = sorted(unit_starts.items(), key=lambda x: x[1])
    pg_sorted = sorted(pages)
    units: list[tuple[str, str]] = []
    for i, (uch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if text.strip():
            units.append((f"第{uch}单元", text))
    return units


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def _call_llm(client: httpx.Client, unit_name: str, chunk: str, hint: str) -> dict:
    is_wenyan = any(kw in chunk[:400] for kw in ["之乎者也", "焉", "乃", "余", "吾", "曰", "矣", "哉"])
    focus = "按002框架抽取：鉴赏/写作类必须标knowledge_kind+know_why；name不绑课文；成语尽量抽尽。"
    if is_wenyan:
        focus = (
            "文言文：wenyan_word每篇≥10条（实词虚词全抽，含extra字段）；"
            "wenyan_syntax每篇≥3条（判断/省略/倒装/被动/固定结构）；"
            "mingpian逐句抽；chengyu尽量抽；wenyan_yuedu整体阅读法1条（加know_why）。"
        )

    user = (
        f"【必修上册】{unit_name}{hint}（{len(chunk)}字）：\n\n{chunk}\n\n{focus}"
    )
    resp = client.post(
        "https://api.deepseek.com/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_tokens": 8192,
            "temperature": 0.1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"无JSON({len(raw)}字)：{raw[:100]}")


def llm_extract(client: httpx.Client, unit_name: str, chunk: str, hint: str) -> list[dict]:
    # 指数退避重试3次（1s/2s/4s）
    for attempt in range(3):
        try:
            data = _call_llm(client, unit_name, chunk, hint)
            return data.get("kus", [])
        except Exception as e:
            wait = 2 ** attempt
            print(f"    [失败 {attempt+1}/3, 等{wait}s] {e}", flush=True)
            if attempt < 2:
                time.sleep(wait)
    # 减半重试
    half = len(chunk) // 2
    print(f"    [减半] {len(chunk)}→{half}+{len(chunk)-half}", flush=True)
    result: list[dict] = []
    for si, sub in enumerate([chunk[:half], chunk[half:]]):
        recovered = False
        for attempt in range(2):
            try:
                data = _call_llm(client, unit_name, sub, f"{hint}(半{si+1})")
                result.extend(data.get("kus", []))
                recovered = True
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"    [减半失败 sub{si+1} {attempt+1}/2, 等{wait}s] {e}", flush=True)
                if attempt < 1:
                    time.sleep(wait)
        if not recovered:
            label = f"{unit_name}{hint}(半{si+1})"
            FAILED_CHUNKS.append(label)
            print(f"    ⚠️  失败已记录: {label}", flush=True)
    return result


# ── 后处理：合并 + 去重 + 校验 ───────────────────────────────────────────────

def _is_text_bound(name: str, ku_type: str) -> bool:
    """鉴赏/表达类ku的name不应包含《》。"""
    return ku_type in SURROGATE_TYPES and "《" in name


def merge_by_name(kus: list[dict]) -> list[dict]:
    """同名ku合并examples；同时dedup。"""
    merged: dict[str, dict] = {}
    order: list[str] = []

    for ku in kus:
        name = ku.get("name", "").strip()
        if not name:
            continue
        if name not in merged:
            merged[name] = ku.copy()
            merged[name].setdefault("_units", [])
            order.append(name)
        else:
            # 合并examples
            existing = merged[name].get("example") or ""
            new_ex = ku.get("example") or ""
            if new_ex and new_ex not in existing:
                merged[name]["example"] = (existing + "；" + new_ex).strip("；")
            # 合并出现单元
            u = ku.get("_unit", "")
            if u and u not in merged[name]["_units"]:
                merged[name]["_units"].append(u)
            # 补充know_why（如果原来是"why待补"，新的有内容则替换）
            if merged[name].get("know_why") == "why待补" and ku.get("know_why") not in (None, "why待补", ""):
                merged[name]["know_why"] = ku["know_why"]

    out: list[dict] = []
    for name in order:
        ku = merged[name]
        kt = ku.get("ku_type", "")
        if kt not in VALID_KU_TYPES:
            ku["ku_type"] = "wenhua_changshi"
        if not ku.get("track"):
            ku["track"] = TRACK_MAP.get(ku.get("ku_type", ""), "积累")
        out.append(ku)
    return out


# ── 审计报告生成 ──────────────────────────────────────────────────────────────

def _truncate(s: str | None, n: int = 80) -> str:
    if not s:
        return "—"
    s = s.replace("\n", " ")
    return s[:n] + "…" if len(s) > n else s


def _why_tag(why: str | None) -> str:
    if not why:
        return "❌缺失"
    if why == "why待补":
        return "⚠️why待补"
    if why == "无深层机制(操作性知识)":
        return "✅诚实无机制"
    if len(why.strip()) < 15:
        return f"⚠️过短({len(why.strip())}字)"
    return "✅真机制"


def build_audit_report(kus: list[dict]) -> str:
    lines: list[str] = []
    a = lines.append

    # ── 统计 ──
    total = len(kus)
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    track_cnt = Counter(ku.get("track") for ku in kus)
    kind_cnt = Counter(ku.get("knowledge_kind") for ku in kus)

    surr_kus = [ku for ku in kus if ku.get("ku_type") in SURROGATE_TYPES]
    text_bound = [ku for ku in surr_kus if _is_text_bound(ku.get("name", ""), ku.get("ku_type", ""))]
    why_missing = [ku for ku in surr_kus if not ku.get("know_why")]
    why_pending = [ku for ku in surr_kus if ku.get("know_why") == "why待补"]
    why_operational = [ku for ku in surr_kus if ku.get("know_why") == "无深层机制(操作性知识)"]
    why_ok = [ku for ku in surr_kus
              if ku.get("know_why")
              and ku.get("know_why") not in ("why待补", "无深层机制(操作性知识)")]

    a("# 必修上 002框架验证报告")
    a("")
    a("## 1. 总体统计")
    a("")
    a(f"- **总KU（去重后）**: {total}")
    a(f"- **三轨**: 积累 {track_cnt.get('积累',0)} / 鉴赏 {track_cnt.get('鉴赏',0)} / 表达 {track_cnt.get('表达',0)}")
    a(f"- **knowledge_kind**: declarative {kind_cnt.get('declarative',0)} / procedural {kind_cnt.get('procedural',0)} / explanatory {kind_cnt.get('explanatory',0)}")
    a("")
    a("| ku_type | 数量 |")
    a("|---------|------|")
    for t, c in sorted(type_cnt.items(), key=lambda x: -x[1]):
        flag = " ★" if t in ("wenyan_word", "wenyan_syntax", "mingpian", "xinxi_yuedu", "shici_jianshang") else ""
        a(f"| {t} | {c}{flag} |")
    a("")

    # ── Surrogate检查 ──
    a("## 2. Surrogate原则检查（鉴赏+表达类）")
    a("")
    a(f"- 鉴赏+表达KU总数: **{len(surr_kus)}**")
    a(f"- ❌ 绑课文（name含《》）: **{len(text_bound)}**")
    a(f"- ✅ 名字是知识替身: **{len(surr_kus) - len(text_bound)}**")
    a("")
    if text_bound:
        a("### ⚠️ 绑课文的KU（需改进）")
        a("")
        a("| name | ku_type | 问题 |")
        a("|------|---------|------|")
        for ku in text_bound:
            a(f"| {ku.get('name','')} | {ku.get('ku_type','')} | name含《》，应改为通用名 |")
        a("")

    # ── know-why检查 ──
    a("## 3. know-why质量（核心验证）")
    a("")
    surr_total = max(len(surr_kus), 1)
    a(f"- 鉴赏+表达KU: **{len(surr_kus)}** 条")
    a(f"- ✅ 真机制know-why: **{len(why_ok)}** ({len(why_ok)*100//surr_total}%)")
    a(f"- ✅ 诚实标注无机制(操作性): **{len(why_operational)}** ({len(why_operational)*100//surr_total}%)")
    a(f"- ⚠️ why待补: **{len(why_pending)}**")
    a(f"- ❌ know_why缺失(null): **{len(why_missing)}**")
    a(f"- 合计有内容(真机制+诚实无机制): **{(len(why_ok)+len(why_operational))*100//surr_total}%**"
      + "  ← 预期70-80%为健康值")
    a("")

    # 按类型展示know-why样本
    by_type: dict[str, list[dict]] = defaultdict(list)
    for ku in surr_kus:
        by_type[ku.get("ku_type", "")].append(ku)

    a("### 鉴赏+表达KU完整展示（审核核心）")
    a("")
    for ku_type in sorted(by_type.keys()):
        type_kus = by_type[ku_type]
        a(f"#### {ku_type}（{len(type_kus)}条）")
        a("")
        for ku in type_kus:
            name = ku.get("name", "")
            kkind = ku.get("knowledge_kind", "—")
            know_what = _truncate(ku.get("know_what"), 80)
            know_how = _truncate(ku.get("know_how"), 100)
            know_why = ku.get("know_why") or ""
            why_status = _why_tag(know_why)
            example = _truncate(ku.get("example"), 80)
            src = ku.get("source_text", "—")
            units_str = "/".join(ku.get("_units", [ku.get("_unit", "")]))

            a(f"**{name}** `{kkind}` [{why_status}]")
            a(f"- know-what: {know_what}")
            a(f"- know-how:  {know_how}")
            a(f"- know-why:  {_truncate(know_why, 120)}")
            a(f"- example:   {example}")
            a(f"- 来源:      {src}  出现单元: {units_str}")
            a("")

    # ── 积累类样本（不展示全部，只展示各类前5条）──
    a("## 4. 积累类KU样本（各类前5条）")
    a("")
    accum_types = ["wenyan_word", "wenyan_syntax", "mingpian", "chengyu", "wenhua_changshi"]
    accum_by_type: dict[str, list[dict]] = defaultdict(list)
    for ku in kus:
        if ku.get("ku_type") in accum_types:
            accum_by_type[ku.get("ku_type", "")].append(ku)

    for kt in accum_types:
        samples = accum_by_type.get(kt, [])
        a(f"### {kt}（共{len(samples)}条，展示前5）")
        a("")
        for ku in samples[:5]:
            name = ku.get("name", "")
            kw = _truncate(ku.get("know_what"), 100)
            src = ku.get("source_text", "—")
            ex_info = ""
            if kt == "wenyan_word" and isinstance(ku.get("extra"), dict):
                ex = ku["extra"]
                tags = []
                if ex.get("词性"):     tags.append(ex["词性"])
                if ex.get("是否通假"): tags.append("通假")
                if ex.get("是否古今异义"): tags.append("古今异义")
                if ex.get("是否词类活用") and ex.get("活用类型"): tags.append(f"词类活用:{ex['活用类型']}")
                if tags:
                    ex_info = f" [{'/'.join(tags)}]"
            a(f"- **{name}**{ex_info}｜{kw}｜{src}")
        a("")

    # ── 问题汇总 ──
    a("## 5. 问题清单（需人工确认）")
    a("")
    issues: list[str] = []

    if text_bound:
        issues.append(f"❌ **Surrogate违规 {len(text_bound)}条**：鉴赏/表达ku的name包含《》（绑课文），需改为通用名")

    if why_missing:
        issues.append(f"❌ **know_why缺失 {len(why_missing)}条**：鉴赏/表达ku应标know_why或'why待补'")

    if why_pending:
        issues.append(f"⚠️ **why待补 {len(why_pending)}条**：有依据后可补充；如确实无来源可接受")

    chengyu_n = type_cnt.get("chengyu", 0)
    if chengyu_n < 10:
        issues.append(f"⚠️ **成语偏少 {chengyu_n}条**（必修上预期≥15条，含拿来主义/劝学等文本中的成语）")

    wenyan_syntax_n = type_cnt.get("wenyan_syntax", 0)
    if wenyan_syntax_n < 30:
        issues.append(f"⚠️ **wenyan_syntax {wenyan_syntax_n}条**（预期≥30，第三/六/七单元有4篇文言文）")

    # 检查鉴赏KU中有无同类型多ku是否可合并的线索
    name_prefix_groups: dict[str, list[str]] = defaultdict(list)
    for ku in surr_kus:
        name = ku.get("name", "")
        if len(name) >= 4:
            name_prefix_groups[name[:4]].append(name)
    dupes = {k: v for k, v in name_prefix_groups.items() if len(v) >= 3}
    if dupes:
        issues.append(f"⚠️ **潜在重复ku**：前缀相似的鉴赏/表达KU，可能需要合并：{list(dupes.values())[:3]}")

    if not issues:
        a("✅ 未发现明显问题")
    else:
        for issue in issues:
            a(f"- {issue}")
    a("")

    a("---")
    a("*由 extract_chinese_hs_002.py AII知识本体002框架生成*")

    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="只处理前N个单元（调试）")
    args = parser.parse_args()

    if not DS_KEY:
        sys.exit("需要 DEEPSEEK_API_KEY 环境变量")
    if not PDF.exists():
        sys.exit(f"PDF不存在: {PDF}")

    print(f"PDF: {PDF.name}", flush=True)
    print(f"CHUNK={CHUNK} | 002框架试抽 | dry-run", flush=True)

    pages = extract_page_texts(PDF)
    units = split_into_units(pages)
    print(f"识别 {len(units)} 个单元: {[u[0] for u in units]}", flush=True)

    units_to_run = units[:args.limit] if args.limit else units
    all_raw_kus: list[dict] = []

    with httpx.Client(headers={"Authorization": f"Bearer {DS_KEY}"}, timeout=130) as client:
        for unit_name, unit_text in units_to_run:
            if not unit_text.strip():
                continue
            if unit_name in SKIP:
                print(f"\n  [跳过] {unit_name}", flush=True)
                continue

            parts: list[str] = []
            if len(unit_text) <= CHUNK:
                parts = [unit_text]
            else:
                n = (len(unit_text) + CHUNK - 1) // CHUNK
                parts = [unit_text[i * CHUNK:(i + 1) * CHUNK] for i in range(n)]

            unit_kus: list[dict] = []
            for pi, part in enumerate(parts):
                hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
                print(f"  {unit_name}{hint} {len(part)}字", flush=True)
                kus = llm_extract(client, unit_name, part, hint)
                for ku in kus:
                    ku["_unit"] = unit_name
                unit_kus.extend(kus)
                print(f"    → {len(kus)} KU", flush=True)

            all_raw_kus.extend(unit_kus)

    print(f"\n原始: {len(all_raw_kus)} KU → 合并去重...", flush=True)
    merged = merge_by_name(all_raw_kus)
    print(f"去重后: {len(merged)} KU", flush=True)

    # 生成审计报告
    report = build_audit_report(merged)
    out_path = Path(__file__).parent / "chinese_002_audit.md"
    out_path.write_text(report, encoding="utf-8")

    # 控制台摘要
    type_cnt = Counter(ku.get("ku_type") for ku in merged)
    track_cnt = Counter(ku.get("track") for ku in merged)
    print(f"\n{'='*60}", flush=True)
    print(f"总计: {len(merged)} KU | 三轨: 积累{track_cnt.get('积累',0)}/鉴赏{track_cnt.get('鉴赏',0)}/表达{track_cnt.get('表达',0)}", flush=True)
    for t, c in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"  {t:25s}: {c}", flush=True)
    print(f"\n审计报告已写出: {out_path}", flush=True)
    if FAILED_CHUNKS:
        print("\n⚠️  失败chunk（数据缺失，需手动补抽）：", flush=True)
        for fc in FAILED_CHUNKS:
            print(f"  - {fc}", flush=True)
    else:
        print("✅ 无失败chunk", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
