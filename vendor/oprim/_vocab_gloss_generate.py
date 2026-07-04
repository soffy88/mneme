"""oprim._vocab_gloss_generate — 词汇释义批量生成（单次 LLM 调用）

词频/分档是确定性统计（_word_frequency_stats.py），但中文释义/词性无法从
纯英文语料库统计出来——用单次 LLM 调用批量生成，基于语料库里真实抽取的
例句（example_sentence 由调用方从语料库确定性抽取，不是 LLM 编的）。
"""

from __future__ import annotations

from typing import Any


_SYSTEM = """你是双语词典编纂员。给定一批英语单词及其在真实语境中的例句，
为每个单词标注词性(pos，用 n./v./adj./adv./prep./conj./pron./det./interj. 等缩写)
和最贴合该例句语境的中文释义(meaning_cn，简洁，5-15字)。

输出严格 JSON 数组，与输入单词一一对应，顺序不变：
[{"word": "...", "pos": "...", "meaning_cn": "..."}, ...]"""


async def generate_vocab_glosses(
    entries: list[dict],
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
) -> list[dict]:
    """批量生成词性+中文释义。

    Parameters
    ----------
    entries : list[dict]
        每项 {"word": str, "example_sentence": str}。
    caller : Any
        LLM 调用者（注入）。

    Returns
    -------
    list[dict]
        每项 {"word": str, "pos": str, "meaning_cn": str}，与输入等长同序；
        LLM 输出解析失败或缺项时该词退化为 {"pos": None, "meaning_cn": None}
        （调用方决定是否仍然入库，不假装有把握）。
    """
    import json

    from oprim.llm import llm_complete

    listing = "\n".join(
        f"{i + 1}. {e['word']} —— 例句: {e['example_sentence']}"
        for i, e in enumerate(entries)
    )
    resp = await llm_complete(
        [{"role": "user", "content": listing}],
        caller=caller,
        system=_SYSTEM,
        model=model,
        max_tokens=4096,
    )

    raw = resp.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            data = []
    except json.JSONDecodeError:
        data = []

    by_word = {d.get("word"): d for d in data if isinstance(d, dict)}

    out = []
    for e in entries:
        d = by_word.get(e["word"])
        if d:
            out.append(
                {
                    "word": e["word"],
                    "pos": d.get("pos"),
                    "meaning_cn": d.get("meaning_cn"),
                }
            )
        else:
            out.append({"word": e["word"], "pos": None, "meaning_cn": None})
    return out


__all__ = ["generate_vocab_glosses"]
