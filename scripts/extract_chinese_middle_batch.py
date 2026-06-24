#!/usr/bin/env python3
"""
初中语文 KU 批量提取 + 入库（三轨19类体系）。

修复记录（相对 pilot 版本）：
  #1 CHUNK 5000→3000（防止文言文密集单元输出截断）
  #2 mingzhu_yuedu 只抽必读名著，自主阅读推荐不抽
  #3 校验逻辑按册：不强制要求不存在的类型（如九上无说明文）
  #4 wenyan_syntax 强调：每篇文言文必须 ≥3 条句式
  #5 shici_jianshang 只放具体诗词鉴赏，通用定义归 wenhua_changshi

用法：
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme \\
  DEEPSEEK_API_KEY=... \\
  .venv/bin/python scripts/extract_chinese_middle_batch.py [--books G7-S,G7-X,...] [--dry-run]

  --books   逗号分隔的 tb_id 后缀（如 G7-S,G8-S）；默认全部6本
  --dry-run 只打印，不入库
  --limit N 每本只跑前 N 个单元（调试）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("缺少 pymupdf: pip install pymupdf")
try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg: pip install asyncpg")
try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
DS_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DB_URL  = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme")
CHUNK   = 3_000  # Fix #1: 5000→3000，防止文言文密集单元输出超 max_tokens

CATALOG = [
    {"tb_id": "TONGBIAN-G7-CHINESE-S", "filename": "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文七年级上册.pdf", "title": "统编版语文七年级上册"},
    {"tb_id": "TONGBIAN-G7-CHINESE-X", "filename": "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文七年级下册.pdf", "title": "统编版语文七年级下册"},
    {"tb_id": "TONGBIAN-G8-CHINESE-S", "filename": "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文八年级上册.pdf", "title": "统编版语文八年级上册"},
    {"tb_id": "TONGBIAN-G8-CHINESE-X", "filename": "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文八年级下册.pdf", "title": "统编版语文八年级下册"},
    {"tb_id": "TONGBIAN-G9-CHINESE-S", "filename": "M_语文_义务教育教科书·语文九年级上册.pdf", "title": "统编版语文九年级上册"},
    {"tb_id": "TONGBIAN-G9-CHINESE-X", "filename": "M_语文_义务教育教科书·语文九年级下册.pdf", "title": "统编版语文九年级下册"},
]

# 各册预期有的类型（用于校验，不在列表里的不强制检查）
BOOK_EXPECTED_TYPES: dict[str, list[str]] = {
    "TONGBIAN-G7-CHINESE-S": ["wenyan_word", "mingju", "zixing_ziyin", "jixuwen_yuedu", "xiezuo", "mingzhu_yuedu"],
    "TONGBIAN-G7-CHINESE-X": ["wenyan_word", "mingju", "zixing_ziyin", "jixuwen_yuedu", "xiezuo", "mingzhu_yuedu"],
    "TONGBIAN-G8-CHINESE-S": ["wenyan_word", "mingju", "zixing_ziyin", "shuomingwen_yuedu", "jixuwen_yuedu", "xiezuo", "mingzhu_yuedu", "bingju"],
    "TONGBIAN-G8-CHINESE-X": ["wenyan_word", "mingju", "zixing_ziyin", "yilunwen_yuedu", "jixuwen_yuedu", "xiezuo", "mingzhu_yuedu", "bingju"],
    "TONGBIAN-G9-CHINESE-S": ["wenyan_word", "wenyan_syntax", "mingju", "zixing_ziyin", "yilunwen_yuedu", "jixuwen_yuedu", "xiezuo", "mingzhu_yuedu", "bingju"],
    "TONGBIAN-G9-CHINESE-X": ["wenyan_word", "wenyan_syntax", "mingju", "zixing_ziyin", "yilunwen_yuedu", "xiezuo", "mingzhu_yuedu", "bingju"],
}

# ── 初中语文 KU 类型（三轨19类）──────────────────────────────────────────────

VALID_KU_TYPES = {
    "wenyan_word", "wenyan_syntax", "mingju", "chengyu", "zixing_ziyin",
    "cizu_yunyong", "wenhua_changshi", "bingju", "biaodian",
    "jixuwen_yuedu", "shuomingwen_yuedu", "yilunwen_yuedu", "sanwen_yuedu",
    "wenyan_yuedu", "shici_jianshang", "mingzhu_yuedu",
    "xiezuo", "kouyu_jiaoji", "goutong_chushi",
}

TRACK_MAP = {
    "wenyan_word": "积累", "wenyan_syntax": "积累", "mingju": "积累",
    "chengyu": "积累", "zixing_ziyin": "积累", "cizu_yunyong": "积累",
    "wenhua_changshi": "积累", "bingju": "积累", "biaodian": "积累",
    "jixuwen_yuedu": "鉴赏", "shuomingwen_yuedu": "鉴赏", "yilunwen_yuedu": "鉴赏",
    "sanwen_yuedu": "鉴赏", "wenyan_yuedu": "鉴赏", "shici_jianshang": "鉴赏",
    "mingzhu_yuedu": "鉴赏",
    "xiezuo": "表达", "kouyu_jiaoji": "表达", "goutong_chushi": "表达",
}

# ── LLM System Prompt ─────────────────────────────────────────────────────────

LLM_SYSTEM = """你是中国K12语文教材知识点（KU）提取专家，当前处理【初中语文（义务教育统编版）】。

