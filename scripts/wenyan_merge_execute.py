"""
wenyan_merge_execute.py  —— 文言实词合并 & 清理 执行脚本（写库）

步骤:
  Step 1: 228条高置信改名 + 册内再合并 + 例句去重
  Step 2: B类11条 + 额外3条删除
  Step 3: A类手工改名 (缒/端/帘/说)
  Step 4: C类改名 (兄/籍/翼) + 特殊(邪/毳)
  Step 5: 老子/礼记名句 → ku_type=mingpian
  Step 6: 句式例子 → ku_type=wenyan_syntax
  Step 7: 最终再合并去重(前面改名可能触发)
  Step 8: 最终报告

⚠️ 写库操作，执行前确认 dry-run 已审核。
"""

import asyncio, asyncpg, re, os, json
from collections import defaultdict
from difflib import SequenceMatcher

DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/mneme"
).replace("postgresql+asyncpg://", "postgresql://")

# ── 手工指定的处理规则 ────────────────────────────────────────────────

# A类: 真词已是root，只去掉·后义项部分（name → root）
A_CLASS_TRIM = {
    "TONGBIAN-G10-CHINESE-BXX-ku-巾-信写在上面的白布方巾":            "巾",
    "TONGBIAN-G10-CHINESE-BXX-ku-旁-通-傍--依傍":                     "旁",
    "TONGBIAN-G10-CHINESE-BXX-ku-诸母-各位伯母叔母":                  "诸母",
    "TONGBIAN-G12-CHINESE-SBXX-ku-中流-江河水流中央":                  "中流",
    "TONGBIAN-G12-CHINESE-SBXX-ku-噌吰-形容钟鼓声":                   "噌吰",
    "TONGBIAN-G12-CHINESE-SBXX-ku-空中-中间是空的":                   "空中",
    "TONGBIAN-G12-CHINESE-SBXX-ku-迷途-迷路-出来做官":                "迷途",
    "TONGBIAN-G7-CHINESE-S-ku-无以-没有什么可以拿来":                 "无以",
    "TONGBIAN-G7-CHINESE-S-ku-明-明确-坚定":                          "明",
    "TONGBIAN-G7-CHINESE-X-ku-尔-同-耳--罢了":                        "尔",
    "TONGBIAN-G7-CHINESE-X-ku-忿然-气愤的样子":                       "忿然",
    "TONGBIAN-G11-CHINESE-SBXM-ku-重-zhòng-负国-更加对不起国家":      "重",
    "TONGBIAN-G11-CHINESE-SBXS-ku-呺-xiāo-然-瓠落无所容义-庄子":     "呺",
}

# A类: 需改name
A_CLASS_RENAME = {
    "TONGBIAN-G10-CHINESE-BXX-ku-夜缒-用绳子拴着从城上下":   "缒",
    "TONGBIAN-G10-CHINESE-BXX-ku-端章甫-穿着礼服戴着礼帽":   "端",
    "TONGBIAN-G12-CHINESE-SBXX-ku-箱帘-同-奁--镜匣":         "帘",
    "TONGBIAN-G12-CHINESE-SBXX-ku-氓-文言词汇-说-通假":       "说",
}

# 说 的义项补充（通"悦"义）
SAY_DESC_PATCH = (
    "说，动词，通假字\n\n"
    "know-what: 说，通'悦'，喜悦\n"
    "know-how: 通假字：说通悦，表示喜悦之意\n"
    "know-why: 古代'说'与'悦'互通，是高频通假字\n"
    "实例: 学而时习之，不亦说乎（《论语》）；心中喜悦，不亦说乎（《氓》语境）\n"
    "来源: 《氓》（诗经·卫风）\n"
    "轨道: 积累\n"
    "[文言]: 词性:动词；义项:通'悦'喜悦；例句:学而时习之，不亦说乎；通假字"
)

# C类: 真词作name，活用进义项
C_CLASS_RENAME = {
    "TONGBIAN-G10-CHINESE-BXX-ku-兄事之-名词作状语-鸿门宴":  "兄",
    "TONGBIAN-G10-CHINESE-BXX-ku-籍吏民-名词作动词-鸿门宴":  "籍",
    "TONGBIAN-G10-CHINESE-BXX-ku-翼蔽-名词作状语-鸿门宴":    "翼",
}

