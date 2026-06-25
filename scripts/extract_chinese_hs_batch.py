#!/usr/bin/env python3
"""
高中语文 KU 批量提取 + 入库（三轨13类体系）。
沿用初中成熟方案（CHUNK=3000/去重/归类规范），调整为高考体系。

用法：
  DATABASE_URL=... DEEPSEEK_API_KEY=... \\
  .venv/bin/python scripts/extract_chinese_hs_batch.py [--books BXS,BXX,...] [--dry-run]

  --books  逗号分隔后缀（BXS/BXX/SBXS/SBXM/SBXX）；默认全部5册
  --dry-run 不入库
  --limit N 每本只跑前N单元（调试）

跳过单元（整本书阅读+词语积累）：
  必修上 第五单元（乡土中国）/ 第八单元（词语积累）
  必修下 第七单元（红楼梦）
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
CHUNK          = 2_000  # 本地模型输出上限较小，缩小chunk防截断
FAILED_CHUNKS: list[str] = []  # 失败chunk记录，末尾报告

# provider 配置（由 --provider 覆盖）
_PROVIDER    = "deepseek"   # 默认，main()会修改
_OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434/v1")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

CATALOG = [
    {"tb_id": "TONGBIAN-G10-CHINESE-BXS",  "filename": "H_语文_普通高中教科书·语文必修上册.pdf",      "title": "统编版高中语文必修上册"},
    {"tb_id": "TONGBIAN-G10-CHINESE-BXX",  "filename": "H_语文_普通高中教科书·语文必修下册.pdf",      "title": "统编版高中语文必修下册"},
    {"tb_id": "TONGBIAN-G11-CHINESE-SBXS", "filename": "H_语文_普通高中教科书·语文选择性必修上册.pdf", "title": "统编版高中语文选择性必修上册"},
    {"tb_id": "TONGBIAN-G11-CHINESE-SBXM", "filename": "H_语文_普通高中教科书·语文选择性必修中册.pdf", "title": "统编版高中语文选择性必修中册"},
    {"tb_id": "TONGBIAN-G12-CHINESE-SBXX", "filename": "H_语文_普通高中教科书·语文选择性必修下册.pdf", "title": "统编版高中语文选择性必修下册"},
]

# 各册需要跳过的单元（整本书阅读 + 词语积累不抽KU）
SKIP_UNITS: dict[str, set[str]] = {
    "TONGBIAN-G10-CHINESE-BXS": {"第五单元", "第八单元"},  # 乡土中国 + 词语积累
    "TONGBIAN-G10-CHINESE-BXX": {"第七单元"},              # 红楼梦
}

# 各册预期必须有的ku_type（用于异常检测）
BOOK_EXPECTED_TYPES: dict[str, list[str]] = {
    "TONGBIAN-G10-CHINESE-BXS":  ["wenyan_word", "wenyan_syntax", "mingpian", "shici_jianshang", "xiezuo"],
    "TONGBIAN-G10-CHINESE-BXX":  ["wenyan_word", "wenyan_syntax", "mingpian", "xiaoshuo_yuedu", "xinxi_yuedu", "xiezuo"],
    "TONGBIAN-G11-CHINESE-SBXS": ["wenyan_word", "wenyan_syntax", "mingpian", "xinxi_yuedu", "xiezuo"],
    "TONGBIAN-G11-CHINESE-SBXM": ["wenyan_word", "wenyan_syntax", "xinxi_yuedu", "xiezuo"],
    "TONGBIAN-G12-CHINESE-SBXX": ["wenyan_word", "wenyan_syntax", "mingpian", "shici_jianshang", "xiezuo"],
}

# ── 高中语文 KU 类型（三轨13类）─────────────────────────────────────────────

VALID_KU_TYPES = {
    # 轨一·积累
    "wenyan_word", "wenyan_syntax", "mingpian", "chengyu", "wenhua_changshi",
    # 轨二·鉴赏
    "xinxi_yuedu", "xiaoshuo_yuedu", "sanwen_yuedu", "wenyan_yuedu", "shici_jianshang",
    # 轨三·表达
    "xiezuo", "kouyu_jiaoji", "goutong_chushi",
}

TRACK_MAP = {
    "wenyan_word": "积累", "wenyan_syntax": "积累", "mingpian": "积累",
    "chengyu": "积累", "wenhua_changshi": "积累",
    "xinxi_yuedu": "鉴赏", "xiaoshuo_yuedu": "鉴赏", "sanwen_yuedu": "鉴赏",
    "wenyan_yuedu": "鉴赏", "shici_jianshang": "鉴赏",
    "xiezuo": "表达", "kouyu_jiaoji": "表达", "goutong_chushi": "表达",
}

# ── LLM System Prompt（高中版·AII知识本体002框架·含3修复）─────────────────────

LLM_SYSTEM = """你是AII知识本体002框架的KU提取专家，当前处理【高中语文·统编版】。