▌核心原则：
  KU = "从课文提取的最小可独立练习/背诵/应用的语言材料或方法"。
  初中语文中考重考：字音字形、名句默写、文言实词/句式、病句辨析、记叙文/说明文/议论文阅读方法、名著。

▌三轨19类 ku_type（精确选一，禁止使用列表外的类型）：

——轨一·积累型（FSRS背诵/选择题练习）——
  wenyan_word     文言词语：一个具体文言词的义项（实词/虚词/通假/古今异义/词类活用）
                  ⚠️ 格式："词·义项" ← 禁止"课文名·句子"格式
                  ⚠️ 每个义项单独一条，不合并多词；虚词"之/其/而/于/以/乃"等按义项分条
  wenyan_syntax   文言句式：一种具体句式+原文例句
                  ⚠️【强化】每篇文言文必须提取≥3条句式（不足3条则说明抽得不全）
                  必覆盖类型：判断句（"……者……也"）/ 省略句（主语省略等）/
                  倒装句（宾语前置/状语后置/定语后置）/ 被动句 / 固定结构（如"……何为"）
                  ⚠️ 文中有什么就抽什么，不能因为"类型雷同"而省略
  mingju          名句默写：课程标准要求背诵的完整句子，每句/每联单独一条
                  ⚠️ 名称格式含句子本身，如"先忧后乐（岳阳楼记）"
  chengyu         成语：含义+出处
  zixing_ziyin    字音字形：每字单独一条，包含正确读音/写法+辨析要点
                  ⚠️ 宁多勿少——中考基础题来源，课文所有生字词都要抽
                  ⚠️ 重点：形声字（如"绯fēi"）、形近字（燥/噪/躁）、多音字（模mó/mú）
  cizu_yunyong    词语运用：近义词辨析 或 关联词用法（每条只辨析一对/一组）
  wenhua_changshi 文学文化常识：作家（朝代/国籍/代表作/文学地位）或 古代文化常识（每条一个知识点）
                  ⚠️【Fix#5】通用概念定义（如"意象是诗歌中寄托情感的物象"）归本类，不归shici_jianshang
  bingju          病句辨析：六种类型（成分残缺/搭配不当/语序不当/结构混乱/表意不明/不合逻辑）
                  每条包含：典型例句 + 病因分析 + 改正方法
  biaodian        标点符号：某标点的具体用法规则+典型例句（每条只讲一种用法）

