"""
import_textbooks_subjects.py
把 curriculum_standards/ 里的语文/英语/物理/历史 PDF 入库。

textbook_id 规则：{PUBLISHER}-{GRADE}-{SUBJECT}-{VOLUME}
  PUBLISHER: TONGBIAN / RENJIAO / PEP1 / PEP3 / JINGTONG / PEP2022
  GRADE: G1-G9, G10/G11/G12 (高一/二/三)
  SUBJECT: CHINESE / ENGLISH / PHYSICS / HISTORY
  VOLUME: S/X(上/下) BX1/2/3(必修) SBX1/2/3(选必) QYC(全一册) 等
"""

import os, sys, uuid, hashlib
from pathlib import Path

import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mneme")
STANDARDS_DIR = Path(__file__).parent.parent / "curriculum_standards"

# ── 完整映射表：filename → (textbook_id, subject, grade, edition, book_name) ──
MAPPING = {
    # ━━━━━━━━━━━━━ 语文 ━━━━━━━━━━━━━
    # 小学 1-6 年级（统编版）
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文一年级上册.pdf":
        ("TONGBIAN-G1-CHINESE-S",  "chinese", "G1",  "TONGBIAN", "统编版·语文一年级上册"),
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文一年级下册.pdf":
        ("TONGBIAN-G1-CHINESE-X",  "chinese", "G1",  "TONGBIAN", "统编版·语文一年级下册"),
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文二年级上册.pdf":
        ("TONGBIAN-G2-CHINESE-S",  "chinese", "G2",  "TONGBIAN", "统编版·语文二年级上册"),
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文二年级下册.pdf":
        ("TONGBIAN-G2-CHINESE-X",  "chinese", "G2",  "TONGBIAN", "统编版·语文二年级下册"),
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文三年级上册.pdf":
        ("TONGBIAN-G3-CHINESE-S",  "chinese", "G3",  "TONGBIAN", "统编版·语文三年级上册"),
    "E_语文_（根据2022年版课程标准修订）义务教育教科书·语文三年级下册.pdf":
        ("TONGBIAN-G3-CHINESE-X",  "chinese", "G3",  "TONGBIAN", "统编版·语文三年级下册"),
    "E_语文_义务教育教科书·语文四年级上册.pdf":
        ("TONGBIAN-G4-CHINESE-S",  "chinese", "G4",  "TONGBIAN", "统编版·语文四年级上册"),
    "E_语文_义务教育教科书·语文四年级下册.pdf":
        ("TONGBIAN-G4-CHINESE-X",  "chinese", "G4",  "TONGBIAN", "统编版·语文四年级下册"),
    "E_语文_义务教育教科书·语文五年级上册.pdf":
        ("TONGBIAN-G5-CHINESE-S",  "chinese", "G5",  "TONGBIAN", "统编版·语文五年级上册"),
    "E_语文_义务教育教科书·语文五年级下册.pdf":
        ("TONGBIAN-G5-CHINESE-X",  "chinese", "G5",  "TONGBIAN", "统编版·语文五年级下册"),
    "E_语文_义务教育教科书·语文六年级上册.pdf":
        ("TONGBIAN-G6-CHINESE-S",  "chinese", "G6",  "TONGBIAN", "统编版·语文六年级上册"),
    "E_语文_义务教育教科书·语文六年级下册.pdf":
        ("TONGBIAN-G6-CHINESE-X",  "chinese", "G6",  "TONGBIAN", "统编版·语文六年级下册"),
    # 初中 7-9 年级（统编版）
    "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文七年级上册.pdf":
        ("TONGBIAN-G7-CHINESE-S",  "chinese", "G7",  "TONGBIAN", "统编版·语文七年级上册"),
    "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文七年级下册.pdf":
        ("TONGBIAN-G7-CHINESE-X",  "chinese", "G7",  "TONGBIAN", "统编版·语文七年级下册"),
    "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文八年级上册.pdf":
        ("TONGBIAN-G8-CHINESE-S",  "chinese", "G8",  "TONGBIAN", "统编版·语文八年级上册"),
    "M_语文_（根据2022年版课程标准修订）义务教育教科书·语文八年级下册.pdf":
        ("TONGBIAN-G8-CHINESE-X",  "chinese", "G8",  "TONGBIAN", "统编版·语文八年级下册"),
    "M_语文_义务教育教科书·语文九年级上册.pdf":
        ("TONGBIAN-G9-CHINESE-S",  "chinese", "G9",  "TONGBIAN", "统编版·语文九年级上册"),
    "M_语文_义务教育教科书·语文九年级下册.pdf":
        ("TONGBIAN-G9-CHINESE-X",  "chinese", "G9",  "TONGBIAN", "统编版·语文九年级下册"),
    # 高中（统编版）
    "H_语文_普通高中教科书·语文必修上册.pdf":
        ("TONGBIAN-G10-CHINESE-BXS",   "chinese", "G10", "TONGBIAN", "统编版·高中语文必修上册"),
    "H_语文_普通高中教科书·语文必修下册.pdf":
        ("TONGBIAN-G10-CHINESE-BXX",   "chinese", "G10", "TONGBIAN", "统编版·高中语文必修下册"),
    "H_语文_普通高中教科书·语文选择性必修上册.pdf":
        ("TONGBIAN-G11-CHINESE-SBXS",  "chinese", "G11", "TONGBIAN", "统编版·高中语文选择性必修上册"),
    "H_语文_普通高中教科书·语文选择性必修中册.pdf":
        ("TONGBIAN-G11-CHINESE-SBXM",  "chinese", "G11", "TONGBIAN", "统编版·高中语文选择性必修中册"),
    "H_语文_普通高中教科书·语文选择性必修下册.pdf":
        ("TONGBIAN-G12-CHINESE-SBXX",  "chinese", "G12", "TONGBIAN", "统编版·高中语文选择性必修下册"),

    # ━━━━━━━━━━━━━ 英语 ━━━━━━━━━━━━━
    # 小学 一年级起点 (PEP1)
    "E_英语_义务教育教科书·英语（一年级起点）三年级上册.pdf":
        ("PEP1-G3-ENGLISH-S",  "english", "G3",  "PEP1", "人教版英语（一年级起点）三年级上册"),
    "E_英语_义务教育教科书·英语（一年级起点）三年级下册.pdf":
        ("PEP1-G3-ENGLISH-X",  "english", "G3",  "PEP1", "人教版英语（一年级起点）三年级下册"),
    "E_英语_义务教育教科书·英语（一年级起点）四年级上册.pdf":
        ("PEP1-G4-ENGLISH-S",  "english", "G4",  "PEP1", "人教版英语（一年级起点）四年级上册"),
    "E_英语_义务教育教科书·英语（一年级起点）四年级下册.pdf":
        ("PEP1-G4-ENGLISH-X",  "english", "G4",  "PEP1", "人教版英语（一年级起点）四年级下册"),
    "E_英语_义务教育教科书·英语（一年级起点）五年级上册.pdf":
        ("PEP1-G5-ENGLISH-S",  "english", "G5",  "PEP1", "人教版英语（一年级起点）五年级上册"),
    "E_英语_义务教育教科书·英语（一年级起点）五年级下册.pdf":
        ("PEP1-G5-ENGLISH-X",  "english", "G5",  "PEP1", "人教版英语（一年级起点）五年级下册"),
    "E_英语_义务教育教科书·英语（一年级起点）六年级上册.pdf":
        ("PEP1-G6-ENGLISH-S",  "english", "G6",  "PEP1", "人教版英语（一年级起点）六年级上册"),
    "E_英语_义务教育教科书·英语（一年级起点）六年级下册.pdf":
        ("PEP1-G6-ENGLISH-X",  "english", "G6",  "PEP1", "人教版英语（一年级起点）六年级下册"),
    # 小学 三年级起点 PEP (PEP3)
    "E_英语_义务教育教科书·英语（PEP）（三年级起点）五年级上册.pdf":
        ("PEP3-G5-ENGLISH-S",  "english", "G5",  "PEP3", "人教版PEP英语（三年级起点）五年级上册"),
    "E_英语_义务教育教科书·英语（PEP）（三年级起点）六年级上册.pdf":
        ("PEP3-G6-ENGLISH-S",  "english", "G6",  "PEP3", "人教版PEP英语（三年级起点）六年级上册"),
    "E_英语_义务教育教科书·英语（三年级起点）五年级下册.pdf":
        ("PEP3-G5-ENGLISH-X",  "english", "G5",  "PEP3", "人教版PEP英语（三年级起点）五年级下册"),
    "E_英语_义务教育教科书·英语（三年级起点）六年级下册.pdf":
        ("PEP3-G6-ENGLISH-X",  "english", "G6",  "PEP3", "人教版PEP英语（三年级起点）六年级下册"),
    # 小学 精通版 (JINGTONG)
    "E_英语_义务教育教科书·英语（精通）（三年级起点）四年级上册.pdf":
        ("JINGTONG-G4-ENGLISH-S",  "english", "G4",  "JINGTONG", "人教精通版英语四年级上册"),
    "E_英语_义务教育教科书·英语（精通）（三年级起点）四年级下册.pdf":
        ("JINGTONG-G4-ENGLISH-X",  "english", "G4",  "JINGTONG", "人教精通版英语四年级下册"),
    "E_英语_义务教育教科书·英语（精通）（三年级起点）五年级上册.pdf":
        ("JINGTONG-G5-ENGLISH-S",  "english", "G5",  "JINGTONG", "人教精通版英语五年级上册"),
    "E_英语_义务教育教科书·英语（精通）（三年级起点）六年级上册.pdf":
        ("JINGTONG-G6-ENGLISH-S",  "english", "G6",  "JINGTONG", "人教精通版英语六年级上册"),
    # 小学 2022课标修订版 (PEP2022)
    "E_英语_（根据2022年版课程标准修订）义务教育教科书·英语三年级下册.pdf":
        ("PEP2022-G3-ENGLISH-X",  "english", "G3",  "PEP2022", "人教版PEP英语2022修订·三年级下册"),
    "E_英语_（根据2022年版课程标准修订）义务教育教科书·英语（PEP）四年级上册.pdf":
        ("PEP2022-G4-ENGLISH-S",  "english", "G4",  "PEP2022", "人教版PEP英语2022修订·四年级上册"),
    "E_英语_（根据2022年版课程标准修订）义务教育教科书·英语四年级下册.pdf":
        ("PEP2022-G4-ENGLISH-X",  "english", "G4",  "PEP2022", "人教版PEP英语2022修订·四年级下册"),
    # 初中（人教版 2022修订）
    "M_英语_（根据2022年版课程标准修订）义务教育教科书·英语七年级下册.pdf":
        ("RENJIAO-G7-ENGLISH-X",   "english", "G7",  "RENJIAO", "人教版英语七年级下册"),
    "M_英语_（根据2022年版课程标准修订）义务教育教科书·英语八年级上册.pdf":
        ("RENJIAO-G8-ENGLISH-S",   "english", "G8",  "RENJIAO", "人教版英语八年级上册"),
    "M_英语_（根据2022年版课程标准修订）义务教育教科书·英语八年级下册.pdf":
        ("RENJIAO-G8-ENGLISH-X",   "english", "G8",  "RENJIAO", "人教版英语八年级下册"),
    "M_英语_义务教育教科书·英语九年级全一册.pdf":
        ("RENJIAO-G9-ENGLISH-QYC", "english", "G9",  "RENJIAO", "人教版英语九年级全一册"),
    # 高中（人教版 2022新课标）
    "H_英语_普通高中教科书·英语必修第一册.pdf":
        ("RENJIAO-G10-ENGLISH-BX1",  "english", "G10", "RENJIAO", "人教版高中英语必修第一册"),
    "H_英语_普通高中教科书·英语必修第二册.pdf":
        ("RENJIAO-G10-ENGLISH-BX2",  "english", "G10", "RENJIAO", "人教版高中英语必修第二册"),
    "H_英语_普通高中教科书·英语必修第三册.pdf":
        ("RENJIAO-G11-ENGLISH-BX3",  "english", "G11", "RENJIAO", "人教版高中英语必修第三册"),
    "H_英语_普通高中教科书·英语选择性必修第一册.pdf":
        ("RENJIAO-G11-ENGLISH-SBX1", "english", "G11", "RENJIAO", "人教版高中英语选择性必修第一册"),
    "H_英语_普通高中教科书·英语选择性必修第二册.pdf":
        ("RENJIAO-G11-ENGLISH-SBX2", "english", "G11", "RENJIAO", "人教版高中英语选择性必修第二册"),
    "H_英语_普通高中教科书·英语选择性必修第三册.pdf":
        ("RENJIAO-G12-ENGLISH-SBX3", "english", "G12", "RENJIAO", "人教版高中英语选择性必修第三册"),
    "H_英语_普通高中教科书·英语选择性必修第四册.pdf":
        ("RENJIAO-G12-ENGLISH-SBX4", "english", "G12", "RENJIAO", "人教版高中英语选择性必修第四册"),

    # ━━━━━━━━━━━━━ 物理 ━━━━━━━━━━━━━
    # 初中（人教版 2022修订）
    "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理八年级上册.pdf":
        ("RENJIAO-G8-PHYSICS-S",    "physics", "G8",  "RENJIAO", "人教版物理八年级上册"),
    "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理八年级下册.pdf":
        ("RENJIAO-G8-PHYSICS-X",    "physics", "G8",  "RENJIAO", "人教版物理八年级下册"),
    "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理九年级全一册.pdf":
        ("RENJIAO-G9-PHYSICS-QYC",  "physics", "G9",  "RENJIAO", "人教版物理九年级全一册"),
    # 高中（人教版 2022新课标）
    "H_物理_普通高中教科书·物理必修第一册.pdf":
        ("RENJIAO-G10-PHYSICS-BX1",  "physics", "G10", "RENJIAO", "人教版高中物理必修第一册"),
    "H_物理_普通高中教科书·物理必修第二册.pdf":
        ("RENJIAO-G10-PHYSICS-BX2",  "physics", "G10", "RENJIAO", "人教版高中物理必修第二册"),
    "H_物理_普通高中教科书·物理必修第三册.pdf":
        ("RENJIAO-G11-PHYSICS-BX3",  "physics", "G11", "RENJIAO", "人教版高中物理必修第三册"),
    "H_物理_普通高中教科书·物理选择性必修第一册.pdf":
        ("RENJIAO-G11-PHYSICS-SBX1", "physics", "G11", "RENJIAO", "人教版高中物理选择性必修第一册"),
    "H_物理_普通高中教科书·物理选择性必修第二册.pdf":
        ("RENJIAO-G11-PHYSICS-SBX2", "physics", "G11", "RENJIAO", "人教版高中物理选择性必修第二册"),
    "H_物理_普通高中教科书·物理选择性必修第三册.pdf":
        ("RENJIAO-G12-PHYSICS-SBX3", "physics", "G12", "RENJIAO", "人教版高中物理选择性必修第三册"),

    # ━━━━━━━━━━━━━ 历史 ━━━━━━━━━━━━━
    # 初中（统编版 2022修订）
    "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史七年级上册.pdf":
        ("TONGBIAN-G7-HISTORY-CN-S", "history", "G7",  "TONGBIAN", "统编版·中国历史七年级上册"),
    "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史七年级下册.pdf":
        ("TONGBIAN-G7-HISTORY-CN-X", "history", "G7",  "TONGBIAN", "统编版·中国历史七年级下册"),
    "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史八年级上册.pdf":
        ("TONGBIAN-G8-HISTORY-CN-S", "history", "G8",  "TONGBIAN", "统编版·中国历史八年级上册"),
    "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史八年级下册.pdf":
        ("TONGBIAN-G8-HISTORY-CN-X", "history", "G8",  "TONGBIAN", "统编版·中国历史八年级下册"),
    "M_历史_义务教育教科书·世界历史九年级上册.pdf":
        ("TONGBIAN-G9-HISTORY-WD-S", "history", "G9",  "TONGBIAN", "统编版·世界历史九年级上册"),
    "M_历史_义务教育教科书·世界历史九年级下册.pdf":
        ("TONGBIAN-G9-HISTORY-WD-X", "history", "G9",  "TONGBIAN", "统编版·世界历史九年级下册"),
    # 高中（统编版）
    "H_历史_普通高中教科书·历史必修中外历史纲要（上）.pdf":
        ("TONGBIAN-G10-HISTORY-BXS",  "history", "G10", "TONGBIAN", "统编版·高中历史必修·中外历史纲要上"),
    "H_历史_普通高中教科书·历史必修中外历史纲要（下）.pdf":
        ("TONGBIAN-G10-HISTORY-BXX",  "history", "G10", "TONGBIAN", "统编版·高中历史必修·中外历史纲要下"),
    "H_历史_普通高中教科书·历史选择性必修1国家制度与社会治理.pdf":
        ("TONGBIAN-G11-HISTORY-SBX1", "history", "G11", "TONGBIAN", "统编版·高中历史选择性必修1·国家制度与社会治理"),
    "H_历史_普通高中教科书·历史选择性必修2经济与社会生活.pdf":
        ("TONGBIAN-G11-HISTORY-SBX2", "history", "G11", "TONGBIAN", "统编版·高中历史选择性必修2·经济与社会生活"),
    "H_历史_普通高中教科书·历史选择性必修3文化交流与传播.pdf":
        ("TONGBIAN-G12-HISTORY-SBX3", "history", "G12", "TONGBIAN", "统编版·高中历史选择性必修3·文化交流与传播"),
}