C_CLASS_DESC_PATCH = {
    "TONGBIAN-G10-CHINESE-BXX-ku-兄事之-名词作状语-鸿门宴": (
        "兄，名词，名词作状语\n\n"
        "know-what: 兄，名词，在“兄事之“中用作状语\n"
        "know-how: [名词作状语] 像兄长一样地对待，修饰动词“事“\n"
        "know-why: 词类活用：名词移位充当状语，描述动作方式\n"
        "实例: 项伯乃夜驰之沛公军，私见张良，具告以事，欲呼张良与俱去，毋从俱死也。张良曰……\n"
        "来源: 《鸿门宴》司马迁\n"
        "轨道: 积累\n"
        "[文言]: 词性:名词；义项:名词作状语，像对兄长那样；例句:项伯…兄事之"
    ),
    "TONGBIAN-G10-CHINESE-BXX-ku-籍吏民-名词作动词-鸿门宴": (
        "籍，名词，名词作动词\n\n"
        "know-what: 籍，名词，在“籍吏民“中用作动词\n"
        "know-how: [名词作动词] 登记，造册，将名词“户籍/名册“活用为动词“登记“\n"
        "know-why: 词类活用：名词活用为动词，直接带宾语\n"
        "实例: 沛公乃令张良留谢，……籍吏民，封府库\n"
        "来源: 《鸿门宴》司马迁\n"
        "轨道: 积累\n"
        "[文言]: 词性:名词；义项:名词作动词，登记、造册；例句:籍吏民，封府库"
    ),
    "TONGBIAN-G10-CHINESE-BXX-ku-翼蔽-名词作状语-鸿门宴": (
        "翼，名词，名词作状语\n\n"
        "know-what: 翼，名词，在“翼蔽沛公“中用作状语\n"
        "know-how: [名词作状语] 像翅膀一样地遮蔽，修饰动词“蔽“\n"
        "know-why: 词类活用：名词充当状语，描述动作方式（比喻义）\n"
        "实例: 项伯亦拔剑起舞，常以身翼蔽沛公，庄不得击\n"
        "来源: 《鸿门宴》司马迁\n"
        "轨道: 积累\n"
        "[文言]: 词性:名词；义项:名词作状语，像翅膀一样遮护；例句:以身翼蔽沛公"
    ),
}

# 特殊改名
SPECIAL_RENAME = {
    "TONGBIAN-G8-CHINESE-X-ku-其真无马邪-加强诘问语气-马说":                         "邪",
    "TONGBIAN-G9-CHINESE-S-ku-拥毳衣炉火-裹着裘皮衣服-围着火炉-湖心亭看雪":          "毳",
}

SPECIAL_DESC_PATCH = {
    "TONGBIAN-G8-CHINESE-X-ku-其真无马邪-加强诘问语气-马说": (
        "邪，语气词，加强诘问\n\n"
        "know-what: 邪（yé），语气词，用于句末加强反问语气\n"
        "know-how: 相当于现代汉语\"吗/呢\"，常见于\"...乎...邪\"句式\n"
        "know-why: 文言语气词，表示强烈疑问或反问，是常考虚词\n"
        "实例: 其真无马邪？其真不知马也！（《马说》韩愈）\n"
        "来源: 《马说》韩愈（八年级下）\n"
        "轨道: 积累\n"
        "[文言]: 词性:语气词；义项:加强诘问，相当于“吗/呢“；例句:其真无马邪？"
    ),
    "TONGBIAN-G9-CHINESE-S-ku-拥毳衣炉火-裹着裘皮衣服-围着火炉-湖心亭看雪": (
        "毳，名词，鸟兽细毛\n\n"
        "know-what: 毳（cuì），名词，鸟兽细密的软毛，毳衣即皮袄\n"
        "know-how: 毳衣：用细毛皮革制成的衣服，即皮袄；拥毳衣：裹着皮袄\n"
        "know-why: 生僻字，需掌握字音字义，常与“毛“字区分（毛为粗，毳为细）\n"
        "实例: 余拏一小舟，拥毳衣炉火，独往湖心亭看雪（《湖心亭看雪》张岱）\n"
        "来源: 《湖心亭看雪》张岱（九年级上）\n"
        "轨道: 积累\n"
        "[文言]: 词性:名词；义项:鸟兽细毛，毳衣=皮袄；例句:拥毳衣炉火"
    ),
}

