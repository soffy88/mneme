#!/usr/bin/env python3
"""
语文 KU 批量提取 + 入库（三轨13类体系）。

用法：
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme \
  DEEPSEEK_API_KEY=... \
  .venv/bin/python scripts/extract_chinese_ku_batch.py [options]

  --books BXS,BXX,...  只跑指定本册 tb_id 后缀（逗号分隔）；默认全部
  --dry-run            只打印，不入库
  --limit N            每本只跑前 N 个单元（调试）

语文 ku_type（三轨13类）：
  轨一·积累：wenyan_word / wenyan_syntax / mingpian / chengyu /
             zixing_ziyin / wenhua_changshi
  轨二·鉴赏：xinxi_yuedu / xiaoshuo_yuedu / sanwen_yuedu /
             wenyan_yuedu / shici_jianshang
  轨三·表达：shumian_biaoda / kouyu_jiaoji / goutong_chushi
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
CHUNK   = 5_000    # 每次 LLM 最大字符；语文wenyan_word输出密集，保守5000

CATALOG = [
    {
        "tb_id":    "TONGBIAN-G10-CHINESE-BXS",
        "filename": "H_语文_普通高中教科书·语文必修上册.pdf",
        "title":    "统编版高中语文必修上册",
    },
    {
        "tb_id":    "TONGBIAN-G10-CHINESE-BXX",
        "filename": "H_语文_普通高中教科书·语文必修下册.pdf",
        "title":    "统编版高中语文必修下册",
    },
    {
        "tb_id":    "TONGBIAN-G11-CHINESE-SBXS",
        "filename": "H_语文_普通高中教科书·语文选择性必修上册.pdf",
        "title":    "统编版高中语文选择性必修上册",
    },
    {
        "tb_id":    "TONGBIAN-G11-CHINESE-SBXM",
        "filename": "H_语文_普通高中教科书·语文选择性必修中册.pdf",
        "title":    "统编版高中语文选择性必修中册",
    },
    {
        "tb_id":    "TONGBIAN-G12-CHINESE-SBXX",
        "filename": "H_语文_普通高中教科书·语文选择性必修下册.pdf",
        "title":    "统编版高中语文选择性必修下册",
    },
    {
        "tb_id":    "TONGBIAN-G7-CHINESE-S",
        "filename": "M_语文_义务教育教科书·语文七年级上册.pdf",
        "title":    "统编版语文七年级上册",
    },
    {
        "tb_id":    "TONGBIAN-G7-CHINESE-X",
        "filename": "M_语文_义务教育教科书·语文七年级下册.pdf",
        "title":    "统编版语文七年级下册",
    },
    {
        "tb_id":    "TONGBIAN-G8-CHINESE-S",
        "filename": "M_语文_义务教育教科书·语文八年级上册.pdf",
        "title":    "统编版语文八年级上册",
    },
    {
        "tb_id":    "TONGBIAN-G8-CHINESE-X",
        "filename": "M_语文_义务教育教科书·语文八年级下册.pdf",
        "title":    "统编版语文八年级下册",
    },
    {
        "tb_id":    "TONGBIAN-G9-CHINESE-S",
        "filename": "M_语文_义务教育教科书·语文九年级上册.pdf",
        "title":    "统编版语文九年级上册",
    },
    {
        "tb_id":    "TONGBIAN-G9-CHINESE-X",
        "filename": "M_语文_义务教育教科书·语文九年级下册.pdf",
        "title":    "统编版语文九年级下册",
    },
]

VALID_KU_TYPES = {
    # 轨一·积累
    "wenyan_word", "wenyan_syntax", "mingpian", "chengyu",
    "zixing_ziyin", "wenhua_changshi",
    # 轨二·鉴赏
    "xinxi_yuedu", "xiaoshuo_yuedu", "sanwen_yuedu",
    "wenyan_yuedu", "shici_jianshang",
    # 轨三·表达
    "shumian_biaoda", "kouyu_jiaoji", "goutong_chushi",
}

TRACK_MAP = {
    "wenyan_word": "积累", "wenyan_syntax": "积累", "mingpian": "积累",
    "chengyu": "积累", "zixing_ziyin": "积累", "wenhua_changshi": "积累",
    "xinxi_yuedu": "鉴赏", "xiaoshuo_yuedu": "鉴赏", "sanwen_yuedu": "鉴赏",
    "wenyan_yuedu": "鉴赏", "shici_jianshang": "鉴赏",
    "shumian_biaoda": "表达", "kouyu_jiaoji": "表达", "goutong_chushi": "表达",
}

# ── LLM Prompt ────────────────────────────────────────────────────────────────

LLM_SYSTEM = """你是中国K12语文教材知识点（KU）提取专家。