▌KU = "可迁移知识的替身（surrogate）"
  不是某篇课文的论据，是学生未来遇到任何同类文本时会用到的知识。

▌三类knowledge_kind（必须标注）:
  declarative  事实性know-what：文言词义/名句/文化常识/成语
  procedural   程序性know-how：阅读方法/写作步骤
  explanatory  解释性know-why：机制/规律/审美原理

▌★know_why 诚实原则（核心，最重要）:

  判断标准：know_why只回答"为什么这样做有效/成立"（机制/认知规律）
  不是"这有什么用"（用途/活动目标）

  填真机制的示例：
    ✅ "情景交融比直抒胸臆更有感染力——景物是情感的客观对应物，
       读者通过感官体验自然领悟情感而非被告知，符合审美参与感原理"
    ✅ "对比使差异更显著，读者在反差中自动判断优劣，符合认知对比效应"

  以下情况诚实填"无深层机制(操作性知识)":
    × "高考常考X"（用途）× "促进合作""激发动力"（活动理由）
    × "这样能更好地理解X"（同义复述）× "找到意象才能分析主题"（步骤合理性）

  ⚠️ 预期填充率70-80%，不是100%——积累轨填null，操作性方法填"无深层机制(操作性知识)"
  严禁：随手编一个看似合理的机制！

▌surrogate原则（鉴赏/表达类ku的name必须是知识替身）:
  ❌ "《喜看稻菽千重浪》·通讯报道角度"（课文论据）
  ✅ "通讯报道阅读法"（可迁移知识），课文进example
  规则：鉴赏/写作类ku的name中不出现《》书名号！

▌合并原则（强化）:
  同一方法不同措辞 → 合并为一个ku：
  ❌ "小说主题分析法"+"小说主题提炼法"+"小说主题归纳法"
  ✅ 只保留"小说主题分析法"，三篇课文全进example
  ❌ "小说心理描写分析法"+"小说心理描写赏析法"（步骤相同）
  ✅ 合并为一个，取最准确的名字
  判断：核心操作步骤基本相同 → 合并；真正不同侧重 → 可分开

▌高中不抽：字音字形/病句辨析/标点/词语运用
  整本书阅读（乡土中国/红楼梦）→ 返回{"unit":"整本书阅读","kus":[]}，不抽KU

▌三轨13类ku_type:
  积累：wenyan_word/wenyan_syntax/mingpian/chengyu/wenhua_changshi
  鉴赏：xinxi_yuedu/xiaoshuo_yuedu/sanwen_yuedu/wenyan_yuedu/shici_jianshang
  表达：xiezuo/kouyu_jiaoji/goutong_chushi

  wenyan_word: 每篇文言文≥10条（格式：词·义项·例句）
  wenyan_syntax: 每篇文言文≥3条（判断/省略/倒装/被动/固定结构）
  mingpian: 64篇必背，逐句单独一条
  chengyu: ★必须抽尽！高中课文成语很多，每篇课文仔细找
  shici_jianshang: 仅针对具体诗词，name格式"鉴赏方法名"（不含《》）
  xiezuo: 每单元写作板块必须有！

