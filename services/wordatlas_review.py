"""wordatlas_review.py — Word Atlas 词汇四题型接线（集成-2，A+B 接线）。

只做接线，不重实现算法：
- 队列：复用 services.wordatlas_fsrs.build_review_queue（先到期最久逾期
  在前、再 5 个一组新学项）；本层只加队列过滤（short-weight 排除）。
- 评分：复用 map_gap_drill_to_rating（答错→Again、答对但慢或用提示→Hard、
  答对→Good、又快又对→Easy）；skip / 自评返回 None，本层入口短路，
  禁止任何默认分支落到 Again（集成定案：skip 不计分）。
- 调度：复用 apply_review（同轮重答幂等，review_id 默认
  gap:{session_id}:{ku}，ku 取卡 key vocab-wa-<vocab_id>）。
- 掌握裁决：BKT 仍是唯一裁决源；本模块只读写 FSRS 卡片状态
  （S/D/due/last_review/review_count），绝不写 p_mastery 或
  mastery_confirmed；is_mastered（稳定度 >= 21 天）仅作展示参考。

DB 层（本文件后半部分）只用 DBAPI 连接（psycopg2 风格 %s 占位符），
不 import 任何 ORM；学生作用域用 student_key TEXT（空串 = 未分学习者
测试通道，生产调用方传入学生 uuid 字符串），避免 NULL 在唯一约束里
不触发冲突的老坑。vocab_units 仍是只读参考表，本层绝不写回它。

署名（凡用到 word-atlas 口径处）：Word Atlas contributors — CC BY 4.0
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Optional, Sequence

from services.wordatlas_fsrs import (
    FSRSState,
    Rating,
    apply_review,
    build_review_queue,
    from_dict,
    is_mastered,
    map_gap_drill_to_rating,
    to_dict,
)

WORD_ATLAS_ATTRIBUTION = "Word Atlas contributors — CC BY 4.0"

# ── 四题型（设计说明 §3，不新发明题型）──
QUESTION_TYPE_CHOICE = "choice"  # 选义：看英文选中文
QUESTION_TYPE_PICTURE = "picture"  # 看图补句：插画 + 挖空 ex[0]
QUESTION_TYPE_LISTENING = "listening"  # 听音辨词：只放音频、不给文字
QUESTION_TYPE_SPELLING = "spelling"  # 拼写：看图 + 释义拼写
QUESTION_TYPES = (
    QUESTION_TYPE_CHOICE,
    QUESTION_TYPE_PICTURE,
    QUESTION_TYPE_LISTENING,
    QUESTION_TYPE_SPELLING,
)
QUESTION_TYPE_NAMES = {
    QUESTION_TYPE_CHOICE: "选义",
    QUESTION_TYPE_PICTURE: "看图补句",
    QUESTION_TYPE_LISTENING: "听音辨词",
    QUESTION_TYPE_SPELLING: "拼写",
}

# ── 队列过滤层（集成-3 交代取舍 ①）──
# short-weight：C2 罕用形式，note 原样保留、cefr/topic/note 一律不动；
# 只在队列过滤层排除，使其永不进入每日新词队列与复习队列。
QUEUE_EXCLUDED_VOCAB_IDS = frozenset({"short-weight"})

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

# 媒体位（与 vocab_media_availability.media_mask 生成列一致）：
# img=1, thumb=2, uk=4, us=8, ex=16, ex2=32。
MEDIA_BIT_IMG = 1
MEDIA_BIT_THUMB = 2
MEDIA_BIT_UK = 4
MEDIA_BIT_US = 8
MEDIA_BIT_EX = 16
MEDIA_BIT_EX2 = 32


def card_key(vocab_id: str) -> str:
    """进度键命名空间：vocab-wa-<vocab_units.id>（设计说明 §4）。"""
    return f"vocab-wa-{vocab_id}"


def vocab_id_of_key(key: str) -> str:
    """card_key 的逆操作；非本命名空间的 key 原样返回。"""
    return key[len("vocab-wa-"):] if key.startswith("vocab-wa-") else key


def is_queue_excluded(vocab_id: str) -> bool:
    return vocab_id in QUEUE_EXCLUDED_VOCAB_IDS


# ── syn 词性后缀（集成-3 交代取舍 ②）──
# jail/rally 的 syn 经补丁带 "(pos.)" 后缀（如 "prison (n.)"），与 family
# 同格式。出题层展示前必须剥离后缀，且不得跨词性取 syn：n. 义项只取
# (n.) 后缀项，v. 义项只取 (v.) 项。无后缀的 plain syn 无法判定词性，
# 原样保留，不得凭空删词（删词是补丁文件的活，不是出题层的活）。
_POS_SUFFIX_RE = re.compile(r"^(?P<word>.*?)\s*\((?P<pos>[A-Za-z]+)\.?\)\s*$")


def _normalize_pos(pos: Optional[str]) -> Optional[str]:
    if pos is None:
        return None
    return pos.strip().lower().rstrip(".")


def strip_pos_suffix(token: str) -> tuple[str, Optional[str]]:
    """剥离 syn/family 词条的词性后缀，返回（词，词性或 None）。"""
    match = _POS_SUFFIX_RE.match(token.strip())
    if match is None:
        return token.strip(), None
    return match.group("word").strip(), _normalize_pos(match.group("pos"))


def syn_for_pos(syn_tokens: Sequence[str], pos: str) -> list[str]:
    """取与目标义项同词性的 syn，展示前已剥离后缀。

    pos 取 senses[].pos 的写法（如 "n." / "v."），内部归一化比较。
    后缀词性不符的项排除；无后缀项保留（无法判定跨词性，不擅自删）。
    """
    want = _normalize_pos(pos)
    out: list[str] = []
    for token in syn_tokens:
        word, token_pos = strip_pos_suffix(token)
        if token_pos is None or token_pos == want:
            out.append(word)
    return out


# ── 复习队列（过滤层 + 复用 build_review_queue）──
def build_word_atlas_queue(
    cards: Iterable[FSRSState],
    now: datetime,
    *,
    group_size: int = 5,
) -> dict:
    """组装一轮 Word Atlas 复习队列。

    先在过滤层排除 QUEUE_EXCLUDED_VOCAB_IDS（按卡 key 反推 vocab_id），
    再原样委托 build_review_queue：到期项在前（最久逾期最前）、
    新学项按传入顺序取 group_size 个一组。未到期项单列 upcoming。
    """
    filtered = [
        card
        for card in cards
        if not is_queue_excluded(vocab_id_of_key(card.key))
    ]
    return build_review_queue(filtered, now, group_size=group_size)


# ── 四题型评分（入口短路：None 绝不落到 Again）──
def grade_vocab_answer(question_type: str, answer: dict) -> Optional[Rating]:
    """四题型一次作答 → FSRS 四档；skip / 自评返回 None（不计分）。

    映射与 gap drill 完全一致（map_gap_drill_to_rating）：
    答错→Again；答对但慢（>=30 秒）或用提示→Hard；答对→Good；
    又快又对（<=3 秒）→Easy。question_type 只校验题型合法性，
    不改变映射（四题型共用同一评分口径，见设计说明 §4）。
    """
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"未知题型：{question_type!r}")
    return map_gap_drill_to_rating(answer)


def submit_vocab_answer(
    card: FSRSState,
    question_type: str,
    answer: dict,
    now: datetime,
    *,
    session_id: Optional[str] = None,
    review_id: Optional[str] = None,
    applied_ids: Optional[set[str]] = None,
) -> tuple[FSRSState, Optional[Rating], bool, Optional[set[str]]]:
    """提交一次四题型作答，返回（卡，档位，是否本次计分，id 集）。

    None 短路：skip / 自评时直接返回原卡不动、applied=False，
    且不占用 review_id——同一节里该词的真实作答仍可计分
    （跳过不消耗本轮第一次作答资格，见 skip 口径补丁）。
    计分时 review_id 默认 gap:{session_id}:{卡 key}，同轮重答
    （即使换题型、即使这次答对）返回原卡不动、applied=False。
    """
    rating = grade_vocab_answer(question_type, answer)
    if rating is None:
        return (
            card,
            None,
            False,
            applied_ids if applied_ids is None else set(applied_ids),
        )
    rid = review_id
    if rid is None and session_id is not None:
        rid = f"gap:{session_id}:{card.key}"
    new_card, applied, updated = apply_review(
        card, rating, now, review_id=rid, applied_ids=applied_ids
    )
    return new_card, rating, applied, updated


# ── 媒体可用性（出题降级门禁，位定义与附表生成列一致）──
def media_mask(media: dict) -> int:
    """由 6 个布尔位算 media_mask（与附表生成列同一口径）。"""
    mask = 0
    if media.get("has_img"):
        mask |= MEDIA_BIT_IMG
    if media.get("has_thumb"):
        mask |= MEDIA_BIT_THUMB
    if media.get("has_audio_uk"):
        mask |= MEDIA_BIT_UK
    if media.get("has_audio_us"):
        mask |= MEDIA_BIT_US
    if media.get("has_audio_ex"):
        mask |= MEDIA_BIT_EX
    if media.get("has_audio_ex2"):
        mask |= MEDIA_BIT_EX2
    return mask


def choose_question_type(
    requested: str, media: dict, *, accent: str = "uk"
) -> str:
    """按媒体可用性决定实际题型；缺媒体时降级为选义，绝不出无声/无图题。

    - 听音辨词：按学生口音偏好（uk/us）取对应音频位；无该口音音频时
      降级为选义（不得静默出无声听音题）。
    - 看图补句：无插画时降级为选义。
    - 选义、拼写：不依赖媒体位（拼写提示图缺失时仍可用释义作提示），
      原样放行。
    """
    if requested not in QUESTION_TYPES:
        raise ValueError(f"未知题型：{requested!r}")
    if requested == QUESTION_TYPE_LISTENING:
        key = "has_audio_uk" if accent == "uk" else "has_audio_us"
        if not media.get(key):
            return QUESTION_TYPE_CHOICE
    if requested == QUESTION_TYPE_PICTURE and not media.get("has_img"):
        return QUESTION_TYPE_CHOICE
    return requested


# ── DB 层（纯 SQL，不写 vocab_units；只读写 word_atlas_fsrs_cards）──
def row_to_card(row: dict) -> FSRSState:
    """卡片行 → FSRSState。优先用 fsrs_card_json（A 线 to_dict 口径），
    缺失时由分列（S/D/due/last_review/review_count）重建。"""
    stored = row.get("fsrs_card_json")
    if isinstance(stored, dict) and stored:
        card = from_dict(stored)
        if not card.key:
            card.key = card_key(str(row["vocab_id"]))
        return card
    return FSRSState(
        key=card_key(str(row["vocab_id"])),
        stability=row.get("stability"),
        difficulty=row.get("difficulty"),
        due=row.get("due"),
        last_review=row.get("last_review"),
        review_count=int(row.get("review_count") or 0),
    )


def load_card(conn, vocab_id: str, student_key: str = "") -> tuple[FSRSState, set[str]]:
    """读一张卡；无行时返回新卡与空 id 集（不写库）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vocab_id, stability, difficulty, due, last_review,"
            " review_count, fsrs_card_json, applied_review_ids"
            " FROM word_atlas_fsrs_cards"
            " WHERE student_key = %s AND vocab_id = %s",
            (student_key, vocab_id),
        )
        row = cur.fetchone()
    if row is None:
        return FSRSState(key=card_key(vocab_id)), set()
    # psycopg2 默认游标返回 tuple：按 SELECT 列顺序重建。
    data = {
        "vocab_id": row[0],
        "stability": row[1],
        "difficulty": row[2],
        "due": row[3],
        "last_review": row[4],
        "review_count": row[5],
        "fsrs_card_json": row[6],
        "applied_review_ids": row[7],
    }
    return row_to_card(data), set(data["applied_review_ids"] or [])