# B类删除 (篇目名·分类标签)
B_DELETE_IDS = [
    "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-古今异义",
    "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-文言实词",
    "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-文言虚词",
    "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-词类活用",
    "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-通假字",
    "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-古今异义",
    "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-文言实词",
    "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-词类活用",
    "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-通假字",
    "TONGBIAN-G10-CHINESE-BXX-ku-齐桓晋文之事-文言实词",
    "TONGBIAN-G10-CHINESE-BXS-ku-琵琶行-文言词汇",
]

EXTRA_DELETE_IDS = [
    "TONGBIAN-G7-CHINESE-X-ku-动态助词-着-了-过",
    "TONGBIAN-G7-CHINESE-X-ku-语气助词-了-嘛-啦-吗-呢-吧-啊",
    "TONGBIAN-G10-CHINESE-BXX-ku-意洞-林觉民自称",
]

ALL_DELETE_IDS = set(B_DELETE_IDS + EXTRA_DELETE_IDS)

# 老子/礼记名句 → mingpian
MINGPIAN_CONVERT = [
    ("TONGBIAN-G11-CHINESE-SBXS-ku-知人者智-自知者明义-老子",
     "知人者智，自知者明",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G11-CHINESE-SBXS-ku-为之于未有-治之于未乱义-老子",
     "为之于未有，治之于未乱",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G11-CHINESE-SBXS-ku-企者不立-跨者不行义-老子",
     "企者不立，跨者不行",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G11-CHINESE-SBXS-ku-知足者富-强行者有志义-老子",
     "知足者富，强行者有志",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G11-CHINESE-SBXS-ku-胜人者有力-自胜者强义-老子",
     "胜人者有力，自胜者强",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G11-CHINESE-SBXS-ku-不失其所者久-死而不亡者寿义-老子",
     "不失其所者久，死而不亡者寿",
     "TONGBIAN-G11-CHINESE-SBXS-kc-第二单元-名篇名句"),
    ("TONGBIAN-G8-CHINESE-X-ku-货恶其弃于地也-不必藏于己-礼记二则",
     "货恶其弃于地也，不必藏于己",
     "TONGBIAN-G8-CHINESE-X-kc-大道之行也-名句"),
]

# 句式例子 → wenyan_syntax
WENYAN_SYNTAX_CONVERT = [
    ("TONGBIAN-G9-CHINESE-X-ku-战胜于朝廷-在朝廷上取胜",
     "状语后置·战胜于朝廷（邹忌讽齐王纳谏）",
     "TONGBIAN-G9-CHINESE-X-kc-邹忌讽齐王纳谏-文言句式"),
    ("TONGBIAN-G9-CHINESE-X-ku-谤讥于市朝-在公共场所指责",
     "状语后置·谤讥于市朝（邹忌讽齐王纳谏）",
     "TONGBIAN-G9-CHINESE-X-kc-邹忌讽齐王纳谏-文言句式"),
]

# 所有需要单独处理的 ID（跳过自动处理）
MANUAL_IDS = (
    set(A_CLASS_TRIM) | set(A_CLASS_RENAME) | set(C_CLASS_RENAME) |
    set(SPECIAL_RENAME) | ALL_DELETE_IDS |
    {r[0] for r in MINGPIAN_CONVERT} |
    {r[0] for r in WENYAN_SYNTAX_CONVERT}
)

# ── 描述解析 ──────────────────────────────────────────────────────────

CATEGORY_LABELS = {
    "文言词语", "文言实词", "文言虚词", "文言词汇",
    "古今异义", "通假字", "词类活用", "文言句式",
}

def is_002(desc: str) -> bool:
    return bool(desc and ("know-what:" in desc or "[文言]:" in desc))