# 这批旧 stub 没有 KU/文件/用户引用，统一清理后重建
OBSOLETE_IDS = [
    # 旧版物理选修（已被2022新课标替代，未下载）
    "RENJIAO-G12-PHYSICS-XX1-1", "RENJIAO-G12-PHYSICS-XX1-2",
    "RENJIAO-G12-PHYSICS-XX2-1", "RENJIAO-G12-PHYSICS-XX2-2", "RENJIAO-G12-PHYSICS-XX2-3",
    "RENJIAO-G12-PHYSICS-XX3-1", "RENJIAO-G12-PHYSICS-XX3-2", "RENJIAO-G12-PHYSICS-XX3-3",
    "RENJIAO-G12-PHYSICS-XX3-4", "RENJIAO-G12-PHYSICS-XX3-5",
    # 旧版语文（RENJIAO 编，实为统编版，新 ID 改为 TONGBIAN）
    "RENJIAO-G1-CHINESE-S", "RENJIAO-G1-CHINESE-X",
    "RENJIAO-G8-CHINESE-S", "RENJIAO-G8-CHINESE-X",
    "RENJIAO-G10-CHINESE-BX1", "RENJIAO-G10-CHINESE-BX2",
    "RENJIAO-G11-CHINESE-BX3", "RENJIAO-G11-CHINESE-BX4",
    "RENJIAO-G12-CHINESE-XX-ZHUZI", "RENJIAO-G12-CHINESE-BX5",
    "RENJIAO-G12-CHINESE-XX-CHUANJI", "RENJIAO-G12-CHINESE-XX-XIQU",
    "RENJIAO-G12-CHINESE-XX-XIEZUO", "RENJIAO-G12-CHINESE-XX-YINGSHI",
    "RENJIAO-G12-CHINESE-XX-WGSHIGE", "RENJIAO-G12-CHINESE-XX-WENHUA",
    "RENJIAO-G12-CHINESE-XX-MINSHU", "RENJIAO-G12-CHINESE-XX-WGXIAOSHUO",
    "RENJIAO-G12-CHINESE-XX-GDSHIGE", "RENJIAO-G12-CHINESE-XX-ZGXIAOSHUO",
    "RENJIAO-G12-CHINESE-XX-YUYAN", "RENJIAO-G12-CHINESE-XX-YANJIANG",
    "RENJIAO-G12-CHINESE-XX-XINWEN", "TONGBIAN-G9-CHINESE-X",
    "RENJIAO-HS-CHINESE-XX-XIAOSHUO",
    # 旧版英语（各种已废旧 stub）
    "XINQIDIAN-G1-ENGLISH-S", "XINQIDIAN-G1-ENGLISH-X",
    "XINQIDIAN-G2-ENGLISH-S", "XINQIDIAN-G2-ENGLISH-X",
    "XINQIDIAN-G3-ENGLISH-S", "XINQIDIAN-G3-ENGLISH-X",
    "XINQIDIAN-G4-ENGLISH-S", "XINQIDIAN-G4-ENGLISH-X",
    "XINQIDIAN-G5-ENGLISH-S", "XINQIDIAN-G5-ENGLISH-X",
    "XINQIDIAN-G6-ENGLISH-S", "XINQIDIAN-G6-ENGLISH-X",
    "BEISHIDA-G7-ENGLISH-S", "WAIYAN-G7-ENGLISH-S", "WAIYAN-G8-ENGLISH-S",
    "RENJIAO-G7-ENGLISH-S",  # 七年级上册未下载，去掉 stub
    "RENJIAO-G10-ENGLISH-BX1", "RENJIAO-G10-ENGLISH-BX2",
    "RENJIAO-G11-ENGLISH-BX3", "RENJIAO-G11-ENGLISH-BX4",
    "RENJIAO-G12-ENGLISH-XX6", "RENJIAO-G12-ENGLISH-XX7", "RENJIAO-G12-ENGLISH-XX8",
    "RENJIAO-G12-ENGLISH-XX9", "RENJIAO-G12-ENGLISH-XX10", "RENJIAO-G12-ENGLISH-XX11",
    "RENJIAO-G12-ENGLISH-XX-YUFA", "RENJIAO-G12-ENGLISH-BX5",
    "RENJIAO-HS-ENGLISH-XX-XIEZUO",
]