▌鉴赏+表达类KU的字段:
  name:           ≤20字，纯知识名称，无《》
  ku_type:        类型
  knowledge_kind: "procedural"/"explanatory"
  know_what:      ≤60字：这个方法是什么
  know_how:       ≤120字：操作步骤（1.找… 2.分析… 3.总结…）
  know_why:       ≤120字：深层机制（或"无深层机制(操作性知识)"）
  example:        课文实例"《篇名》(关键细节)"，多个用"；"分隔
  source_text:    第X单元·文体
  difficulty:     0.1-0.9
  prerequisites:  前置ku名列表（≤3个）
  extra:          null

▌积累类KU的字段:
  name:           词/句/概念本身（≤30字）
  ku_type:        类型
  knowledge_kind: "declarative"
  know_what:      ≤80字：释义/全文
  know_how:       null（文言词可填"考点：辨别活用/通假"）
  know_why:       null
  example:        null
  extra:          wenyan_word时填{词性,是否通假,是否古今异义,是否词类活用,活用类型,义项,例句}，其余null

输出纯JSON（无markdown代码块）：
{
  "unit": "单元名",
  "kus": [
    {
      "id": "ku-001",
      "name": "通讯报道阅读法",
      "ku_type": "xinxi_yuedu",
      "knowledge_kind": "procedural",
      "know_what": "以真实事件为材料，通过典型事件和细节展现人物精神品质的新闻文体阅读方法",
      "know_how": "1.找典型事件切入点；2.识别细节描写（动作/语言/神态）；3.分析细节如何支撑中心论点；4.警惕高考设错：偷换概念/以偏概全",
      "know_why": "典型事件+细节使读者自行推导人物品质——符合'展示而非讲述'原则，具体性增强可信度，情景再现让读者产生共鸣",
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
    """识别高中语文单元边界（无名著导读，但有整本书阅读/词语积累单元）。"""
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
            intro = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)), None
            )
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式B：第一行="第X单元NNN"（单元+页码粘连）
        m2 = re.match(r"^第([一二三四五六七八九十]+)单元\d+$", lines[0])
        if m2:
            unit_ch = m2.group(1)
            intro = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)
                 and "语文" not in l[:4] and "必修" not in l[:4] and "选择性" not in l[:5]),
                None,
            )
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式C：第一行="第X单元 活动·探究" 等（含空格+主题词）
        mc = re.match(r"^第([一二三四五六七八九十]+)单元[\s　]+\S", lines[0])
        if mc:
            unit_ch = mc.group(1)
            intro = next((l for l in lines[1:] if len(l) > 5 and not re.match(r"^\d+$", l)), None)
            if intro:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 兜底：页面<600字 且含"第X单元" 且开头无两位页码
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