▌核心原则：
  语文KU≠概念总结。语文KU是"从课文提取的最小可独立练习/背诵/应用的语言材料或方法"。
  文言词语KU要具体到某个词（如"属"字的动词义"劝饮"），不能笼统写"文言实词"。

▌三轨13类 ku_type（必须精确选一）：

——轨一·积累型（将来走FSRS背诵）——
  wenyan_word     文言词语：一个具体文言词的义项（含词性/是否通假/古今异义/词类活用）
                  示例：KU名="属·劝酒义"（出自《赤壁赋》"举酒属客"），
                  core="属，动词，劝人饮酒。例：举酒属客，诵明月之诗（赤壁赋）"
                  ⚠️ 每个有独特义项/用法的词单独一个KU；不能合并多词为一KU
  wenyan_syntax   文言句式：一种典型句式+例句
                  示例："何为其然也·宾语前置"，core="'何为'即'为何'，宾语'何'前置。"
  mingpian        名篇名句：课程标准要求背诵的完整段落/句子（需标明出处）
                  示例："寄蜉蝣于天地，渺沧海之一粟（苏轼《赤壁赋》）"
  chengyu         成语：含义+出处
  zixing_ziyin    字音字形：易错字的读音/写法（高考常考，非生僻字）
  wenhua_changshi 文化常识：古代称谓/纪年/职官/礼俗/典章制度等一个知识点

——轨二·鉴赏型（将来走苏格拉底引导）——
  xinxi_yuedu     信息类文本阅读方法（论述类/实用类，如通讯/议论文/说明文）
  xiaoshuo_yuedu  小说阅读方法（人物/情节/环境/主题/叙事手法）
  sanwen_yuedu    散文阅读方法（写景/抒情/叙事散文，语言赏析/结构手法）
  wenyan_yuedu    文言文整体阅读方法（断句/翻译/文意理解/整体把握）
  shici_jianshang 古诗词鉴赏（意象/情感/手法/炼字炼句，每首诗可提取1-3个方法KU）

——轨三·表达型（将来走写作/口语陪练）——
  shumian_biaoda  书面表达：议论文/记叙文/应用文的某一具体写作方法
  kouyu_jiaoji    口语交际：倾听/表达/应对/演讲/辩论/访谈的技能点
  goutong_chushi  沟通处世：得体表达/劝说/换位思考/交际语境的能力点

▌每个 KU 的字段：
  name           KU名称（≤30字，对积累型要含词/句本身）
  ku_type        上面13类之一
  track          "积累"/"鉴赏"/"表达"（与ku_type对应）
  core           核心内容（≤100字）：
                 - wenyan_word：词性+义项+课文例句
                 - mingpian：完整原文（可省略标点）+出处
                 - 鉴赏型：方法要点（学什么、怎么用）
                 - 表达型：能力要点
  source_text    出自哪篇课文（如"《赤壁赋》苏轼"；课内单元任务则写"第X单元学习任务"）
  difficulty     0.1–0.9（0.1=识记即可，0.5=需理解运用，0.9=综合鉴赏高阶）
  prerequisites  前置KU名列表（最多4个）
  extra          仅当 ku_type=wenyan_word 时填写（其他类型设为null）：
    {"词性": "动词/名词/虚词/...", "是否通假": false, "是否古今异义": false,
     "是否词类活用": false, "活用类型": "名词作动词/..."或null,
     "义项": "该义项简述", "例句": "原文例句（≤20字）"}