def tf_id(textbook_id: str, filename: str) -> str:
    h = hashlib.sha1(f"{textbook_id}:{filename}".encode()).hexdigest()[:8]
    return f"tf-{h}"


def run() -> None:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 1. 删除废旧 stubs
    if OBSOLETE_IDS:
        cur.execute(
            "DELETE FROM textbooks WHERE id = ANY(%s)",
            (OBSOLETE_IDS,)
        )
        print(f"  清理旧 stub: {cur.rowcount} 条")

    inserted_tb = updated_tb = skipped_tf = inserted_tf = 0

    for filename, (tb_id, subject, grade, edition, book_name) in MAPPING.items():
        pdf_path = STANDARDS_DIR / filename
        if not pdf_path.exists():
            print(f"  [跳过] 文件不存在: {filename}")
            continue

        file_size = pdf_path.stat().st_size

        # 2. Upsert textbook
        cur.execute("""
            INSERT INTO textbooks (id, subject, grade, edition, book_name)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET subject   = EXCLUDED.subject,
                  grade     = EXCLUDED.grade,
                  edition   = EXCLUDED.edition,
                  book_name = EXCLUDED.book_name
        """, (tb_id, subject, grade, edition, book_name))
        if cur.rowcount == 1:
            inserted_tb += 1
        else:
            updated_tb += 1

        # 3. Insert textbook_file（幂等：以 storage_path 为去重键）
        storage_path = f"curriculum_standards/{filename}"
        cur.execute("SELECT id FROM textbook_files WHERE storage_path = %s", (storage_path,))
        if cur.fetchone():
            skipped_tf += 1
            continue

        fid = tf_id(tb_id, filename)
        cur.execute("""
            INSERT INTO textbook_files
              (id, textbook_id, owner_student_id, filename, file_type,
               storage_path, file_size, has_text_layer)
            VALUES (%s, %s, NULL, %s, 'pdf', %s, %s, TRUE)
            ON CONFLICT (id) DO NOTHING
        """, (fid, tb_id, filename, storage_path, file_size))
        inserted_tf += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"  textbooks: +{inserted_tb} 新增 / {updated_tb} 更新")
    print(f"  textbook_files: +{inserted_tf} 新增 / {skipped_tf} 已存在跳过")


if __name__ == "__main__":
    print("→ 入库语文/英语/物理/历史教材…")
    run()
    print("完成。")