——轨二·鉴赏型（苏格拉底引导）——
  jixuwen_yuedu   记叙文阅读方法：人物描写/情节结构/标题作用/句子含义/情感主旨/叙事手法
                  ⚠️【Fix#5】只放针对具体篇目的阅读方法，方法名要含课文名
  shuomingwen_yuedu 说明文阅读方法：说明方法（举例/列数字/分类别/打比方/作比较/下定义）/
                  说明顺序/语言准确性（"几乎""大约"等限制性词语）
                  ⚠️ 从说明文单元提取，每种说明方法单独一条
  yilunwen_yuedu  议论文阅读方法：论点提炼/论据类型（事实论据/道理论据）/
                  论证方法（举例/道理/对比/比喻论证）/驳论文批驳方式
  sanwen_yuedu    散文阅读方法：写景/叙事/抒情散文的语言赏析/情感把握/结构手法
  wenyan_yuedu    文言文整体阅读方法：翻译技巧（留删换调补）/断句规律/
                  内容理解/人物形象/写作手法（每篇文言文提取1条）
  shici_jianshang 古诗词鉴赏（现代诗+古典诗词）：
                  ⚠️【Fix#5】必须针对具体诗词，ku名格式"《诗名》·鉴赏角度"
                  ⚠️ 通用诗歌概念定义（意象、炼字的定义）改归 wenhua_changshi
                  内容：意象含义/情感主旨/表现手法/炼字炼句，每首1-3条
  mingzhu_yuedu   名著阅读：
                  ⚠️【Fix#2】只抽教材"名著导读"正文的【必读名著】，"自主阅读推荐"的书跳过不抽
                  ⚠️ 九上必读：《艾青诗选》《水浒传》；七上：《朝花夕拾》《西游记》；
                     七下：《骆驼祥子》《海底两万里》；八上：《红星照耀中国》《昆虫记》；
                     八下：《傅雷家书》《钢铁是怎样炼成的》；九下：《儒林外史》《简爱》
                  ⚠️ 每部名著抽2-3条（可按人物/结构/主题/语言分多条）：
                     作者+时代+背景+主要内容+核心人物形象+主题+1-2个经典情节

——轨三·表达型——
  xiezuo          写作方法：记叙文/说明文/议论文的某一具体写法（每单元必须有）
  kouyu_jiaoji    口语交际：语言得体/图文转换/拟写标语/演讲/辩论技能
  goutong_chushi  沟通处世：得体表达/劝说策略（有则抽）

▌每个 KU 的字段：
  name           ≤30字，积累型含词/句本身，鉴赏型含课文名+方法关键词
  ku_type        19类之一
  track          "积累"/"鉴赏"/"表达"
  core           ≤120字，内容见下：
                 · wenyan_word：词性+义项+原文例句
                 · wenyan_syntax：句式类型+格式特征+原文例句+分析
                 · mingju：完整原文+出处
                 · zixing_ziyin：字+正确读音/写法+辨析要点（形声字说字族）
                 · bingju：例句+病因（六种之一）+改正方法
                 · biaodian：用法规则+例句
                 · 鉴赏型：方法要点（含具体课文分析，不能只说原则）
                 · mingzhu_yuedu：作者/时代/主要内容/核心人物/主题/经典情节
                 · xiezuo/kouyu：能力要点+方法步骤
  source_text    出处（篇名+作者 或 "名著导读·《书名》" 或 "第X单元·写作"）
  difficulty     0.1–0.9
  prerequisites  前置KU名列表（≤3个，可为[]）
  extra          ku_type=wenyan_word 时填写，其他为null：
                 {"词性":"动词/名词/虚词/...", "是否通假":false, "是否古今异义":false,
                  "是否词类活用":false, "活用类型":null, "义项":"简述", "例句":"≤20字"}

▌抽取规则（按文体/板块）：
  文言文：wenyan_word逐词（≥8个/篇）+ wenyan_syntax≥3条 + mingju逐句 + wenhua_changshi + wenyan_yuedu
  古诗词：shici_jianshang（1-3条具体鉴赏）+ mingju（必背句） + wenhua_changshi（作家简介）
  现代文记叙文/小说：jixuwen_yuedu（1-3条）+ zixing_ziyin（全部生字）+ chengyu + wenhua_changshi
  说明文：shuomingwen_yuedu（每种说明方法一条）+ zixing_ziyin + cizu_yunyong
  议论文：yilunwen_yuedu（1-3条）+ zixing_ziyin + wenhua_changshi
  名著导读（必读部分）：mingzhu_yuedu（2-3条/部，必须有）
  每单元写作板块：xiezuo（必须有）
  每单元口语交际：kouyu_jiaoji（有则抽）
  病句/标点：从单元练习或课后题提取 bingju/biaodian（每种类型至少1条）