def _call_llm(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str, tb_id: str) -> dict:
    is_wenyan = any(kw in text_chunk[:400] for kw in
                    ["之乎者也", "焉", "乃", "余", "吾", "曰", "矣", "哉", "欤"])
    if is_wenyan:
        focus = (
            "文言文重点(002框架)："
            "wenyan_word每篇≥10条（知识性质declarative，知道义项+例句，extra填满）；"
            "wenyan_syntax每篇≥3条（判断/省略/倒装/被动/固定结构，不漏）；"
            "mingpian逐句单独一条；chengyu尽量抽尽；"
            "wenyan_yuedu整体阅读法1条（procedural，需填know_why）。"
        )
    elif any(kw in text_chunk[:300] for kw in ["论点", "论据", "逻辑", "议论", "新闻", "通讯"]):
        focus = (
            "信息类文本(002框架)："
            "xinxi_yuedu用通用方法名（'通讯报道阅读法'不含《》），课文进example；"
            "must填know_why（真机制不是用途）；"
            "写作板块必须有xiezuo；chengyu尽量抽尽。"
        )
    else:
        focus = (
            "002框架提醒：鉴赏/写作类ku的name不含《》，课文进example；"
            "know_why填真机制（70-80%填充率，无机制填'无深层机制(操作性知识)'）；"
            "同方法不同措辞合并为一个ku；写作板块必须有xiezuo；成语尽量抽尽。"
        )

    user = (
        f"【高中语文·{tb_id}·002框架】{unit_name}{part_hint}（{len(text_chunk)}字）：\n\n"
        f"{text_chunk}\n\n"
        f"{focus}"
    )
    if _PROVIDER == "ollama":
        resp = client.post(
            f"{_OLLAMA_BASE}/chat/completions",
            json={
                "model": _OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 6144},
            },
            timeout=300,  # 本地模型较慢
        )
    else:
        resp = client.post(
            "https://api.deepseek.com/chat/completions",
            json={
                "model": "deepseek-v4-flash",
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
    msg = resp.json()["choices"][0]["message"]
    raw = (msg.get("content") or "").strip()
    # thinking 模型（qwen3.5/deepseek-v4）：content 为空时从 reasoning 字段取 JSON
    if not raw:
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if reasoning:
            m2 = re.search(r"\{.*\}", reasoning, re.DOTALL)
            raw = m2.group() if m2 else ""
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"无JSON（{len(raw)}字）：{raw[:120]}")


def llm_extract(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str, tb_id: str) -> list[dict]:
    # 指数退避重试3次（1s/2s/4s）
    for attempt in range(3):
        try:
            data = _call_llm(client, unit_name, text_chunk, part_hint, tb_id)
            return data.get("kus", [])
        except Exception as e:
            wait = 2 ** attempt
            print(f"    [失败 {attempt+1}/3, 等{wait}s] {e}", flush=True)
            if attempt < 2:
                time.sleep(wait)

    # 减半重试
    half = len(text_chunk) // 2
    print(f"    [减半] {len(text_chunk)}→{half}+{len(text_chunk)-half}", flush=True)
    result: list[dict] = []
    for si, sub in enumerate([text_chunk[:half], text_chunk[half:]]):
        recovered = False
        for attempt in range(2):
            try:
                d = _call_llm(client, unit_name, sub, f"{part_hint}(半{si+1})", tb_id)
                result.extend(d.get("kus", []))
                recovered = True
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"    [减半失败 sub{si+1} {attempt+1}/2, 等{wait}s] {e}", flush=True)
                if attempt < 1:
                    time.sleep(wait)
        if not recovered:
            label = f"{tb_id}:{unit_name}{part_hint}(半{si+1})"
            FAILED_CHUNKS.append(label)
            print(f"    ⚠️  失败已记录: {label}", flush=True)
    return result


# ── 主抽取循环 ────────────────────────────────────────────────────────────────


def extract_all_kus(
    client: httpx.Client,
    units: list[tuple[str, str]],
    tb_id: str,
    skip_units: set[str],
    limit: int | None = None,
) -> list[dict]:
    all_kus: list[dict] = []
    units_to_run = units[:limit] if limit else units

    for unit_name, unit_text in units_to_run:
        if not unit_text.strip():
            continue
        if unit_name in skip_units:
            print(f"  [跳过] {unit_name}（整本书阅读/词语积累）", flush=True)
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
            kus = llm_extract(client, unit_name, part, hint, tb_id)
            for ku in kus:
                ku["_unit"] = unit_name
                kt = ku.get("ku_type", "")
                if kt not in VALID_KU_TYPES:
                    print(f"    ⚠️  未知类型 '{kt}'，归 wenhua_changshi", flush=True)
                    ku["ku_type"] = "wenhua_changshi"
                    kt = "wenhua_changshi"
                if not ku.get("track"):
                    ku["track"] = TRACK_MAP.get(kt, "积累")
            all_kus.extend(kus)
            print(f"    → {len(kus)} KU 抽出", flush=True)

    return all_kus


def dedup_kus(kus: list[dict]) -> list[dict]:
    """按name去重并合并example（surrogate原则：同名知识只保留一个）。"""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for ku in kus:
        name = ku.get("name", "").strip()
        if not name:
            continue
        if name not in merged:
            merged[name] = ku.copy()
            order.append(name)
        else:
            # 合并example
            existing = merged[name].get("example") or ""
            new_ex = ku.get("example") or ""
            if new_ex and new_ex not in existing:
                merged[name]["example"] = (existing + "；" + new_ex).strip("；")
            # 如果原来know_why是"无深层机制"但新的有真机制，替换
            old_why = merged[name].get("know_why") or ""
            new_why = ku.get("know_why") or ""
            if old_why in ("", "无深层机制(操作性知识)") and new_why not in ("", "无深层机制(操作性知识)"):
                merged[name]["know_why"] = new_why
    return [merged[n] for n in order]