▌KC（知识簇）聚类规则：
  按语文学习逻辑聚类，每 KC 含 3–10 个 KU。
  积累型KC示例："《赤壁赋》文言词语""必修上·名篇名句""古代文化常识（纪年称谓）"
  鉴赏型KC示例："小说阅读核心方法""古诗词意象与情感""信息类文本阅读技法"
  表达型KC示例："议论文写作技法""口语交际技能"

▌抽取原则：
  1. 文言文课文（《劝学》《师说》《赤壁赋》等）：
     重点抽轨一（实词逐词、句式逐类、名句整句、文化常识）+ wenyan_yuedu
     实词：只抽"该课文特别值得关注"的词（有多义/通假/活用），不要所有词
  2. 古诗词：抽 shici_jianshang（意象/情感/炼字手法，每首1-3个）+ mingpian（背诵句）
  3. 现代文小说/散文：抽对应鉴赏型KU（方法1个）+ 字音字形/成语（各1-3个）
  4. 信息类/实用类文本（通讯报道、议论文）：抽 xinxi_yuedu 方法KU
  5. 单元"写作"板块：抽 shumian_biaoda
  6. 单元"口语交际"板块：抽 kouyu_jiaoji 或 goutong_chushi
  ★ 轨三（shumian_biaoda/kouyu_jiaoji/goutong_chushi）必须有！
    统编教材每单元都有写作/口语交际板块，不要遗漏。

▌数量控制：
  - wenyan_word：每篇文言文提取5-15个词（选择最有价值的）
  - 鉴赏型：每篇提取1-3个方法KU（不要重复同类方法）
  - 表达型：每个单元1-3个KU
  - 积累型（非wenyan）：字音/成语/常识各1-5个