▌数量目标（全册参考）：
  wenyan_word ≥60（文言文多的册），字音字形 ≥30，mingju ≥20，bingju ≥3

输出纯 JSON（无 markdown 代码块）：
{
  "unit": "单元名称",
  "kus": [
    {
      "id": "ku-001",
      "name": "先忧后乐（岳阳楼记）",
      "ku_type": "mingju",
      "track": "积累",
      "core": "先天下之忧而忧，后天下之乐而乐。范仲淹《岳阳楼记》，表达忧乐观。",
      "source_text": "《岳阳楼记》范仲淹",
      "difficulty": 0.2,
      "prerequisites": [],
      "extra": null
    }
  ],
  "kcs": [
    {"id": "kc-001", "name": "《岳阳楼记》文言词语", "logic_reason": "同篇聚类", "ku_ids": ["ku-001"]}
  ]
}
只输出 JSON，不加任何其他文字。"""

# ── PDF 解析 ──────────────────────────────────────────────────────────────────

def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        sys.exit(f"PDF 打开失败: {e}")
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


def split_into_units(pages: dict[int, str]) -> list[tuple[str, str]]:
    """识别初中语文单元边界，名著导读单独成一段。"""
    CHARS = "一二三四五六七八九十"
    unit_occurrences: dict[str, list[int]] = {}

    for pg in sorted(pages):
        text = pages[pg]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue

        # 模式A：第一行="第X单元"（纯净）
        m = re.match(r"^第([一二三四五六七八九十]+)单元$", lines[0])
        if m:
            unit_ch = m.group(1)
            intro = next((l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)), None)
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式B：第一行="第X单元NNN"（单元号+页码粘连）
        m2 = re.match(r"^第([一二三四五六七八九十]+)单元\d+$", lines[0])
        if m2:
            unit_ch = m2.group(1)
            intro = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l) and "语文" not in l[:4]),
                None,
            )
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式C：第一行="第X单元  活动·探究"等（含空格+主题词）
        # 处理如"第四单元  活动·探究"/"第五单元  活动·探究"格式
        mc = re.match(r"^第([一二三四五六七八九十]+)单元[\s　]+\S", lines[0])
        if mc:
            unit_ch = mc.group(1)
            intro = next((l for l in lines[1:] if len(l) > 5 and not re.match(r"^\d+$", l)), None)
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 兜底：页面<600字 且含"第X单元" 且页面开头无两位页码
        if len(text) < 600:
            m3 = re.search(r"第([一二三四五六七八九十]+)单元", text)
            if m3 and not re.search(r"\d{2,}", text[:50]):
                unit_occurrences.setdefault(m3.group(1), []).append(pg)

    if "一" not in unit_occurrences:
        for pg in sorted(pages)[:20]:
            text = pages[pg]
            if len(text) < 400 and not re.search(r"第[二三四五六七八九十]+单元", text):
                if re.search(r"本单元", text):
                    unit_occurrences["一"] = [pg]
                    break

    # 名著导读起始页（不限页面字数，因为名著导读首页内容丰富）
    mingzhu_start: int | None = None
    for pg in sorted(pages):
        text = pages[pg]
        # 首行或前100字含"名著导读"，且不是页眉（后面有实质内容）
        if re.search(r"名著导读", text[:100]) and len(text) > 100:
            mingzhu_start = pg
            break

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
        if mingzhu_start and start_pg < mingzhu_start < end_pg:
            end_pg = mingzhu_start
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if text.strip():
            units.append((f"第{uch}单元", text))

    if mingzhu_start:
        mz_text = "\n".join(pages[p] for p in pg_sorted if p >= mingzhu_start)
        if mz_text.strip():
            # 限制名著导读长度：只取正文部分（前 CHUNK*3 字符），不截掉关键内容
            units.append(("名著导读", mz_text[:CHUNK * 3]))

    return units


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def _call_llm(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str, tb_id: str) -> dict:
    # 根据单元类型给不同的重点提示
    focus = "请抽取所有KU（写作板块必须有xiezuo）。"
    if "文言" in text_chunk[:200] or unit_name in ("第三单元", "第四单元", "第五单元"):
        focus = (
            "文言文重点：wenyan_word逐词抽（≥8条）；wenyan_syntax每篇≥3条句式（判断/省略/倒装/被动/固定结构）；"
            "mingju逐句抽；wenyan_yuedu整体阅读方法1条。写作板块必须有xiezuo。"
        )
    elif "名著导读" in unit_name:
        focus = (
            "【名著导读】只抽本册必读名著的mingzhu_yuedu（2-3条/部）。"
            "自主阅读推荐部分（如《三国演义》《唐诗三百首》《泰戈尔诗选》《世说新语》等）直接跳过，不抽任何KU。"
            "每部名著：作者/时代/主要内容/核心人物形象/主题/经典情节。"
        )
    elif "说明" in text_chunk[:300]:
        focus = "说明文重点：shuomingwen_yuedu每种说明方法单独一条；字音字形全部生字词；写作板块必须有xiezuo。"
    elif "议论" in text_chunk[:300]:
        focus = "议论文重点：yilunwen_yuedu（论点/论据/论证方法）；bingju从练习题提取；写作板块必须有xiezuo。"

    user = (
        f"【初中语文·{tb_id}】{unit_name}{part_hint} 正文（{len(text_chunk)}字）：\n\n"
        f"{text_chunk}\n\n"
        f"{focus}"
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
    raise ValueError(f"无 JSON（{len(raw)}字）：{raw[:120]}")


def llm_extract(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str, tb_id: str) -> dict:
    for attempt in range(2):
        try:
            return _call_llm(client, unit_name, text_chunk, part_hint, tb_id)
        except Exception as e:
            print(f"    [LLM 失败 attempt {attempt+1}] {e}", flush=True)
            time.sleep(3)

    half = len(text_chunk) // 2
    print(f"    [减半重试] {len(text_chunk)}→{half}+{len(text_chunk)-half}", flush=True)
    merged: dict = {"unit": unit_name, "kus": [], "kcs": []}
    kid_offset = 0
    for sub_idx, sub in enumerate([text_chunk[:half], text_chunk[half:]]):
        try:
            d = _call_llm(client, unit_name, sub, f"{part_hint}(减半{sub_idx+1}/2)", tb_id)
            for ku in d.get("kus", []):
                old_id = ku.get("id", f"ku-{kid_offset:03d}")
                ku["id"] = f"ku-{kid_offset:03d}"
                for kc in d.get("kcs", []):
                    kc["ku_ids"] = [ku["id"] if k == old_id else k for k in kc.get("ku_ids", [])]
                kid_offset += 1
            merged["kus"].extend(d.get("kus", []))
            merged["kcs"].extend(d.get("kcs", []))
        except Exception as e:
            print(f"    [减半失败 sub{sub_idx+1}] {e}", flush=True)
    return merged


# ── 主抽取循环 ────────────────────────────────────────────────────────────────

def _attach_kcs(kus: list[dict], kcs: list[dict]) -> None:
    ku_kc: dict[str, list[str]] = {}
    for kc in kcs:
        for kid in kc.get("ku_ids", []):
            ku_kc.setdefault(kid, []).append(kc.get("name", ""))
    for ku in kus:
        ku.setdefault("_kcs", ku_kc.get(ku.get("id", ""), []) or ["综合语文知识"])


def extract_all_kus(
    client: httpx.Client,
    units: list[tuple[str, str]],
    tb_id: str,
    limit: int | None = None,
) -> list[dict]:
    all_kus: list[dict] = []
    units_to_run = units[:limit] if limit else units

    for unit_name, unit_text in units_to_run:
        if not unit_text.strip():
            continue

        parts: list[str] = []
        if len(unit_text) <= CHUNK:
            parts = [unit_text]
        else:
            n = (len(unit_text) + CHUNK - 1) // CHUNK
            for i in range(n):
                parts.append(unit_text[i * CHUNK: (i + 1) * CHUNK])

        for pi, part in enumerate(parts):
            hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
            print(f"  LLM: {unit_name}{hint} ({len(part)}字)", flush=True)
            data = llm_extract(client, unit_name, part, hint, tb_id)
            kus = data.get("kus", [])
            kcs = data.get("kcs", [])

            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            _attach_kcs(kus, kcs)
            for ku in kus:
                ku["_unit"] = unit_name
                kt = ku.get("ku_type", "")
                if kt not in VALID_KU_TYPES:
                    print(f"    ⚠️  未知类型 '{kt}'，归 wenyan_word", flush=True)
                    ku["ku_type"] = "wenyan_word"
                    kt = "wenyan_word"
                if not ku.get("track"):
                    ku["track"] = TRACK_MAP.get(kt, "积累")
                ku["prerequisites"] = [id_to_name.get(p, p) for p in ku.get("prerequisites", []) if p]
            all_kus.extend(kus)
            print(f"    → {len(kus)} KU 抽出", flush=True)

    return all_kus


def dedup_kus(kus: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for ku in kus:
        key = ku.get("name", "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ku)
    return out


# ── 校验 Fix #3：按册校验 ─────────────────────────────────────────────────────

def anomaly_check(tb_id: str, kus: list[dict]) -> bool:
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    total = len(kus)

    if total == 0:
        print(f"  ⚠️  {tb_id}: 0 KU，停止", flush=True)
        return False

    # 严重集中（>80% 同类型）
    if total >= 10:
        max_ratio = max(type_cnt.values()) / total
        if max_ratio > 0.80:
            dom = max(type_cnt, key=type_cnt.get)
            print(f"  ⚠️  {tb_id}: {dom} 占 {max_ratio:.0%}，分类异常，停止", flush=True)
            return False

    # 三轨必须都有
    tracks = Counter(TRACK_MAP.get(ku.get("ku_type", ""), "") for ku in kus)
    for tr in ("积累", "鉴赏", "表达"):
        if tracks.get(tr, 0) == 0:
            print(f"  ⚠️  {tb_id}: 轨·{tr}=0，停止", flush=True)
            return False

    # 按册校验必有类型
    required = BOOK_EXPECTED_TYPES.get(tb_id, [])
    missing = [t for t in required if type_cnt.get(t, 0) == 0]
    if missing:
        print(f"  ⚠️  {tb_id}: 缺少必有类型 {missing}，停止", flush=True)
        return False

    return True


# ── DB 入库 ──────────────────────────────────────────────────────────────────

def pg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert_cluster(conn: asyncpg.Connection, tb_id: str, kc_name: str, order: int) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", kc_name)[:40].strip("-").lower()
    kc_id = f"{tb_id}-kc-{slug}"
    await conn.execute(
        """
        INSERT INTO knowledge_clusters (id, textbook_id, name, display_order)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO NOTHING
        """,
        kc_id, tb_id, kc_name, order,
    )
    return kc_id


async def upsert_ku(conn: asyncpg.Connection, tb_id: str, cluster_id: str, ku: dict) -> None:
    slug = re.sub(r"[^\w一-鿿]", "-", ku["name"])[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type = ku.get("ku_type", "wenyan_word")

    desc_parts: list[str] = []
    if ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("source_text"):
        desc_parts.append(f"【来源】{ku['source_text']}")
    if ku.get("track"):
        desc_parts.append(f"【轨道】{ku['track']}")
    if isinstance(ku.get("extra"), dict) and ku_type == "wenyan_word":
        ex = ku["extra"]
        parts_ex: list[str] = []
        if ex.get("词性"):       parts_ex.append(f"词性：{ex['词性']}")
        if ex.get("是否通假"):     parts_ex.append("通假字")
        if ex.get("是否古今异义"):  parts_ex.append("古今异义")
        if ex.get("是否词类活用") and ex.get("活用类型"):
            parts_ex.append(f"词类活用：{ex['活用类型']}")
        if ex.get("义项"):       parts_ex.append(f"义项：{ex['义项']}")
        if ex.get("例句"):       parts_ex.append(f"例句：{ex['例句']}")
        if parts_ex:
            desc_parts.append(f"【文言】{'；'.join(parts_ex)}")

    description = "\n".join(desc_parts) or None

    await conn.execute(
        """
        INSERT INTO knowledge_units
          (id, textbook_id, cluster_id, name, description,
           prerequisites, related_kus, difficulty, exam_frequency,
           question_types, ku_type, mastery_levels)
        VALUES ($1,$2,$3,$4,$5,$6,'[]'::jsonb,$7,'mid','[]'::jsonb,$8,'[]'::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        ku_id, tb_id, cluster_id,
        ku["name"], description,
        prereqs, diff, ku_type,
    )