# ── 校验 ─────────────────────────────────────────────────────────────────────

def anomaly_check(tb_id: str, kus: list[dict]) -> bool:
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    total = len(kus)

    if total == 0:
        print(f"  ⚠️  {tb_id}: 0 KU，停止", flush=True)
        return False

    if total >= 10:
        max_ratio = max(type_cnt.values()) / total
        if max_ratio > 0.80:
            dom = max(type_cnt, key=type_cnt.get)
            print(f"  ⚠️  {tb_id}: {dom} 占 {max_ratio:.0%}，分类异常，停止", flush=True)
            return False

    tracks = Counter(TRACK_MAP.get(ku.get("ku_type", ""), "") for ku in kus)
    for tr in ("积累", "鉴赏", "表达"):
        if tracks.get(tr, 0) == 0:
            print(f"  ⚠️  {tb_id}: 轨·{tr}=0，停止", flush=True)
            return False

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
    ku_type = ku.get("ku_type", "wenhua_changshi")

    # 002框架字段打包进description
    desc_parts: list[str] = []
    kkind = ku.get("knowledge_kind") or ""
    if kkind:
        desc_parts.append(f"[{kkind}]")
    if ku.get("know_what"):
        desc_parts.append(f"know-what: {ku['know_what']}")
    if ku.get("know_how"):
        desc_parts.append(f"know-how: {ku['know_how']}")
    know_why = (ku.get("know_why") or "").strip()
    if know_why:
        desc_parts.append(f"know-why: {know_why}")
    if ku.get("example"):
        desc_parts.append(f"实例: {ku['example']}")
    # 兼容旧core字段
    if not desc_parts and ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("source_text"):
        desc_parts.append(f"来源: {ku['source_text']}")
    if ku.get("track"):
        desc_parts.append(f"轨道: {ku['track']}")
    if isinstance(ku.get("extra"), dict) and ku_type == "wenyan_word":
        ex = ku["extra"]
        parts_ex: list[str] = []
        if ex.get("词性"):       parts_ex.append(f"词性:{ex['词性']}")
        if ex.get("是否通假"):   parts_ex.append("通假字")
        if ex.get("是否古今异义"): parts_ex.append("古今异义")
        if ex.get("是否词类活用") and ex.get("活用类型"):
            parts_ex.append(f"词类活用:{ex['活用类型']}")
        if ex.get("义项"):       parts_ex.append(f"义项:{ex['义项']}")
        if ex.get("例句"):       parts_ex.append(f"例句:{ex['例句']}")
        if parts_ex:
            desc_parts.append(f"[文言]:{'；'.join(parts_ex)}")

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


_AUTO_CLUSTER_CN = {
    "wenyan_word": "文言词语", "wenyan_syntax": "文言句式", "mingpian": "名篇名句",
    "chengyu": "成语典故", "wenhua_changshi": "文学文化常识",
    "xinxi_yuedu": "信息类阅读方法", "xiaoshuo_yuedu": "小说阅读方法",
    "sanwen_yuedu": "散文阅读方法", "wenyan_yuedu": "文言文阅读方法",
    "shici_jianshang": "诗词鉴赏方法",
    "xiezuo": "写作方法", "kouyu_jiaoji": "口语交际方法", "goutong_chushi": "沟通处世方法",
}
_UNIT_SPECIFIC = {"wenyan_word", "wenyan_syntax", "mingpian"}  # 积累轨按单元分簇


