r"""services/vocab_meaning.py — 「这句中文到底是释义还是读音」的**唯一判定源**

存在的理由：一个真实且**双向**的静默错误。

教材词表把两类东西写进同一个 `canonical_meaning` 列：

- **音标**：`[ˈeərən]`、`[æfˈɡænɪstɑːn]` —— 是读音，不是释义；
- **带方括号义项标签的释义**：`[法] 法案`、`[天] 十月`、`(使)远离，(使)不接近`。

所以**「以 `[（(` 开头」根本不能判定是音标**。实测（2026-10-03，全表）：

| 类别 | 行数 |
|---|---|
| 以 `[（(` 开头的 `canonical_meaning` | 9,855 |
| 其中**无汉字** → 真音标 | **9,844** |
| 其中**有汉字** → 是释义，被旧规则误拒 | **11** |

误拒的 11 条里有 `[人名] 齐珀`、`[口语]再见!`、`(使)远离…`、`（等于the United
Kingdom）英国`、`won't → [澳大利亚、新西兰口语]厌恶`。旧规则
（`scripts/derive_meaning_from_canonical.py` 里的 `r"^[\[（(]"`）把它们当音标丢掉，
其中 11 条至今 `meaning_cn` 仍为空 —— 不是被正确拒绝，是被**误判**。

唯一判据：**括号开头 且 内部无汉字** → 读音。加一条极窄的兜底：括号里整体只是
一个音标标记词（`（音标）`）。必须限长，否则会误杀「发音」一词自己的正常释义
`n. 发音；读法`（生产里确有此行）。

本模块是 `derive_meaning_from_canonical.derive()` 与 Context Retriever 的共同依赖，
避免出现两个互相矛盾的判定（那正是单源红线要防的漂移）。

**本模块只判定，不修数据。** 那 11 条要不要回填是独立决策（见 TASKS CME-P1.5）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 教材词表的占位符 —— 没有内容可派生。
PLACEHOLDERS = frozenset(
    {"", "无", "-", "—", "/", "n/a", "N/A", "null", "NULL"}
)

# 义项/领域标签前缀：[法] [天] [计] [食品] [家具] [外科] [地理] [物] …
_BRACKET_PREFIX = re.compile(r"^[\[（(]")

# 汉字（含扩展区）。ASCII 假名/注音假名不算 —— 那些也是读音。
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# 括号内**整体只是**一个「这是音标」的标记词（`（音标）`/`（读音）`）。
# 用「整体等于」而不是「包含 + 限长」—— 后者是我第一版的写法，它防的是一个生产里
# 并不存在的场景（实测 0 行 `（音标）` 标记），而且我写的测试根本碰不到那个分支，
# 变异验证时才发现：删掉长度限制，41 项测试全绿。改成精确匹配后意图可被测。
_PHONETIC_MARKERS = frozenset({"音标", "读音", "发音", "phonetic", "ipa"})

# 判定档位。
TIER_CANONICAL = "canonical"  # meaning_cn 有可信释义 —— 权威
TIER_LEGACY = "legacy"        # 只有 canonical_meaning 能给出释义 —— 可用但未派生
TIER_UNUSABLE = "unusable"    # 音标 / 占位符 / 空 —— 绝不可当释义用

KIND_GLOSS = "gloss"
KIND_PHONETIC = "phonetic"
KIND_PLACEHOLDER = "placeholder"
KIND_MISSING = "missing"


@dataclass(frozen=True)
class MeaningVerdict:
    """判定结果。``gloss`` 非空**当且仅当**它可当释义用。"""

    tier: str
    kind: str
    gloss: str | None
    source_column: str | None
    reason: str

    @property
    def usable(self) -> bool:
        return bool(self.gloss)

    def to_payload(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "kind": self.kind,
            "gloss": self.gloss,
            "source_column": self.source_column,
            "reason": self.reason,
        }


def is_phonetic_transcription(text: str | None) -> bool:
    """这个字符串是读音而不是中文释义吗？

    判据：**括号开头 且 内部无汉字**（+ 极窄的音标标记词兜底）。
    只看「括号开头」会把 `[法] 法案`、`(使)远离` 误判成音标 —— 生产里这类
    带义项标签的释义有 11 条曾因此被丢掉。
    """
    t = (text or "").strip()
    if not t:
        return False
    if not _BRACKET_PREFIX.match(t):
        return False
    if not _CJK.search(t):
        return True
    inner = _BRACKET_PREFIX.sub("", t).strip("]）) ").strip().lower()
    return inner in _PHONETIC_MARKERS


def classify_canonical_meaning(canonical_meaning: str | None) -> MeaningVerdict:
    """判定 `canonical_meaning` 这一列本身。**不**在这里做词性解析/义项清理
    （那是 `derive_meaning_from_canonical.derive()` 的事，判定与派生分开）。"""
    t = (canonical_meaning or "").strip()
    if not t:
        return MeaningVerdict(TIER_UNUSABLE, KIND_MISSING, None, None, "canonical_meaning 为空")
    if t in PLACEHOLDERS:
        return MeaningVerdict(
            TIER_UNUSABLE, KIND_PLACEHOLDER, None, None, f"canonical_meaning 是占位符 {t!r}"
        )
    if is_phonetic_transcription(t):
        return MeaningVerdict(
            TIER_UNUSABLE,
            KIND_PHONETIC,
            None,
            None,
            "canonical_meaning 括号开头且内部无汉字 → 读音（音标），不是释义",
        )
    return MeaningVerdict(TIER_LEGACY, KIND_GLOSS, t, "canonical_meaning", "可作释义（未派生）")


def classify_meaning_source(
    *, meaning_cn: str | None, canonical_meaning: str | None
) -> MeaningVerdict:
    """决定「这个词的释义取自哪一列」，并给出可信档位。

    优先级：`meaning_cn`（权威，已由受审计的派生/生成路径写入）→
    `canonical_meaning`（legacy，未派生）。**任何情况下都不会返回音标**。

    这是 Context Retriever 的唯一入口：LLM 拿到的 `meaning_cn` 一定不是读音。
    """
    mc = (meaning_cn or "").strip()
    if mc:
        if is_phonetic_transcription(mc):
            # meaning_cn 自身被污染 —— 实测全表 0 条，但**必须**挡住：
            # 这一列是要给孩子背的，宁可判成无可用释义也不能把音标当中文意思。
            return MeaningVerdict(
                TIER_UNUSABLE,
                KIND_PHONETIC,
                None,
                "meaning_cn",
                "meaning_cn 疑似音标（污染），已拒用",
            )
        return MeaningVerdict(TIER_CANONICAL, KIND_GLOSS, mc, "meaning_cn", "meaning_cn 可信释义")

    return classify_canonical_meaning(canonical_meaning)


__all__ = [
    "KIND_GLOSS",
    "KIND_MISSING",
    "KIND_PHONETIC",
    "KIND_PLACEHOLDER",
    "PLACEHOLDERS",
    "TIER_CANONICAL",
    "TIER_LEGACY",
    "TIER_UNUSABLE",
    "MeaningVerdict",
    "classify_canonical_meaning",
    "classify_meaning_source",
    "is_phonetic_transcription",
]