async def store_kus(conn: asyncpg.Connection, tb_id: str, kus: list[dict]) -> int:
    kc_map: dict[str, str] = {}
    order = 1
    for ku in kus:
        for kc_name in ku.get("_kcs", []):
            if kc_name not in kc_map:
                kc_map[kc_name] = await upsert_cluster(conn, tb_id, kc_name, order)
                order += 1

    fallback = (
        await upsert_cluster(conn, tb_id, "综合语文知识", 999)
        if not kc_map else next(iter(kc_map.values()))
    )
    for ku in kus:
        kc_names = ku.get("_kcs") or ["综合语文知识"]
        cluster_id = kc_map.get(kc_names[0], fallback)
        await upsert_ku(conn, tb_id, cluster_id, ku)
    return len(kus)


# ── 单本处理 ──────────────────────────────────────────────────────────────────

async def process_book(
    book: dict,
    client: httpx.Client,
    dry_run: bool,
    limit: int | None,
) -> dict:
    tb_id = book["tb_id"]
    pdf   = PDF_DIR / book["filename"]

    if not pdf.exists():
        print(f"\n[跳过] {tb_id}: PDF 不存在", flush=True)
        return {"tb_id": tb_id, "ku_count": 0, "skipped": True}

    print(f"\n{'='*60}", flush=True)
    print(f"开始: {book['title']} ({tb_id})", flush=True)
    print(f"PDF:  {pdf.name} ({pdf.stat().st_size // 1024} KB)", flush=True)

    pages = extract_page_texts(pdf)
    units = split_into_units(pages)
    print(f"识别到 {len(units)} 个单元: {[u[0] for u in units]}", flush=True)

    if not units:
        print(f"  ⚠️  未识别到任何单元，跳过", flush=True)
        return {"tb_id": tb_id, "ku_count": 0, "skipped": True}

    kus = extract_all_kus(client, units, tb_id, limit=limit)
    kus = dedup_kus(kus)

    type_cnt  = Counter(ku.get("ku_type") for ku in kus)
    track_cnt = Counter(ku.get("track") for ku in kus)

    print(f"\n  ── {tb_id} 分布 ──", flush=True)
    print(f"  总计: {len(kus)} KU  |  三轨: {dict(track_cnt)}", flush=True)
    for t, c in sorted(type_cnt.items(), key=lambda x: -x[1]):
        flag = " ← ★" if t in ("wenyan_syntax", "shuomingwen_yuedu", "mingzhu_yuedu", "bingju") else ""
        print(f"    {t:25s}: {c}{flag}", flush=True)

    # 每类样本 1 条
    print(f"\n  ── 样本 ──", flush=True)
    shown: set = set()
    for ku in kus:
        t = ku.get("ku_type")
        if t not in shown:
            shown.add(t)
            print(f"  [{t}] {ku.get('name')} | {ku.get('core','')[:70]}", flush=True)

    if dry_run:
        print(f"\n  [dry-run] 跳过入库", flush=True)
        return {"tb_id": tb_id, "ku_count": len(kus), "type_cnt": dict(type_cnt), "track_cnt": dict(track_cnt)}

    if not anomaly_check(tb_id, kus):
        print(f"  ⚠️  异常检测不过，{tb_id} 不入库", flush=True)
        return {"tb_id": tb_id, "ku_count": 0, "anomaly": True}

    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        count = await store_kus(conn, tb_id, kus)
        print(f"\n  ✅ {tb_id} 入库 {count} KU", flush=True)
    finally:
        await conn.close()

    return {"tb_id": tb_id, "ku_count": len(kus), "type_cnt": dict(type_cnt), "track_cnt": dict(track_cnt)}