def parse_yixiang_002(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": "", "know_what": "", "know_why": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("[文言]:"):
            for seg in l[5:].strip().split("；"):
                s = seg.strip()
                if s.startswith("词性:"): r["pos"] = s[3:].strip()
                elif s.startswith("义项:"): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句:"): r["liju"] = s[3:].strip()
                elif "通假" in s: r["tongja"] = s
        elif l.startswith("来源:"):
            r["source"] = l[3:].strip()
        elif l.startswith("know-what:") and not r["know_what"]:
            r["know_what"] = l[10:].strip()
        elif l.startswith("know-why:") and not r["know_why"]:
            r["know_why"] = l[9:].strip()
    return r

def parse_yixiang_old(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": "", "know_what": "", "know_why": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("【来源】"): r["source"] = l[4:].strip()
        elif l.startswith("【文言】"):
            for seg in l[4:].strip().split("；"):
                s = seg.strip()
                if s.startswith("词性："): r["pos"] = s[3:].strip()
                elif s.startswith("义项："): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句："): r["liju"] = s[3:].strip()
    r["know_what"] = desc.split("\n")[0].strip()
    return r

def parse_yixiang(desc: str) -> dict:
    if not desc: return {}
    return parse_yixiang_002(desc) if is_002(desc) else parse_yixiang_old(desc)

# ── 词根识别 ─────────────────────────────────────────────────────────

_WORD_PAT = re.compile(r"^([^，,、\s（(【\[「『：:]+)")

def actual_word_from_desc(desc: str) -> str:
    if not desc: return ""
    if is_002(desc):
        for line in desc.split("\n"):
            l = line.strip()
            if l.startswith("know-what:"):
                m = _WORD_PAT.match(l[10:].strip())
                return m.group(1).strip("·") if m else ""
    else:
        first = desc.split("\n")[0].strip()
        m = re.match(r"^([^，,、\s（(【\[「『：:]+)[：:]", first)
        return m.group(1).strip("·") if m else ""
    return ""

def extract_word_from_name_parts(name: str, root: str) -> tuple[str, str]:
    parts = [p.strip() for p in name.split("·")]
    candidates = []
    for part in parts[1:]:
        if part in CATEGORY_LABELS: continue
        m_before = re.match(r"^([^（(]+)[（(]", part)
        if m_before:
            w = m_before.group(1).strip()
            if w and w not in CATEGORY_LABELS:
                candidates.append((w, "high"))
                continue
        m_in = re.match(r"^[^（(]*[（(]([^）)]+)[）)]", part)
        if m_in:
            w = m_in.group(1).strip()
            if not w.startswith("《") and len(w) <= 8:
                candidates.append((w, "high"))
                continue
        candidates.append((part, "low" if len(part) <= 5 else "fail"))
    if not candidates: return "", "fail"
    word, conf = candidates[0]
    if conf == "high" and len(word) > 4: conf = "low"
    return word, conf

def is_pattern_b(entry: dict, root: str) -> bool:
    if len(root) > 4: return True
    w = actual_word_from_desc(entry["description"] or "")
    return bool(w and w != root)

def compute_high_conf_name_map(rows: list) -> dict[str, str]:
    """计算 228条高置信 name_map，跳过 MANUAL_IDS。"""
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["id"] in MANUAL_IDS: continue
        root = r["name"].split("·")[0].strip() if "·" in r["name"] else r["name"].strip()
        groups[(r["textbook_id"], root)].append(dict(r))

    name_map: dict[str, str] = {}
    for (tb_id, root), entries in groups.items():
        if len(entries) < 2: continue
        if len(root) > 4:
            for e in entries:
                word, conf = extract_word_from_name_parts(e["name"], root)
                desc_word = actual_word_from_desc(e["description"] or "")
                if conf == "high" and word:
                    name_map[e["id"]] = word
                elif word and desc_word and word == desc_word:
                    name_map[e["id"]] = word
                # else: skip (low conf, handled by MANUAL_IDS or kept as-is)
        else:
            mismatches = 0
            tw = []
            for e in entries:
                w = actual_word_from_desc(e["description"] or "")
                tw.append(w)
                if w and w != root: mismatches += 1
            if mismatches >= len(entries) // 2 + 1:
                # Pattern B with short root
                for e, w in zip(entries, tw):
                    word, conf = extract_word_from_name_parts(e["name"], root)
                    if conf == "high" and word:
                        name_map[e["id"]] = word
    return name_map

# ── 去重 ─────────────────────────────────────────────────────────────

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def dedup_yixiangs(yis: list[dict]) -> tuple[list[dict], int]:
    seen_keys, seen_liju, kept = [], [], []
    removed = 0
    for yi in yis:
        key = f"{yi.get('pos','')}|{yi.get('yixiang','')}|{yi.get('liju','')[:30]}"
        liju = yi.get("liju", "").strip()
        if key in seen_keys: removed += 1; continue
        if liju and liju in seen_liju: removed += 1; continue
        yi_str = yi.get("yixiang", "") + yi.get("liju", "")
        is_dup = any(
            yi_str and sk.split("|")[1] + (sk.split("|")[2] if len(sk.split("|")) > 2 else "")
            and similar(yi_str, sk.split("|")[1] + (sk.split("|")[2] if len(sk.split("|")) > 2 else "")) > 0.85
            for sk in seen_keys
        )
        if is_dup: removed += 1; continue
        seen_keys.append(key)
        if liju: seen_liju.append(liju)
        kept.append(yi)
    return kept, removed

# ── 合并描述生成 ──────────────────────────────────────────────────────

def pick_best(entries: list[dict]) -> dict:
    def score(e):
        d = e.get("description") or ""
        return (10 if is_002(d) else 0) + len(d) / 100
    return max(entries, key=score)

def build_merged_desc(root: str, yixiangs: list[dict], sources: list[str], best_entry: dict) -> str:
    if len(yixiangs) == 1:
        # 单义项：保留原描述，仅更新 name（调用方处理）
        return best_entry.get("description") or ""

    n = len(yixiangs)
    numbers = "①②③④⑤⑥⑦⑧"
    know_how_parts = []
    yi_lines = []
    for i, yi in enumerate(yixiangs):
        pos = yi.get("pos", "") or ""
        meaning = yi.get("yixiang", "") or ""
        example = yi.get("liju", "") or ""
        tongja = yi.get("tongja", "") or ""
        num = numbers[i] if i < len(numbers) else f"{i+1}."
        part = f"{num}[{pos}]{meaning}"
        if example: part += f"，例：{example}"
        if tongja:  part += f"（{tongja}）"
        know_how_parts.append(part)
        yi_lines.append(
            f"义项{i+1}: 词性:{pos}；义项:{meaning}；例句:{example}"
            + (f"；{tongja}" if tongja else "")
        )

    # know-why from best
    know_why = ""
    best_d = best_entry.get("description") or ""
    for line in best_d.split("\n"):
        l = line.strip()
        if l.startswith("know-why:"):
            know_why = l[9:].strip()
            break

    src_str = "·".join(sources) if sources else ""
    first_yi = yixiangs[0]
    parts = [
        f"{root}，文言词语，{n}义项",
        "",
        f"know-what: {root}，文言词语",
        f"know-how: {'；'.join(know_how_parts)}",
    ]
    if know_why:
        parts.append(f"know-why: {know_why}")
    if src_str:
        parts.append(f"来源: {src_str}")
    parts.append("轨道: 积累")
    parts.append(
        f"[文言]: 词性:{first_yi.get('pos','')}；"
        f"义项:{first_yi.get('yixiang','')}；"
        f"例句:{first_yi.get('liju','')}"
    )
    if len(yixiangs) > 1:
        parts.append("[多义项]:")
        parts.extend(yi_lines)
    return "\n".join(parts)

# ── 合并执行 ─────────────────────────────────────────────────────────

async def merge_groups(conn, rows_fn, log_prefix="") -> dict:
    """取最新行，按(textbook_id, root)分组，执行合并+去重。"""
    rows = await rows_fn()
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        e = dict(r)
        root = e["name"].split("·")[0].strip() if "·" in e["name"] else e["name"].strip()
        groups[(e["textbook_id"], root)].append(e)

    stats = {"merged_groups": 0, "deleted": 0, "dup_removed": 0}
    for (tb_id, root), entries in groups.items():
        if len(entries) < 2: continue

        all_yi, all_sources, all_ids = [], [], [e["id"] for e in entries]
        for e in entries:
            yi = parse_yixiang(e["description"] or "")
            all_yi.append(yi)
            src = yi.get("source", "")
            if src and src not in all_sources:
                all_sources.append(src)

        deduped, n_removed = dedup_yixiangs(all_yi)
        stats["merged_groups"] += 1
        stats["dup_removed"] += n_removed

        best = pick_best(entries)
        keep_id = best["id"]
        delete_ids = [e["id"] for e in entries if e["id"] != keep_id]

        new_desc = build_merged_desc(root, deduped, all_sources, best)
        await conn.execute(
            "UPDATE knowledge_units SET name=$1, description=$2 WHERE id=$3",
            root, new_desc, keep_id
        )
        for del_id in delete_ids:
            await conn.execute("DELETE FROM knowledge_units WHERE id=$1", del_id)
        stats["deleted"] += len(delete_ids)
        if log_prefix:
            print(f"  {log_prefix} merge `{root}` ({tb_id[:20]}): keep={keep_id[-20:]}, "
                  f"del={len(delete_ids)}, yi={len(deduped)}, dup={n_removed}")

    return stats

# ── 主流程 ───────────────────────────────────────────────────────────

async def run():
    conn = await asyncpg.connect(DB_URL)
    total_before = await conn.fetchval(
        "SELECT count(*) FROM knowledge_units ku JOIN textbooks t ON ku.textbook_id=t.id "
        "WHERE ku.ku_type='wenyan_word' AND t.subject='chinese'"
    )
    print(f"=== 开始合并 === 初始条数: {total_before}\n")

    async def fetch_wenyan():
        return await conn.fetch(
            "SELECT ku.id, ku.name, ku.description, ku.textbook_id, t.book_name, t.grade "
            "FROM knowledge_units ku JOIN textbooks t ON ku.textbook_id=t.id "
            "WHERE ku.ku_type='wenyan_word' AND t.subject='chinese' "
            "ORDER BY t.grade, ku.textbook_id, ku.name"
        )

    # ── Step 1: 高置信 Pattern B 改名 ─────────────────────────────────
    print("── Step 1: 228条高置信改名 ──")
    rows = await fetch_wenyan()
    high_map = compute_high_conf_name_map(rows)
    n_renamed = 0
    for ku_id, new_name in high_map.items():
        await conn.execute("UPDATE knowledge_units SET name=$1 WHERE id=$2", new_name, ku_id)
        n_renamed += 1
    print(f"  改名: {n_renamed} 条")

    # ── Step 1b: 高置信改名后，册内再合并 ────────────────────────────
    print("── Step 1b: 册内再合并（高置信改名触发）──")
    s1 = await merge_groups(conn, fetch_wenyan)
    print(f"  合并组: {s1['merged_groups']}, 删除: {s1['deleted']}, 义项去重: {s1['dup_removed']}")

    # ── Step 2: 删除 B类 + 额外误抽取条目 ────────────────────────────
    print("\n── Step 2: 删除 B类(11) + 额外(3) ──")
    for del_id in ALL_DELETE_IDS:
        n = await conn.execute("DELETE FROM knowledge_units WHERE id=$1", del_id)
        print(f"  DELETE {del_id[-30:]}: {n}")

    # ── Step 3: A类手工改名 ───────────────────────────────────────────
    print("\n── Step 3: A类手工改名 ──")
    # 3a: trim to root (13条)
    for ku_id, new_name in A_CLASS_TRIM.items():
        await conn.execute("UPDATE knowledge_units SET name=$1 WHERE id=$2", new_name, ku_id)
        print(f"  TRIM {ku_id[-30:]}: → '{new_name}'")

    # 3b: rename 4条
    for ku_id, new_name in A_CLASS_RENAME.items():
        if ku_id == "TONGBIAN-G12-CHINESE-SBXX-ku-氓-文言词汇-说-通假":
            await conn.execute(
                "UPDATE knowledge_units SET name=$1, description=$2 WHERE id=$3",
                new_name, SAY_DESC_PATCH, ku_id
            )
            print(f"  RENAME+DESC {ku_id[-30:]}: → '{new_name}' (说·description更新)")
        else:
            await conn.execute("UPDATE knowledge_units SET name=$1 WHERE id=$2", new_name, ku_id)
            print(f"  RENAME {ku_id[-30:]}: → '{new_name}'")

    # ── Step 4: C类改名 + 特殊 ───────────────────────────────────────
    print("\n── Step 4: C类改名 + 特殊 ──")
    for ku_id, new_name in {**C_CLASS_RENAME, **SPECIAL_RENAME}.items():
        desc_patch = C_CLASS_DESC_PATCH.get(ku_id) or SPECIAL_DESC_PATCH.get(ku_id)
        if desc_patch:
            await conn.execute(
                "UPDATE knowledge_units SET name=$1, description=$2 WHERE id=$3",
                new_name, desc_patch, ku_id
            )
        else:
            await conn.execute("UPDATE knowledge_units SET name=$1 WHERE id=$2", new_name, ku_id)
        print(f"  RENAME {ku_id[-35:]}: → '{new_name}'")

    # ── Step 5: 老子/礼记名句 → mingpian ─────────────────────────────
    print("\n── Step 5: 名句 → ku_type=mingpian ──")
    for ku_id, new_name, cluster_id in MINGPIAN_CONVERT:
        await conn.execute(
            "UPDATE knowledge_units SET name=$1, ku_type='mingpian', cluster_id=$2 WHERE id=$3",
            new_name, cluster_id, ku_id
        )
        print(f"  CONVERT {ku_id[-35:]}: → mingpian '{new_name[:20]}'")

    # ── Step 6: 句式 → wenyan_syntax ─────────────────────────────────
    print("\n── Step 6: 句式 → ku_type=wenyan_syntax ──")
    for ku_id, new_name, cluster_id in WENYAN_SYNTAX_CONVERT:
        await conn.execute(
            "UPDATE knowledge_units SET name=$1, ku_type='wenyan_syntax', cluster_id=$2 WHERE id=$3",
            new_name, cluster_id, ku_id
        )
        print(f"  CONVERT {ku_id[-35:]}: → wenyan_syntax '{new_name[:30]}'")

    # ── Step 7: 最终再合并（Step 3-4 改名后可能触发新重复）────────────
    print("\n── Step 7: 最终再合并去重 ──")
    s7 = await merge_groups(conn, fetch_wenyan)
    print(f"  合并组: {s7['merged_groups']}, 删除: {s7['deleted']}, 义项去重: {s7['dup_removed']}")

    # ── Step 8: 最终报告 ──────────────────────────────────────────────
    total_after = await conn.fetchval(
        "SELECT count(*) FROM knowledge_units ku JOIN textbooks t ON ku.textbook_id=t.id "
        "WHERE ku.ku_type='wenyan_word' AND t.subject='chinese'"
    )
    mingpian_after = await conn.fetchval(
        "SELECT count(*) FROM knowledge_units WHERE ku_type='mingpian'"
    )
    wenyan_syntax_after = await conn.fetchval(
        "SELECT count(*) FROM knowledge_units WHERE ku_type='wenyan_syntax'"
    )

    print("\n" + "="*50)
    print(f"=== 最终统计 ===")
    print(f"wenyan_word: {total_before} → {total_after} (减少 {total_before - total_after})")
    print(f"mingpian 转入 +7（当前总计: {mingpian_after}）")
    print(f"wenyan_syntax 转入 +2（当前总计: {wenyan_syntax_after}）")
    print(f"Step1 改名: {n_renamed}, Step1b合并: {s1['merged_groups']}组/{s1['deleted']}删/{s1['dup_removed']}去重")
    print(f"Step7 合并: {s7['merged_groups']}组/{s7['deleted']}删/{s7['dup_removed']}去重")

    # 多义词样例
    print("\n── 多义词样例（以/且/曾/因/道）──")
    for word in ["以", "且", "曾", "因", "道"]:
        sample_rows = await conn.fetch(
            "SELECT ku.id, ku.name, ku.textbook_id, t.book_name, ku.description "
            "FROM knowledge_units ku JOIN textbooks t ON ku.textbook_id=t.id "
            "WHERE ku.ku_type='wenyan_word' AND t.subject='chinese' "
            "AND ku.name=$1 ORDER BY t.grade", word
        )
        print(f"\n【{word}】共 {len(sample_rows)} 个textbook 中出现:")
        for r in sample_rows:
            desc = r["description"] or ""
            # Extract义项 count
            yi_count = desc.count("义项") if "[多义项]:" in desc else 1
            know_how = ""
            for line in desc.split("\n"):
                if line.strip().startswith("know-how:"):
                    know_how = line.strip()[9:].strip()[:80]
                    break
            print(f"  {r['book_name'][:14]}: {r['name']} | know-how: {know_how}…")

    await conn.close()
    print("\n=== 合并完成 ===")

if __name__ == "__main__":
    asyncio.run(run())