async def store_kus(conn: asyncpg.Connection, tb_id: str, kus: list[dict]) -> int:
    kc_cache: dict[str, str] = {}
    order = [1]

    async def get_cluster(unit_name: str, ku_type: str) -> str:
        type_cn = _AUTO_CLUSTER_CN.get(ku_type, ku_type)
        # 积累轨按"第X单元·类型"分簇，鉴赏/表达按类型跨单元分簇（surrogate原则）
        kc_name = f"{unit_name}·{type_cn}" if ku_type in _UNIT_SPECIFIC else type_cn
        if kc_name not in kc_cache:
            kc_cache[kc_name] = await upsert_cluster(conn, tb_id, kc_name, order[0])
            order[0] += 1
        return kc_cache[kc_name]

    for ku in kus:
        cluster_id = await get_cluster(ku.get("_unit", "全册"), ku.get("ku_type", "wenhua_changshi"))
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
    skip  = SKIP_UNITS.get(tb_id, set())

    if not pdf.exists():
        print(f"\n[跳过] {tb_id}: PDF 不存在", flush=True)
        return {"tb_id": tb_id, "ku_count": 0, "skipped": True}

    print(f"\n{'='*60}", flush=True)
    print(f"开始: {book['title']} ({tb_id})", flush=True)
    if skip:
        print(f"  跳过单元: {skip}", flush=True)

    pages = extract_page_texts(pdf)
    units = split_into_units(pages)
    print(f"识别 {len(units)} 个单元: {[u[0] for u in units]}", flush=True)

    kus = extract_all_kus(client, units, tb_id, skip_units=skip, limit=limit)
    kus = dedup_kus(kus)

    type_cnt  = Counter(ku.get("ku_type") for ku in kus)
    track_cnt = Counter(ku.get("track") for ku in kus)
    kind_cnt  = Counter(ku.get("knowledge_kind") for ku in kus)

    # know_why 填充率统计（鉴赏+表达类）
    SURROGATE_TYPES = {
        "xinxi_yuedu", "xiaoshuo_yuedu", "sanwen_yuedu", "wenyan_yuedu",
        "shici_jianshang", "xiezuo", "kouyu_jiaoji", "goutong_chushi",
    }
    surr = [ku for ku in kus if ku.get("ku_type") in SURROGATE_TYPES]
    why_real    = sum(1 for k in surr if k.get("know_why") and k.get("know_why") not in ("无深层机制(操作性知识)", "why待补"))
    why_oper    = sum(1 for k in surr if k.get("know_why") == "无深层机制(操作性知识)")
    why_missing = sum(1 for k in surr if not k.get("know_why"))
    surr_n         = max(len(surr), 1)
    real_rate      = why_real * 100 // surr_n   # 目标70-80%

    print(f"\n  ── {tb_id} 分布 ──", flush=True)
    print(f"  总计: {len(kus)} KU  |  三轨: {dict(track_cnt)}", flush=True)
    print(f"  knowledge_kind: {dict(kind_cnt)}", flush=True)
    print(f"  know_why[鉴赏+表达{len(surr)}条]: 真机制{why_real}({real_rate}%) | 诚实无机制{why_oper} | 缺失{why_missing}", flush=True)
    target_ok = "✅" if 60 <= real_rate <= 90 else "⚠️"
    print(f"  {target_ok} 真机制率{real_rate}%（目标60-90%）", flush=True)
    for t, c in sorted(type_cnt.items(), key=lambda x: -x[1]):
        flag = " ←★" if t in ("wenyan_syntax", "mingpian", "xinxi_yuedu", "shici_jianshang") else ""
        print(f"    {t:25s}: {c}{flag}", flush=True)

    # 每类样本1条（002字段）
    print(f"\n  ── 样本 ──", flush=True)
    shown: set = set()
    for ku in kus:
        t = ku.get("ku_type")
        if t not in shown:
            shown.add(t)
            why_preview = (ku.get("know_why") or "")[:50]
            what_preview = (ku.get("know_what") or ku.get("core") or "")[:50]
            print(f"  [{t}/{ku.get('knowledge_kind','?')}] {ku.get('name')} | {what_preview}", flush=True)
            if why_preview:
                print(f"    → why: {why_preview}", flush=True)

    if dry_run:
        print(f"\n  [dry-run] 跳过入库", flush=True)
        return {"tb_id": tb_id, "ku_count": len(kus), "type_cnt": dict(type_cnt)}

    if not anomaly_check(tb_id, kus):
        print(f"  ⚠️  异常检测不过，{tb_id} 不入库", flush=True)
        return {"tb_id": tb_id, "ku_count": 0, "anomaly": True}

    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        count = await store_kus(conn, tb_id, kus)
        print(f"\n  ✅ {tb_id} 入库 {count} KU", flush=True)
    finally:
        await conn.close()

    return {"tb_id": tb_id, "ku_count": len(kus), "type_cnt": dict(type_cnt)}


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
            WHERE t.subject = 'chinese' AND t.grade IN ('G10','G11','G12')
            GROUP BY t.id, t.grade, t.book_name
            ORDER BY t.grade, t.id
        """)
        print("\n\n══ 高中语文 KU 全局汇总 ══")
        total = 0
        for r in rows:
            print(f"  {r['id']:35s}  {r['ku_count']:4d} KU  {r['type_count']} 类型  {r['book_name']}")
            total += r["ku_count"]
        print(f"\n  高中语文合计: {total} KU")

        type_rows = await conn.fetch("""
            SELECT ku.ku_type, COUNT(*) AS n
            FROM knowledge_units ku
            JOIN textbooks t ON t.id = ku.textbook_id
            WHERE t.subject = 'chinese' AND t.grade IN ('G10','G11','G12')
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
    suffix = tb_id.split("-")[-1]
    return any(f == suffix or f == tb_id for f in book_filter)