# ── 全局汇总 ──────────────────────────────────────────────────────────────────

async def print_summary() -> None:
    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        rows = await conn.fetch("""
            SELECT t.id, t.grade, t.book_name,
                   COUNT(ku.id) AS ku_count,
                   COUNT(DISTINCT ku.ku_type) AS type_count
            FROM textbooks t
            LEFT JOIN knowledge_units ku ON ku.textbook_id = t.id
            WHERE t.subject = 'chinese' AND t.grade IN ('G7','G8','G9')
            GROUP BY t.id, t.grade, t.book_name
            ORDER BY t.grade, t.id
        """)
        print("\n\n══ 初中语文 KU 全局汇总 ══")
        total = 0
        for r in rows:
            print(f"  {r['id']:35s}  {r['ku_count']:4d} KU  {r['type_count']} 类型  {r['book_name']}")
            total += r["ku_count"]
        print(f"\n  初中语文合计: {total} KU")

        # 全局类型分布
        type_rows = await conn.fetch("""
            SELECT ku.ku_type, COUNT(*) AS n
            FROM knowledge_units ku
            JOIN textbooks t ON t.id = ku.textbook_id
            WHERE t.subject = 'chinese' AND t.grade IN ('G7','G8','G9')
            GROUP BY ku.ku_type ORDER BY n DESC
        """)
        print("\n  全局类型分布：")
        for r in type_rows:
            print(f"    {r['ku_type']:25s}: {r['n']}")
    finally:
        await conn.close()