输出纯 JSON（无 markdown 代码块）：
{
  "unit": "单元名称",
  "kus": [
    {
      "id": "ku-001",
      "name": "属·劝酒义",
      "ku_type": "wenyan_word",
      "track": "积累",
      "core": "属，动词，劝人饮酒。例：举酒属客，诵明月之诗。",
      "source_text": "《赤壁赋》苏轼",
      "difficulty": 0.4,
      "prerequisites": [],
      "extra": {"词性":"动词","是否通假":false,"是否古今异义":false,"是否词类活用":false,"活用类型":null,"义项":"劝酒","例句":"举酒属客"}
    }
  ],
  "kcs": [
    {"id": "kc-001", "name": "KC名", "logic_reason": "聚类逻辑", "ku_ids": ["ku-001"]}
  ]
}
只输出 JSON，不加任何其他文字。"""


# ── PDF → 单元文本 ────────────────────────────────────────────────────────────

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
    """
    识别单元边界（第X单元）。
    使用与物理脚本相同的贪心单调算法防止页眉误判。
    语文教材每页都有"第X单元"页眉，真正的单元首页特征：
    - 文字较少（导言页）
    - 页面以"第X单元"开头+换行+导言正文
    """
    CHARS = "一二三四五六七八九十"
    unit_occurrences: dict[str, list[int]] = {}

    for pg in sorted(pages):
        text = pages[pg]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue

        # 模式A：第一行="第X单元"（单独），后面几行里有导言正文
        m = re.match(r"^第([一二三四五六七八九十]+)单元$", lines[0])
        if m:
            unit_ch = m.group(1)
            # 找第一个长度>10的非数字行作为导言行
            intro_line = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)),
                None,
            )
            if intro_line:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 模式B：第一行="第X单元NNN"（单元+页码合并），后面紧接导言
        # 例如: "第七单元105" → 导言第二行
        m2 = re.match(r"^第([一二三四五六七八九十]+)单元\d+$", lines[0])
        if m2:
            unit_ch = m2.group(1)
            intro_line = next(
                (l for l in lines[1:] if len(l) > 10 and not re.match(r"^\d+$", l)
                 and "语文" not in l[:4] and "必修" not in l[:4]),
                None,
            )
            if intro_line:
                unit_occurrences.setdefault(unit_ch, []).append(pg)
                continue

        # 兜底：整页文字<350字且含"第X单元"且有导言内容（不含页眉数字）
        if len(text) < 350:
            m3 = re.search(r"第([一二三四五六七八九十]+)单元", text)
            if m3:
                unit_ch = m3.group(1)
                if not re.search(r"\d{2,}", text[:50]):
                    unit_occurrences.setdefault(unit_ch, []).append(pg)

    # 同时处理第一单元（可能没有"第一单元"页眉，直接从导言开始）
    if "一" not in unit_occurrences:
        for pg in sorted(pages)[:20]:
            text = pages[pg]
            # 第一单元导言通常是较短的段落，以"青春"/"学习"/"自然"等主题词开头
            if len(text) < 400 and not re.search(r"第[二三四五六七八九十]+单元", text):
                if re.search(r"本单元", text):
                    unit_occurrences["一"] = [pg]
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
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if text.strip():
            units.append((f"第{uch}单元", text))
    return units


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def _call_llm(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str) -> dict:
    user = (
        f"{unit_name}{part_hint} 正文内容（{len(text_chunk)}字符）：\n\n"
        f"{text_chunk}\n\n"
        "请按三轨13类体系提取所有KU（轨三表达型必须有）。文言词语要逐词提取。"
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
    raise ValueError(f"No JSON in response ({len(raw)} chars): {raw[:120]}")


def llm_extract(client: httpx.Client, unit_name: str, text_chunk: str, part_hint: str = "") -> dict:
    """调用LLM提取KU；失败重试1次；两次都失败则减半各抽一次并合并。"""
    for attempt in range(2):
        try:
            return _call_llm(client, unit_name, text_chunk, part_hint)
        except Exception as e:
            print(f"    [LLM 失败 attempt {attempt+1}] {e}", flush=True)
            time.sleep(3)

    half = len(text_chunk) // 2
    print(f"    [减半重试] chunk {len(text_chunk)}→{half}+{len(text_chunk)-half}", flush=True)
    merged: dict = {"unit": unit_name, "kus": [], "kcs": []}
    kid_offset = 0
    for sub_idx, sub in enumerate([text_chunk[:half], text_chunk[half:]]):
        try:
            sub_hint = f"{part_hint}(减半{sub_idx+1}/2)"
            d = _call_llm(client, unit_name, sub, sub_hint)
            for ku in d.get("kus", []):
                old_id = ku.get("id", f"ku-{kid_offset:03d}")
                new_id = f"ku-{kid_offset:03d}"
                ku["id"] = new_id
                for kc in d.get("kcs", []):
                    kc["ku_ids"] = [new_id if k == old_id else k for k in kc.get("ku_ids", [])]
                kid_offset += 1
            merged["kus"].extend(d.get("kus", []))
            merged["kcs"].extend(d.get("kcs", []))
        except Exception as e:
            print(f"    [减半失败] sub{sub_idx+1}: {e}", flush=True)
    return merged


# ── 抽取主循环 ───────────────────────────────────────────────────────────────

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
            kus  = data.get("kus", [])
            kcs  = data.get("kcs", [])

            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            _attach_kcs(kus, kcs)
            for ku in kus:
                ku["_unit"] = unit_name
                kt = ku.get("ku_type", "wenyan_word")
                if kt not in VALID_KU_TYPES:
                    ku["ku_type"] = "wenyan_word"
                    kt = "wenyan_word"
                # 补全 track
                if not ku.get("track"):
                    ku["track"] = TRACK_MAP.get(kt, "积累")
                # 前置依赖：id→name 转换
                ku["prerequisites"] = [
                    id_to_name.get(p, p)
                    for p in ku.get("prerequisites", []) if p
                ]
            all_kus.extend(kus)

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


# ── 异常检测 ─────────────────────────────────────────────────────────────────

def anomaly_check(tb_id: str, kus: list[dict], is_hs: bool) -> bool:
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    total = len(kus)
    if total == 0:
        print(f"  ⚠️  {tb_id}: 0 KU 抽出，停止", flush=True)
        return False

    # 高中语文必须有 mingpian（名句背诵）
    if is_hs and type_cnt.get("mingpian", 0) == 0:
        print(f"  ⚠️  {tb_id}: mingpian=0（高中语文必须有名篇名句），停止", flush=True)
        return False

    # 高中语文必须有 wenyan_word（必有文言文单元）
    if is_hs and type_cnt.get("wenyan_word", 0) == 0:
        print(f"  ⚠️  {tb_id}: wenyan_word=0（高中语文必须有文言词语），停止", flush=True)
        return False

    # 严重集中：>80% 同一类型
    if total >= 10:
        max_type_ratio = max(type_cnt.values()) / total
        if max_type_ratio > 0.80:
            dominant = max(type_cnt, key=type_cnt.get)
            print(f"  ⚠️  {tb_id}: {dominant} 占比 {max_type_ratio:.0%}，分类异常，停止", flush=True)
            return False

    # 三轨都必须有
    tracks = Counter(TRACK_MAP.get(ku.get("ku_type",""), "") for ku in kus)
    for tr in ("积累", "鉴赏", "表达"):
        if tracks.get(tr, 0) == 0:
            print(f"  ⚠️  {tb_id}: 轨{tr}=0，三轨缺失，停止", flush=True)
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
    diff  = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type = ku.get("ku_type", "wenyan_word")

    desc_parts = []
    if ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("source_text"):
        desc_parts.append(f"【来源】{ku['source_text']}")
    if ku.get("track"):
        desc_parts.append(f"【轨道】{ku['track']}")
    # wenyan_word 额外字段
    if isinstance(ku.get("extra"), dict) and ku_type == "wenyan_word":
        ex = ku["extra"]
        parts_ex = []
        if ex.get("词性"):
            parts_ex.append(f"词性：{ex['词性']}")
        if ex.get("是否通假"):
            parts_ex.append("通假字")
        if ex.get("是否古今异义"):
            parts_ex.append("古今异义")
        if ex.get("是否词类活用") and ex.get("活用类型"):
            parts_ex.append(f"词类活用：{ex['活用类型']}")
        if ex.get("义项"):
            parts_ex.append(f"义项：{ex['义项']}")
        if ex.get("例句"):
            parts_ex.append(f"例句：{ex['例句']}")
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

    fallback = await upsert_cluster(conn, tb_id, "综合语文知识", 999) if not kc_map else next(iter(kc_map.values()))

    for ku in kus:
        kc_names = ku.get("_kcs") or ["综合语文知识"]
        cluster_id = kc_map.get(kc_names[0], fallback)
        await upsert_ku(conn, tb_id, cluster_id, ku)

    return len(kus)


# ── 单本处理 ─────────────────────────────────────────────────────────────────

async def process_book(
    book: dict,
    client: httpx.Client,
    dry_run: bool,
    limit: int | None,
    save_json: str = "",
) -> None:
    tb_id  = book["tb_id"]
    pdf    = PDF_DIR / book["filename"]
    is_hs  = any(x in tb_id for x in ("G10", "G11", "G12"))

    if not pdf.exists():
        print(f"\n[跳过] {tb_id}: PDF 不存在 ({pdf})", flush=True)
        return

    print(f"\n{'='*60}", flush=True)
    print(f"开始: {book['title']} ({tb_id})", flush=True)
    print(f"PDF: {pdf.name} ({pdf.stat().st_size//1024} KB)", flush=True)

    pages = extract_page_texts(pdf)
    units = split_into_units(pages)
    print(f"识别到 {len(units)} 个单元: {[u[0] for u in units]}", flush=True)

    if not units:
        print("  ⚠️  未识别到任何单元，跳过", flush=True)
        return

    kus = extract_all_kus(client, units, limit=limit)
    kus = dedup_kus(kus)

    # 打印分布
    type_cnt  = Counter(ku.get("ku_type") for ku in kus)
    track_cnt = Counter(ku.get("track") for ku in kus)
    print("\n  ── 分布汇总 ──", flush=True)
    print(f"  总计: {len(kus)} KU", flush=True)
    print(f"  三轨: {dict(track_cnt)}", flush=True)
    for t, c in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"    {t:20s}: {c}", flush=True)

    # 打印样本（每类各1条）
    print("\n  ── 样本（每类各1条）──", flush=True)
    shown_types: set = set()
    for ku in kus:
        t = ku.get("ku_type")
        if t not in shown_types:
            shown_types.add(t)
            print(f"  [{t}] {ku.get('name')} | {ku.get('core','')[:60]}", flush=True)
            if ku.get("extra"):
                print(f"         extra: {ku['extra']}", flush=True)

    if save_json:
        out = Path(save_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(kus, f, ensure_ascii=False, indent=2)
        print(f"\n  [save-json] 已保存 {len(kus)} 条 → {save_json}", flush=True)

    if dry_run:
        print("\n  [dry-run] 不入库", flush=True)
        return

    if not anomaly_check(tb_id, kus, is_hs):
        print("  ⚠️  异常检测不过，本册不入库", flush=True)
        return

    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        count = await store_kus(conn, tb_id, kus)
        print(f"\n  ✅ 入库完成: {count} KU", flush=True)
    finally:
        await conn.close()


# ── 入口 ─────────────────────────────────────────────────────────────────────

def _match(tb_id: str, book_filter: list[str]) -> bool:
    if not book_filter:
        return True
    suffix = tb_id.split("-")[-1]
    return any(f == suffix or f == tb_id for f in book_filter)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", default="", help="逗号分隔的 tb_id 后缀")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="每本只跑前N单元")
    parser.add_argument("--save-json", default="", help="把原始KU数据保存到该JSON路径（dry-run时也保存）")
    args = parser.parse_args()

    if not DS_KEY and not args.dry_run:
        sys.exit("需要 DEEPSEEK_API_KEY 环境变量")

    book_filter = [b.strip() for b in args.books.split(",") if b.strip()]
    books = [b for b in CATALOG if _match(b["tb_id"], book_filter)]
    if not books:
        sys.exit(f"没有匹配的教材。可用后缀: {[b['tb_id'].split('-')[-1] for b in CATALOG]}")

    print(f"计划处理: {[b['tb_id'] for b in books]}", flush=True)

    with httpx.Client(headers={"Authorization": f"Bearer {DS_KEY}"}) as client:
        for book in books:
            await process_book(book, client, args.dry_run, args.limit, args.save_json)

    # DB 汇总
    if not args.dry_run:
        conn = await asyncpg.connect(pg_dsn(DB_URL))
        try:
            rows = await conn.fetch("""
                SELECT t.id, t.book_name,
                       COUNT(ku.id) AS ku_count,
                       COUNT(DISTINCT ku.ku_type) AS type_count
                FROM textbooks t
                LEFT JOIN knowledge_units ku ON ku.textbook_id = t.id
                WHERE t.subject = 'chinese'
                GROUP BY t.id, t.book_name
                ORDER BY t.id
            """)
            print("\n\n── 语文教材 KU 汇总 ──")
            for r in rows:
                print(f"  {r['id']:35s} {r['ku_count']:4d} KU  {r['type_count']} types  {r['book_name']}")
        finally:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