async def main() -> None:
    global _PROVIDER, CHUNK
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", default="", help="逗号分隔后缀（BXS/BXX/SBXS/SBXM/SBXX）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", default="deepseek", choices=["deepseek", "ollama"],
                        help="LLM后端（deepseek/ollama，默认deepseek）")
    parser.add_argument("--model", default="", help="本地模型名（默认qwen3.5:9b）")
    parser.add_argument("--chunk", type=int, default=0, help="chunk大小（默认deepseek=3000,ollama=2000）")
    args = parser.parse_args()

    _PROVIDER = args.provider
    if args.model:
        global _OLLAMA_MODEL
        _OLLAMA_MODEL = args.model
    if args.chunk:
        CHUNK = args.chunk

    if _PROVIDER == "deepseek":
        if not DS_KEY:
            sys.exit("需要 DEEPSEEK_API_KEY 环境变量")
        headers = {"Authorization": f"Bearer {DS_KEY}"}
        if not args.chunk:
            CHUNK = 3_000
    else:
        headers = {}
        print(f"provider=ollama  model={_OLLAMA_MODEL}  base={_OLLAMA_BASE}", flush=True)

    book_filter = [b.strip() for b in args.books.split(",") if b.strip()]
    books = [b for b in CATALOG if _match(b["tb_id"], book_filter)]
    if not books:
        avail = [b["tb_id"].split("-")[-1] for b in CATALOG]
        sys.exit(f"无匹配教材。可用后缀: {avail}")

    print(f"计划处理 {len(books)} 本: {[b['tb_id'] for b in books]}", flush=True)
    print(f"CHUNK={CHUNK} | {'dry-run' if args.dry_run else '入库模式'}", flush=True)

    results: list[dict] = []
    with httpx.Client(headers=headers, timeout=300) as client:
        for book in books:
            r = await process_book(book, client, args.dry_run, args.limit)
            results.append(r)

    print("\n\n══ 本次运行汇总 ══")
    for r in results:
        if r.get("skipped"):
            print(f"  {r['tb_id']:35s}  [跳过]")
        elif r.get("anomaly"):
            print(f"  {r['tb_id']:35s}  [异常未入库]")
        else:
            print(f"  {r['tb_id']:35s}  {r['ku_count']} KU")

    if FAILED_CHUNKS:
        print(f"\n⚠️  永久失败chunk（数据丢失 {len(FAILED_CHUNKS)} 块）:")
        for c in FAILED_CHUNKS:
            print(f"  - {c}")
    else:
        print("\n✅ 所有chunk均成功处理（无数据丢失）")

    if not args.dry_run:
        await print_summary()


if __name__ == "__main__":
    asyncio.run(main())