# ── 入口 ─────────────────────────────────────────────────────────────────────

def _match(tb_id: str, book_filter: list[str]) -> bool:
    if not book_filter:
        return True
    suffix = "-".join(tb_id.split("-")[-2:])  # 如 "G7-S"
    return any(f == suffix or f == tb_id for f in book_filter)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", default="", help="逗号分隔的后缀，如 G7-S,G8-S（默认全部）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not DS_KEY:
        sys.exit("需要 DEEPSEEK_API_KEY 环境变量")

    book_filter = [b.strip() for b in args.books.split(",") if b.strip()]
    books = [b for b in CATALOG if _match(b["tb_id"], book_filter)]
    if not books:
        avail = ["-".join(b["tb_id"].split("-")[-2:]) for b in CATALOG]
        sys.exit(f"无匹配教材。可用后缀: {avail}")

    print(f"计划处理 {len(books)} 本: {[b['tb_id'] for b in books]}", flush=True)
    print(f"CHUNK={CHUNK} | {'dry-run' if args.dry_run else '入库模式'}", flush=True)

    results: list[dict] = []
    with httpx.Client(headers={"Authorization": f"Bearer {DS_KEY}"}, timeout=130) as client:
        for book in books:
            r = await process_book(book, client, args.dry_run, args.limit)
            results.append(r)

    # 打印运行汇总
    print("\n\n══ 本次运行汇总 ══")
    for r in results:
        if r.get("skipped"):
            print(f"  {r['tb_id']:35s}  [跳过]")
        elif r.get("anomaly"):
            print(f"  {r['tb_id']:35s}  [异常未入库]")
        else:
            print(f"  {r['tb_id']:35s}  {r['ku_count']} KU")

    if not args.dry_run:
        await print_summary()


if __name__ == "__main__":
    asyncio.run(main())
