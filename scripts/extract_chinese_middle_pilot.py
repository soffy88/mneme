#!/usr/bin/env python3
"""
初中语文 KU 试抽（pilot）：只抽一本，导出 Markdown 供审阅，不入库。

用法：
  DEEPSEEK_API_KEY=... .venv/bin/python scripts/extract_chinese_middle_pilot.py \
      [--book TONGBIAN-G9-CHINESE-S] \
      [--limit N]   # 只跑前 N 个单元（调试用）

输出：scripts/chinese_g9_pilot_review.md
"""
from __future__ import annotations

import argparse
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
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
DS_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
CHUNK   = 5_000  # 每次 LLM 最大字符

# 只抽这一本做试验
TARGET_BOOK = {
    "tb_id":    "TONGBIAN-G9-CHINESE-S",
    "filename": "M_语文_义务教育教科书·语文九年级上册.pdf",
    "title":    "统编版语文九年级上册",
}

# ── 初中语文 KU 类型（三轨19类）──────────────────────────────────────────────

VALID_KU_TYPES = {
    # 轨一·积累（9类）
    "wenyan_word",      # 文言词语（实词/虚词/通假/古今异义/活用）
    "wenyan_syntax",    # 文言句式
    "mingju",           # 名句默写（课标背诵篇目）
    "chengyu",          # 成语
    "zixing_ziyin",     # 字音字形（★初中强化：形声字/形近字/多音字）
    "cizu_yunyong",     # 词语运用（近义词辨析/关联词）★初中新增
    "wenhua_changshi",  # 文学文化常识（作家作品/古代文化常识）
    "bingju",           # 病句辨析（六种类型）★初中新增
    "biaodian",         # 标点符号 ★初中新增
    # 轨二·鉴赏（7类）
    "jixuwen_yuedu",    # 记叙文阅读（人物/情节/标题/句子含义/情感/手法）★初中主力
    "shuomingwen_yuedu",# 说明文阅读（说明方法/顺序/语言准确性）★初中强化
    "yilunwen_yuedu",   # 议论文阅读（论点/论据/论证方法）
    "sanwen_yuedu",     # 散文阅读
    "wenyan_yuedu",     # 文言文整体阅读（断句/翻译/内容理解/人物）
    "shici_jianshang",  # 古诗词鉴赏（意象/情感/手法/炼字）
    "mingzhu_yuedu",    # 名著阅读（作者/主要内容/人物形象/主题/经典情节）★初中必考
    # 轨三·表达（3类）
    "xiezuo",           # 写作（初中以记叙文为主）
    "kouyu_jiaoji",     # 口语交际（语言得体/图文转换/拟写宣传语）
    "goutong_chushi",   # 沟通处世
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

# ── LLM System Prompt（初中版）──────────────────────────────────────────────

LLM_SYSTEM = """你是中国K12语文教材知识点（KU）提取专家，当前处理【初中语文（义务教育）】教材。

▌核心原则：
  语文KU≠概念总结。KU是"从课文提取的最小可独立练习/背诵/应用的语言材料或方法"。
  初中语文中考重考：字音字形、名句默写、病句辨析、文言文逐词、记叙文/说明文阅读方法、名著。

▌三轨19类 ku_type（必须精确选一，不得使用列表外的类型）：

——轨一·积累型（走FSRS背诵/选择题练习）——
  wenyan_word     文言词语：一个具体文言词的义项（含词性/是否通假/古今异义/词类活用）
                  ⚠️ 格式："词·义项" 如"属·劝酒义"，禁止"课文名·句子"格式
                  ⚠️ 每个有独特义项/用法的词单独一个KU，不合并多词
                  初中重点：之/其/而/于/以/乃等虚词，以及课文特色实词
  wenyan_syntax   文言句式：一种典型句式+例句（判断句/省略句/倒装句/被动句）
  mingju          名句默写：课程标准要求背诵的完整句子或段落，注明出处
                  ⚠️ 初中叫"名句默写"（不是"名篇"），每句/每联单独一条
                  示例：name="先天下之忧而忧，后天下之乐而乐（岳阳楼记）"
  chengyu         成语：含义+出处（初中教材出现的成语）
  zixing_ziyin    字音字形：易错字的读音/写法，每字单独一条
                  ⚠️ 初中强化：形声字（如"绯红"fēi）、形近字（如"燥/噪/躁"）、
                  多音字（如"模"mó/mú）、课文生字词
                  ⚠️ 要全！字音字形是中考基础题的主要来源，从课文生字词逐个抽
  cizu_yunyong    词语运用：近义词辨析 或 关联词的用法
                  示例："启示"vs"启发"的辨析；"不但…而且…"的用法
  wenhua_changshi 文学文化常识：作家作品（朝代/国籍/代表作/文学地位）或
                  古代文化常识（节日/纪年/职官/礼俗），每个知识点一条
  bingju          病句辨析：中考六种类型之一的典型例句+修改方法
                  六类：成分残缺/搭配不当/语序不当/结构混乱/表意不明/不合逻辑
                  ⚠️ 从课文或单元练习中的病句例子提取，有明确对错
  biaodian        标点符号：一个标点的具体用法规则+典型例句
                  示例：引号的四种用法之一："表示特殊含义"的用法

——轨二·鉴赏型（走苏格拉底引导）——
  jixuwen_yuedu   记叙文阅读方法：人物描写方法/情节结构/标题作用/句子含义/
                  情感主旨/表现手法（初中语文最重要的文体阅读，每篇提取1-3个方法KU）
  shuomingwen_yuedu 说明文阅读方法：说明方法（举例/列数字/分类别/打比方/作比较等）
                  /说明顺序/说明语言准确性（★初中重点，高中少考，这里要强化）
  yilunwen_yuedu  议论文阅读方法：论点提炼/论据类型/论证方法（举例/道理/对比/比喻论证）
  sanwen_yuedu    散文阅读方法：写景散文/叙事散文/抒情散文的语言赏析/情感把握/结构手法
  wenyan_yuedu    文言文整体阅读方法：断句规律/翻译技巧（留删换调补）/
                  内容理解/人物形象分析/写作手法
  shici_jianshang 古诗词鉴赏：意象含义/情感主旨/表现手法/炼字炼句
                  （每首诗提取1-3个鉴赏KU，包含现代诗和古诗词）
  mingzhu_yuedu   名著阅读：每部名著一个KU，包含：
                  作者+时代/背景/主要内容/主要人物及其形象/主题思想/经典情节
                  ⚠️ 初中中考必考，必须从"名著导读"单元提取！
                  ⚠️ 九上常见名著：《艾青诗选》《水浒传》，每部单独一条

——轨三·表达型（走写作/口语陪练）——
  xiezuo          写作方法：记叙文/说明文/议论文/应用文的某一具体写法
                  （初中以记叙文为主：开头结尾/人物描写/以小见大/欲扬先抑等）
  kouyu_jiaoji    口语交际：语言得体/图文转换/拟写宣传语/演讲/辩论技能
  goutong_chushi  沟通处世：得体表达/劝说策略/换位思考的能力（较少，有则抽）

▌每个 KU 的字段：
  name           KU名称（≤30字，积累型含词/句本身，鉴赏型含课文名+方法关键词）
  ku_type        上面19类之一
  track          "积累"/"鉴赏"/"表达"
  core           核心内容（≤120字）：
                 - wenyan_word：词性+义项+课文原句例证
                 - mingju：完整原文+出处（课文名+作者）
                 - zixing_ziyin：字+正确读音/写法+辨析要点
                 - bingju：病句例句+病因分析+改正方法
                 - biaodian：标点用法规则+例句
                 - 鉴赏型：方法要点（学什么、怎么用）
                 - mingzhu_yuedu：作者/时代/主要内容/核心人物/主题/经典情节
                 - 表达型：能力要点
  source_text    出处（如"《岳阳楼记》范仲淹"；名著则"名著导读·《水浒传》"；
                 单元写作板块则"第X单元·写作"）
  difficulty     0.1–0.9（0.1=识记，0.5=需理解，0.9=综合运用）
  prerequisites  前置KU名列表（最多3个，初中阶段通常较少）
  extra          仅当 ku_type=wenyan_word 时填写（其他设为null）：
    {"词性": "动词/名词/虚词/...", "是否通假": false, "是否古今异义": false,
     "是否词类活用": false, "活用类型": null或"名词作动词/...",
     "义项": "该义项简述", "例句": "原文例句（≤20字）"}

▌抽取规则（按文体/板块）：
  1. 文言文课文（《岳阳楼记》《醉翁亭记》等）：
     - wenyan_word：逐词抽（实词全抽，虚词抽该课文特色用法），每篇8-15个
     - wenyan_syntax：每篇1-3个典型句式
     - mingju：每篇背诵名句逐句单独一条
     - wenhua_changshi：作家作品+相关文化常识各1-2条
     - wenyan_yuedu：整体阅读方法1条
  2. 古诗词（《行路难》《酬乐天》等）：
     - shici_jianshang：每首1-3个鉴赏KU
     - mingju：必背名句每句单独一条
     - wenhua_changshi：作家简介+朝代背景1条
  3. 现代文小说（《故乡》《孤独之旅》等）：
     - jixuwen_yuedu：1-3个阅读方法KU
     - zixing_ziyin：课文生字词（每字单独一条，★要全）
     - chengyu：课文中出现的成语
     - wenhua_changshi：作家简介
  4. 说明文（《中国石拱桥》《苏州园林》等）：
     - shuomingwen_yuedu：1-3个说明文阅读方法KU（★说明方法逐类抽）
     - zixing_ziyin：课文生字词
     - cizu_yunyong：课文中的词语运用辨析
  5. 议论文（《敬业与乐业》《不求甚解》等）：
     - yilunwen_yuedu：1-3个议论文阅读方法KU
     - zixing_ziyin：课文生字词
     - wenhua_changshi：作家简介+论点相关知识
  6. 现代诗歌（《沁园春·雪》《我爱这土地》等）：
     - shici_jianshang：每首1-2个鉴赏KU（意象/情感/修辞手法）
     - mingju：名句1-2条
  7. 名著导读板块：
     - mingzhu_yuedu：★每部名著必须抽！内容要全（作者/梗概/人物/主题/情节）
  8. 单元"写作"板块 → xiezuo（每单元必须有）
  9. 单元"口语交际"/"综合性学习" → kouyu_jiaoji 或 goutong_chushi
  10. 病句/标点：从单元练习题或课文注释中提取 bingju/biaodian

▌去重与质量控制：
  - 同一个词的同一义项只抽一次（wenyan_word去重）
  - 同一首诗/篇的同一方法不重复
  - 名著每部只抽一条mingzhu_yuedu（内容要丰富，合并到一条core里）
  - bingju每类病句类型至少一条，不要重复同类型
  - zixing_ziyin：宁多勿少，中考基础题来源

▌数量目标（全册总量参考）：
  wenyan_word 60-100个（文言文为主的册子要多）
  mingju 20-40条
  zixing_ziyin 30-60条（每篇现代文生字词要全）
  jixuwen_yuedu 5-10条
  shuomingwen_yuedu 3-6条
  yilunwen_yuedu 3-6条
  mingzhu_yuedu 2-3条（本册名著数量）
  bingju 3-6条
  其余各类 2-8条

输出纯 JSON（无 markdown 代码块）：
{
  "unit": "单元名称",
  "kus": [
    {
      "id": "ku-001",
      "name": "先忧后乐·名句（岳阳楼记）",
      "ku_type": "mingju",
      "track": "积累",
      "core": "先天下之忧而忧，后天下之乐而乐。出自范仲淹《岳阳楼记》，表达忧国忧民的政治理想。",
      "source_text": "《岳阳楼记》范仲淹",
      "difficulty": 0.2,
      "prerequisites": [],
      "extra": null
    },
    {
      "id": "ku-002",
      "name": "属·劝酒义（醉翁亭记）",
      "ku_type": "wenyan_word",
      "track": "积累",
      "core": "属，动词，劝人饮酒。例：射者中，弈者胜，觥筹交错，起坐而喧哗者，众宾欢也。",
      "source_text": "《醉翁亭记》欧阳修",
      "difficulty": 0.4,
      "prerequisites": [],
      "extra": {"词性":"动词","是否通假":false,"是否古今异义":false,"是否词类活用":false,"活用类型":null,"义项":"劝酒","例句":"射者中，弈者胜"}
    }
  ],
  "kcs": [
    {"id": "kc-001", "name": "《岳阳楼记》文言词语", "logic_reason": "同篇文言词语聚为一KC", "ku_ids": ["ku-001","ku-002"]}
  ]
}
只输出 JSON，不加任何其他文字。"""


# ── PDF 处理（复用高中脚本的逻辑）────────────────────────────────────────────

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
    """识别初中语文单元边界（含名著导读单元）。"""
    CHARS = "一二三四五六七八九十"
    unit_occurrences: dict[str, list[int]] = {}

    for pg in sorted(pages):
        text = pages[pg]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue

        # 模式A：第一行="第X单元"（单独）
        m = re.match(r"^第([一二三四五六七八九十]+)单元$", lines[0])
        if m:
            unit_ch = m.group(1)
            intro_line = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)),
                None,
            )
            if intro_line:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式B：第一行="第X单元NNN"（单元+页码合并）
        m2 = re.match(r"^第([一二三四五六七八九十]+)单元\d+$", lines[0])
        if m2:
            unit_ch = m2.group(1)
            intro_line = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)
                 and "语文" not in l[:4]),
                None,
            )
            if intro_line:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 兜底：整页文字<350字且含"第X单元"
        if len(text) < 350:
            m3 = re.search(r"第([一二三四五六七八九十]+)单元", text)
            if m3:
                unit_ch = m3.group(1)
                if not re.search(r"\d{2,}", text[:50]):
                    unit_occurrences.setdefault(unit_ch, []).append(pg)

    # 第一单元兜底
    if "一" not in unit_occurrences:
        for pg in sorted(pages)[:20]:
            text = pages[pg]
            if len(text) < 400 and not re.search(r"第[二三四五六七八九十]+单元", text):
                if re.search(r"本单元", text):
                    unit_occurrences["一"] = [pg]
                    break

    # 检测"名著导读"单元（初中特有）
    mingzhu_start: int | None = None
    for pg in sorted(pages):
        text = pages[pg]
        if re.search(r"名著导读", text[:100]) and len(text) < 500:
            if mingzhu_start is None:
                mingzhu_start = pg
                break

    if not unit_occurrences:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    # 贪心选取页码单调递增
    all_units = sorted(unit_occurrences.keys(), key=lambda x: CHARS.index(x) if x in CHARS else 99)
    unit_starts: dict[str, int] = {}
    prev_pg = 0
    for uch in all_units:
        valid = [p for p in unit_occurrences[uch] if p > prev_pg]
        if valid:
            unit_starts[uch] = valid[0]
            prev_pg = valid[0]

    if not unit_starts:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    ordered = sorted(unit_starts.items(), key=lambda x: x[1])
    pg_sorted = sorted(pages)
    units: list[tuple[str, str]] = []
    for i, (uch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        # 名著导读夹在这个范围内时，截止到名著导读开始
        if mingzhu_start and start_pg < mingzhu_start < end_pg:
            end_pg = mingzhu_start
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if text.strip():
            units.append((f"第{uch}单元", text))

    # 名著导读作为单独"单元"
    if mingzhu_start:
        text = "\n".join(pages[p] for p in pg_sorted if p >= mingzhu_start)
        if text.strip():
            units.append(("名著导读", text[:CHUNK * 2]))  # 限制名著导读长度避免过长

    return units


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def _call_llm(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str) -> dict:
    user = (
        f"【初中语文·九年级上册】{unit_name}{part_hint} 正文内容（{len(text_chunk)}字符）：\n\n"
        f"{text_chunk}\n\n"
        "请按三轨19类体系提取所有KU。\n"
        "重点：文言词语逐词抽（不少于8个/篇）；字音字形从生字词逐个抽；"
        "名著导读单元必须抽mingzhu_yuedu；说明文必抽shuomingwen_yuedu；"
        "议论文必抽yilunwen_yuedu；记叙文必抽jixuwen_yuedu；"
        "每单元写作板块必抽xiezuo。"
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


def llm_extract(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str = "") -> dict:
    for attempt in range(2):
        try:
            return _call_llm(client, unit_name, text_chunk, part_hint)
        except Exception as e:
            print(f"    [LLM 失败 attempt {attempt+1}] {e}", flush=True)
            time.sleep(3)

    half = len(text_chunk) // 2
    print(f"    [减半重试] {len(text_chunk)}→{half}+{len(text_chunk)-half}", flush=True)
    merged: dict = {"unit": unit_name, "kus": [], "kcs": []}
    kid_offset = 0
    for sub_idx, sub in enumerate([text_chunk[:half], text_chunk[half:]]):
        try:
            d = _call_llm(client, unit_name, sub, f"{part_hint}(减半{sub_idx+1}/2)")
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
            data = llm_extract(client, unit_name, part, hint)
            kus = data.get("kus", [])
            kcs = data.get("kcs", [])

            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            _attach_kcs(kus, kcs)
            for ku in kus:
                ku["_unit"] = unit_name
                kt = ku.get("ku_type", "")
                if kt not in VALID_KU_TYPES:
                    print(f"    ⚠️  未知类型 '{kt}'，归为 wenyan_word", flush=True)
                    ku["ku_type"] = "wenyan_word"
                    kt = "wenyan_word"
                if not ku.get("track"):
                    ku["track"] = TRACK_MAP.get(kt, "积累")
                ku["prerequisites"] = [
                    id_to_name.get(p, p) for p in ku.get("prerequisites", []) if p
                ]
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


# ── Markdown 报告生成 ─────────────────────────────────────────────────────────

def generate_report(kus: list[dict], title: str, out_path: Path) -> None:
    type_cnt: Counter = Counter(ku.get("ku_type") for ku in kus)
    track_cnt: Counter = Counter(ku.get("track") for ku in kus)

    lines: list[str] = []
    lines.append(f"# 初中语文 KU 试抽审阅报告：{title}")
    lines.append("")
    lines.append("## 汇总统计")
    lines.append("")
    lines.append(f"- **总计 KU 数**：{len(kus)}")
    lines.append("")
    lines.append("### 三轨分布")
    lines.append("")
    for tr in ("积累", "鉴赏", "表达"):
        lines.append(f"- 轨·{tr}：{track_cnt.get(tr, 0)} 条")
    lines.append("")
    lines.append("### 各类型分布")
    lines.append("")
    # 按轨道组织
    track_order = [
        ("积累", ["wenyan_word","wenyan_syntax","mingju","chengyu","zixing_ziyin",
                  "cizu_yunyong","wenhua_changshi","bingju","biaodian"]),
        ("鉴赏", ["jixuwen_yuedu","shuomingwen_yuedu","yilunwen_yuedu","sanwen_yuedu",
                  "wenyan_yuedu","shici_jianshang","mingzhu_yuedu"]),
        ("表达", ["xiezuo","kouyu_jiaoji","goutong_chushi"]),
    ]
    for tr_name, types in track_order:
        lines.append(f"**轨一·{tr_name}**" if tr_name == "积累" else f"**轨二·{tr_name}**" if tr_name == "鉴赏" else f"**轨三·{tr_name}**")
        for t in types:
            cnt = type_cnt.get(t, 0)
            flag = " ⚠️ 无" if cnt == 0 else ""
            lines.append(f"  - `{t}`：{cnt} 条{flag}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 详细 KU 列表（按三轨→类型→出处分组）")
    lines.append("")

    # 按轨道→类型→单元分组
    for tr_name, types in track_order:
        has_any = any(type_cnt.get(t, 0) > 0 for t in types)
        if not has_any:
            continue
        lines.append(f"## 轨·{tr_name}")
        lines.append("")

        for ku_type in types:
            type_kus = [k for k in kus if k.get("ku_type") == ku_type]
            if not type_kus:
                continue

            type_label = {
                "wenyan_word": "文言词语",
                "wenyan_syntax": "文言句式",
                "mingju": "名句默写",
                "chengyu": "成语",
                "zixing_ziyin": "字音字形",
                "cizu_yunyong": "词语运用",
                "wenhua_changshi": "文学文化常识",
                "bingju": "病句辨析",
                "biaodian": "标点符号",
                "jixuwen_yuedu": "记叙文阅读",
                "shuomingwen_yuedu": "说明文阅读",
                "yilunwen_yuedu": "议论文阅读",
                "sanwen_yuedu": "散文阅读",
                "wenyan_yuedu": "文言文整体阅读",
                "shici_jianshang": "古诗词鉴赏",
                "mingzhu_yuedu": "名著阅读",
                "xiezuo": "写作",
                "kouyu_jiaoji": "口语交际",
                "goutong_chushi": "沟通处世",
            }.get(ku_type, ku_type)

            lines.append(f"### `{ku_type}` — {type_label}（{len(type_kus)} 条）")
            lines.append("")

            # 按出处分组
            by_source: dict[str, list[dict]] = {}
            for ku in type_kus:
                src = ku.get("source_text") or ku.get("_unit") or "未知"
                by_source.setdefault(src, []).append(ku)

            for src, src_kus in sorted(by_source.items()):
                lines.append(f"#### 出处：{src}")
                lines.append("")
                for ku in src_kus:
                    lines.append(f"**{ku.get('name', '?')}**")
                    lines.append(f"- 难度：{ku.get('difficulty', '?')} | 轨道：{ku.get('track', '?')}")
                    lines.append(f"- 核心：{ku.get('core', '')}")
                    if ku.get("extra") and ku.get("ku_type") == "wenyan_word":
                        ex = ku["extra"]
                        flags = []
                        if ex.get("词性"): flags.append(f"词性:{ex['词性']}")
                        if ex.get("是否通假"): flags.append("通假")
                        if ex.get("是否古今异义"): flags.append("古今异义")
                        if ex.get("是否词类活用"): flags.append(f"活用:{ex.get('活用类型','')}")
                        if flags:
                            lines.append(f"- 文言属性：{' | '.join(flags)}")
                    if ku.get("prerequisites"):
                        lines.append(f"- 前置：{', '.join(ku['prerequisites'])}")
                    lines.append(f"- 所在单元：{ku.get('_unit', '')}")
                    kcs_str = ", ".join(ku.get("_kcs") or [])
                    if kcs_str:
                        lines.append(f"- KC 归属：{kcs_str}")
                    lines.append("")

    lines.append("---")
    lines.append("*by extract_chinese_middle_pilot.py*")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 报告已写出：{out_path}", flush=True)


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", default="TONGBIAN-G9-CHINESE-S",
                        help="教材 tb_id（默认九年级上册）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只抽前 N 个单元（调试）")
    args = parser.parse_args()

    if not DS_KEY:
        sys.exit("缺少 DEEPSEEK_API_KEY 环境变量")

    book = TARGET_BOOK
    if args.book != TARGET_BOOK["tb_id"]:
        print(f"⚠️  本 pilot 脚本只支持 {TARGET_BOOK['tb_id']}，忽略 --book 参数", flush=True)

    pdf_path = PDF_DIR / book["filename"]
    if not pdf_path.exists():
        sys.exit(f"PDF 不存在: {pdf_path}")

    out_path = Path(__file__).parent / "chinese_g9_pilot_review.md"

    print(f"📖 读取 PDF: {pdf_path.name}", flush=True)
    pages = extract_page_texts(pdf_path)
    print(f"   {len(pages)} 页", flush=True)

    units = split_into_units(pages)
    print(f"   识别到 {len(units)} 个单元: {[u[0] for u in units]}", flush=True)

    if args.limit:
        print(f"   --limit {args.limit}，只抽前 {args.limit} 个单元", flush=True)

    with httpx.Client(headers={"Authorization": f"Bearer {DS_KEY}"}, timeout=130) as client:
        kus = extract_all_kus(client, units, limit=args.limit)

    kus = dedup_kus(kus)

    print(f"\n📊 共抽 {len(kus)} 个 KU（去重后）", flush=True)
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    for kt, n in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"   {kt:30s} {n}", flush=True)

    # 校验必有类型
    MUST_HAVE = {
        "mingzhu_yuedu": "名著阅读（名著导读单元必须有）",
        "bingju": "病句辨析（初中特有）",
        "shuomingwen_yuedu": "说明文阅读（九上有说明文单元）",
        "yilunwen_yuedu": "议论文阅读（九上有议论文单元）",
        "jixuwen_yuedu": "记叙文阅读（九上有小说单元）",
        "zixing_ziyin": "字音字形",
        "mingju": "名句默写",
        "wenyan_word": "文言词语",
    }
    missing = [f"{t} ({desc})" for t, desc in MUST_HAVE.items() if type_cnt.get(t, 0) == 0]
    if missing:
        print("\n⚠️  缺少必有类型：", flush=True)
        for m in missing:
            print(f"   - {m}", flush=True)
    else:
        print("\n✅ 所有必有类型均有抽出", flush=True)

    generate_report(kus, book["title"], out_path)
    print(f"\n请审阅：{out_path}", flush=True)


if __name__ == "__main__":
    main()