def save_card(
    conn,
    vocab_id: str,
    card: FSRSState,
    applied_ids: Optional[set[str]],
    student_key: str = "",
) -> None:
    """写回一张卡（UPSERT）：分列 + fsrs_card_json 镜像 + 幂等 id 集。"""
    payload = to_dict(card)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO word_atlas_fsrs_cards"
            " (student_key, vocab_id, stability, difficulty, due,"
            "  last_review, review_count, fsrs_card_json,"
            "  applied_review_ids, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())"
            " ON CONFLICT (student_key, vocab_id) DO UPDATE SET"
            "  stability = EXCLUDED.stability,"
            "  difficulty = EXCLUDED.difficulty,"
            "  due = EXCLUDED.due,"
            "  last_review = EXCLUDED.last_review,"
            "  review_count = EXCLUDED.review_count,"
            "  fsrs_card_json = EXCLUDED.fsrs_card_json,"
            "  applied_review_ids = EXCLUDED.applied_review_ids,"
            "  updated_at = now()",
            (
                student_key,
                vocab_id,
                card.stability,
                card.difficulty,
                card.due,
                card.last_review,
                card.review_count,
                json.dumps(payload),
                sorted(applied_ids or []),
            ),
        )
    conn.commit()


def fetch_review_queue(
    conn,
    now: datetime,
    *,
    student_key: str = "",
    cefr: Optional[str] = None,
    group_size: int = 5,
) -> dict:
    """只读：从测试库取一轮复习队列。

    新词候选顺序：CEFR 层由低到高、同层按 word 排序（学习路线起点
    难度开始取未学词）；到期排序与分组口径委托 build_word_atlas_queue。
    short-weight 排除在 Python 过滤层（不在 SQL WHERE 里），见上。
    返回的 queue/due/new_batch/upcoming 条目为
    {vocab_id, word, cefr, card, media}，另附 due/new 计数。
    """
    sql = (
        "SELECT v.id, v.word, v.cefr, c.stability, c.difficulty, c.due,"
        " c.last_review, c.review_count, c.fsrs_card_json,"
        " m.has_img, m.has_thumb, m.has_audio_uk, m.has_audio_us,"
        " m.has_audio_ex, m.has_audio_ex2"
        " FROM vocab_units v"
        " LEFT JOIN word_atlas_fsrs_cards c"
        "   ON c.vocab_id = v.id AND c.student_key = %s"
        " LEFT JOIN vocab_media_availability m ON m.id = v.id"
    )
    params: list = [student_key]
    if cefr is not None:
        sql += " WHERE v.cefr = %s"
        params.append(cefr)
    sql += (
        " ORDER BY CASE v.cefr"
        "  WHEN 'A1' THEN 0 WHEN 'A2' THEN 1 WHEN 'B1' THEN 2"
        "  WHEN 'B2' THEN 3 WHEN 'C1' THEN 4 WHEN 'C2' THEN 5 ELSE 6 END,"
        " v.word"
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    states: list[FSRSState] = []
    info: dict[str, dict] = {}
    for row in rows:
        vocab_id, word, cefr_value = row[0], row[1], row[2]
        card = row_to_card(
            {
                "vocab_id": vocab_id,
                "stability": row[3],
                "difficulty": row[4],
                "due": row[5],
                "last_review": row[6],
                "review_count": row[7],
                "fsrs_card_json": row[8],
            }
        )
        states.append(card)
        info[card.key] = {
            "vocab_id": vocab_id,
            "word": word,
            "cefr": cefr_value,
            "card": card,
            "media": {
                "has_img": bool(row[9]),
                "has_thumb": bool(row[10]),
                "has_audio_uk": bool(row[11]),
                "has_audio_us": bool(row[12]),
                "has_audio_ex": bool(row[13]),
                "has_audio_ex2": bool(row[14]),
            },
        }
    built = build_word_atlas_queue(states, now, group_size=group_size)
    out = dict(built)
    for name in ("queue", "due", "new_batch", "new_remaining", "upcoming"):
        out[name] = [info[card.key] for card in built[name]]
    return out


def answer_question(
    conn,
    vocab_id: str,
    question_type: str,
    answer: dict,
    now: datetime,
    *,
    session_id: Optional[str] = None,
    review_id: Optional[str] = None,
    student_key: str = "",
) -> dict:
    """四题型作答 → 评分 → FSRS 调度 → 下次 due 写回（一站式接线）。

    skip / 自评：返回 rating None、applied False，不写库（卡片状态、
    幂等 id 集原样保留）。同轮重答：applied False，不写库。
    计分成功：写回卡片 + 幂等 id 集。BKT 掌握裁决不在此写。
    """
    card, applied_ids = load_card(conn, vocab_id, student_key)
    new_card, rating, applied, updated = submit_vocab_answer(
        card,
        question_type,
        answer,
        now,
        session_id=session_id,
        review_id=review_id,
        applied_ids=applied_ids,
    )
    if applied:
        save_card(conn, vocab_id, new_card, updated, student_key)
    return {
        "vocab_id": vocab_id,
        "question_type": question_type,
        "question_type_name": QUESTION_TYPE_NAMES[question_type],
        "rating": rating.name if rating is not None else None,
        "applied": applied,
        "stability": new_card.stability,
        "difficulty": new_card.difficulty,
        "due": new_card.due.isoformat() if new_card.due else None,
        "review_count": new_card.review_count,
        "is_mastered": is_mastered(new_card),
    }
