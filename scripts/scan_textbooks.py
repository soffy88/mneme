#!/usr/bin/env python3
"""
扫描 ~/books/教材/ 所有 PDF，解析元数据，生成 textbook_import_plan.json。
只生成清单，不执行任何数据库或 MinIO 操作。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SOURCE_DIR = Path.home() / "books" / "教材"
OUTPUT_FILE = Path(__file__).parent / "textbook_import_plan.json"
LARGE_THRESHOLD_MB = 200  # 超过此值标记为可能扫描件

# ── 学科检测 ─────────────────────────────────────────────────────────────────

CHINESE_KEYWORDS = [
    "语文", "小说", "诗歌", "散文", "传记", "戏曲", "诸子", "文化",
    "演讲", "辩论", "写作", "新闻阅读", "影视", "语言文字",
]

def detect_subject(name: str) -> str:
    if "数学" in name: return "math"
    if "物理" in name: return "physics"
    if any(k in name for k in ["英语", "English", "english"]): return "english"
    if any(k in name for k in CHINESE_KEYWORDS): return "chinese"
    return "other"


# ── 版本检测 ─────────────────────────────────────────────────────────────────

def detect_edition(name: str) -> str:
    # 注意顺序：B版先于普通人教版
    if re.search(r"人教\s*[Bb]版", name): return "RENJIAOB"
    if "新起点" in name: return "XINQIDIAN"
    if "北师大" in name: return "BEISHIDA"
    if "外研社" in name or "外研版" in name or "外研" in name: return "WAIYAN"
    if "统编版" in name or ("统编" in name and "人教" not in name): return "TONGBIAN"
    # 人教版（含统编人教版、新人教版）
    if "人教" in name: return "RENJIAO"
    return "RENJIAO"  # 无明确版本信息默认人教


# ── 年级 + 学段检测 ──────────────────────────────────────────────────────────

# 小学阶段汉字数字映射
CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}

def detect_grade(name: str) -> tuple[str, bool]:
    """返回 (grade_code, is_high_school)"""

    # ── 小学 ──
    for i in range(1, 7):
        cn = "一二三四五六"[i - 1]
        if f"{i}年级" in name or f"{cn}年级" in name:
            return f"G{i}", False

    # ── 初中 ──
    if "七年级" in name or "7年级" in name:
        return "G7", False
    if any(k in name for k in ["八年级", "8年级", "八上", "八下", "8上", "8下"]):
        return "G8", False
    if any(k in name for k in ["九年级", "9年级", "九上", "九下"]):
        return "G9", False

    # ── 高中（按必修编号推算年级）──
    m = re.search(r"必修\s*(\d+)", name)
    if m:
        n = int(m.group(1))
        if n <= 2: return "G10", True
        if n <= 4: return "G11", True
        return "G12", True  # 必修5

    if "选修" in name or "高中" in name:
        return "G12", True  # 选修均归 G12

    return "HS", True  # 高中通用（未能精确定位）


# ── 册次检测 ─────────────────────────────────────────────────────────────────

# 高中语文选修短名映射（书名 → 短码）
ZW_ELECTIVE_MAP = {
    "中国古代诗歌散文欣赏": "XX-GDSHIGE",
    "中国小说欣赏": "XX-ZGXIAOSHUO",
    "中外传记作品选读": "XX-CHUANJI",
    "中外戏曲名作欣赏": "XX-XIQU",
    "先秦诸子选读": "XX-ZHUZI",
    "中国文化经典研读": "XX-WENHUA",
    "中国民俗文化": "XX-MINSHU",
    "外国小说欣赏": "XX-WGXIAOSHUO",
    "外国诗歌散文欣赏": "XX-WGSHIGE",
    "影视名作欣赏": "XX-YINGSHI",
    "文章写作与修改": "XX-XIEZUO",
    "新闻阅读与实践": "XX-XINWEN",
    "演讲与辩论": "XX-YANJIANG",
    "语言文字应用": "XX-YUYAN",
    "小说欣赏入门": "XX-XIAOSHUO",  # 单独文件
    "英语写作": "XX-XIEZUO",
    "高中英语语法与词汇": "XX-YUFA",
}

def detect_volume(name: str, subject: str) -> str:
    # 必修
    m = re.search(r"必修\s*(\d+)", name)
    if m: return f"BX{m.group(1)}"

    # 选修 N-M（如 选修2-1, 选修4-5）
    m = re.search(r"选修\s*(\d+)[－\-](\d+)", name)
    if m: return f"XX{m.group(1)}-{m.group(2)}"

    # 选修 N（如 选修10, 选修6）
    m = re.search(r"选修\s*(\d+)", name)
    if m: return f"XX{m.group(1)}"

    # 上/下册（含"八上"/"八下"/"九上"/"九下"等汉字数字格式）
    if ("上册" in name or "上【" in name
            or re.search(r"\d+上", name)
            or re.search(r"[七八九]上", name)):
        return "S"
    if ("下册" in name or "下【" in name
            or re.search(r"\d+下", name)
            or re.search(r"[七八九]下", name)):
        return "X"
    if "全一册" in name or "全一" in name: return "QYC"

    # 高中语文选修书名
    for keyword, code in ZW_ELECTIVE_MAP.items():
        if keyword in name:
            return code

    # 英语辅助/语法
    if "语法" in name or "词汇" in name: return "XX-YUFA"
    if "写作" in name and subject == "english": return "XX-XIEZUO"

    return "QYC"  # 默认全一册


# ── 跳过规则 ─────────────────────────────────────────────────────────────────

UUID_RE = re.compile(r"-[0-9a-f]{8,}$")

def should_skip(name: str, size_mb: float) -> tuple[bool, str]:
    """返回 (should_skip, reason)"""
    stem = Path(name).stem

    # 1. UUID后缀文件（重复）
    if UUID_RE.search(stem):
        return True, "UUID后缀重复文件"

    # 2. 词汇表/单词表
    if any(k in name for k in ["单词表", "词汇表"]):
        return True, "非正式教材：词汇表"

    # 3. 参考版/背诵版/默写版
    if any(k in name for k in ["背诵版", "默写版", "参考版"]):
        return True, "非正式教材：练习辅助版"

    # 4. 超大文件（高清扫描件，先标记）
    if size_mb > LARGE_THRESHOLD_MB:
        return True, f"超大文件({size_mb:.1f}MB)，疑似高清扫描件，人工确认"

    return False, ""


# ── textbook_id 生成 ─────────────────────────────────────────────────────────

def make_textbook_id(edition: str, grade: str, subject: str, volume: str) -> str:
    return f"{edition}-{grade}-{subject.upper()}-{volume}".upper()


# ── book_name 生成 ───────────────────────────────────────────────────────────

EDITION_ZH = {
    "RENJIAO": "人教版",
    "RENJIAOB": "人教B版",
    "BEISHIDA": "北师大版",
    "WAIYAN": "外研版",
    "TONGBIAN": "统编版",
    "XINQIDIAN": "英语新起点",
}

SUBJECT_ZH = {
    "math": "数学",
    "physics": "物理",
    "chinese": "语文",
    "english": "英语",
    "other": "其他",
}

GRADE_ZH = {
    "G1": "一年级", "G2": "二年级", "G3": "三年级",
    "G4": "四年级", "G5": "五年级", "G6": "六年级",
    "G7": "七年级", "G8": "八年级", "G9": "九年级",
    "G10": "高一", "G11": "高二", "G12": "高三",
    "HS": "高中",
}

VOLUME_ZH = {
    "S": "上册", "X": "下册", "QYC": "全一册",
    "BX1": "必修1", "BX2": "必修2", "BX3": "必修3",
    "BX4": "必修4", "BX5": "必修5",
    "XX1-1": "选修1-1", "XX1-2": "选修1-2",
    "XX2-1": "选修2-1", "XX2-2": "选修2-2", "XX2-3": "选修2-3",
    "XX3-1": "选修3-1", "XX3-2": "选修3-2", "XX3-3": "选修3-3",
    "XX3-4": "选修3-4", "XX3-5": "选修3-5",
    "XX4-1": "选修4-1", "XX4-2": "选修4-2", "XX4-4": "选修4-4",
    "XX4-5": "选修4-5", "XX4-6": "选修4-6", "XX4-7": "选修4-7",
    "XX4-9": "选修4-9",
    "XX6": "选修6", "XX7": "选修7", "XX8": "选修8",
    "XX9": "选修9", "XX10": "选修10", "XX11": "选修11",
}

# 高中语文选修书名全称
ZW_ELECTIVE_NAMES = {
    "XX-GDSHIGE": "中国古代诗歌散文欣赏",
    "XX-ZGXIAOSHUO": "中国小说欣赏",
    "XX-CHUANJI": "中外传记作品选读",
    "XX-XIQU": "中外戏曲名作欣赏",
    "XX-ZHUZI": "先秦诸子选读",
    "XX-WENHUA": "中国文化经典研读",
    "XX-MINSHU": "中国民俗文化",
    "XX-WGXIAOSHUO": "外国小说欣赏",
    "XX-WGSHIGE": "外国诗歌散文欣赏",
    "XX-YINGSHI": "影视名作欣赏",
    "XX-XIEZUO": "文章写作与修改",
    "XX-XINWEN": "新闻阅读与实践",
    "XX-YANJIANG": "演讲与辩论",
    "XX-YUYAN": "语言文字应用",
    "XX-XIAOSHUO": "小说欣赏入门",
    "XX-YUFA": "语法与词汇",
}

def make_book_name(edition: str, grade: str, subject: str, volume: str, orig_name: str) -> str:
    e = EDITION_ZH.get(edition, edition)
    g = GRADE_ZH.get(grade, grade)
    s = SUBJECT_ZH.get(subject, subject)

    # 特殊：高中语文/英语选修，用中文全名
    if volume.startswith("XX-"):
        elec_name = ZW_ELECTIVE_NAMES.get(volume, "")
        if elec_name:
            return f"{e}{s}选修·{elec_name}"
        return f"{e}{g}{s}选修"

    v = VOLUME_ZH.get(volume, volume)
    return f"{e}{g}{s}{v}"


# ── 主流程 ────────────────────────────────────────────────────────────────────

def scan() -> list[dict]:
    pdfs = sorted(SOURCE_DIR.glob("**/*.pdf"))
    entries = []

    for pdf in pdfs:
        size_bytes = pdf.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        name = pdf.name

        # 跳过检查
        skip, skip_reason = should_skip(name, size_mb)

        subject = detect_subject(name)
        edition = detect_edition(name)
        grade, is_hs = detect_grade(name)
        volume = detect_volume(name, subject)
        textbook_id = make_textbook_id(edition, grade, subject, volume)
        book_name = make_book_name(edition, grade, subject, volume, name)

        entries.append({
            "file_path": str(pdf),
            "filename": name,
            "textbook_id": textbook_id,
            "subject": subject,
            "grade": grade,
            "edition": edition,
            "volume": volume,
            "book_name": book_name,
            "file_size_mb": round(size_mb, 2),
            "action": "skip" if skip else "import",
            "skip_reason": skip_reason,
        })

    return entries


def dedup(entries: list[dict]) -> list[dict]:
    """
    同一 textbook_id 若有多个 action=import 的条目，保留文件最合适的一个。
    选择策略：大小在 10-200MB 之间 → 优先；否则选最大的（但已排除>200MB）。
    """
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        if e["action"] == "import":
            groups[e["textbook_id"]].append(e)

    for tid, group in groups.items():
        if len(group) <= 1:
            continue
        # 在 10-200MB 范围内挑最大的（最清晰）
        preferred = sorted(
            group,
            key=lambda x: x["file_size_mb"] if 10 <= x["file_size_mb"] <= 200 else -x["file_size_mb"],
            reverse=True,
        )
        keep = preferred[0]
        for e in preferred[1:]:
            e["action"] = "skip"
            e["skip_reason"] = f"重复文件（保留 {keep['filename']}，{keep['file_size_mb']:.1f}MB）"

    return entries


def print_summary(entries: list[dict]) -> None:
    imports = [e for e in entries if e["action"] == "import"]
    skips = [e for e in entries if e["action"] == "skip"]

    print(f"\n{'='*60}")
    print(f" 教材 PDF 扫描结果（共 {len(entries)} 个文件）")
    print(f"{'='*60}")
    print(f" 计划导入：{len(imports)} 本")
    print(f" 跳过：    {len(skips)} 个（含去重）")
    print()

    # 分学段列表
    stages = {
        "小学": [e for e in imports if e["grade"] in [f"G{i}" for i in range(1, 7)]],
        "初中": [e for e in imports if e["grade"] in ["G7", "G8", "G9"]],
        "高中": [e for e in imports if e["grade"] in ["G10", "G11", "G12", "HS"]],
    }
    for stage, lst in stages.items():
        if lst:
            print(f"── {stage}（{len(lst)} 本）──")
            for e in sorted(lst, key=lambda x: (x["grade"], x["subject"], x["textbook_id"])):
                print(f"  [{e['textbook_id']}]  {e['book_name']}  ({e['file_size_mb']:.1f}MB)")
            print()

    # 跳过原因分组
    skip_reasons: dict[str, list] = {}
    for e in skips:
        r = e["skip_reason"].split("（")[0].strip()  # 取主原因
        skip_reasons.setdefault(r, []).append(e)

    print("── 跳过明细 ──")
    for reason, lst in sorted(skip_reasons.items()):
        print(f"  [{reason}]  {len(lst)} 个：")
        for e in lst:
            print(f"    - {e['filename']}  ({e['file_size_mb']:.1f}MB)")
    print()


def main():
    print(f"扫描目录：{SOURCE_DIR}")
    entries = scan()
    entries = dedup(entries)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"清单已写入：{OUTPUT_FILE}")
    print_summary(entries)


if __name__ == "__main__":
    main()
