"""U.19 英语习得型范式：导入词汇 FSRS 种子数据 + 分级泛读文章。

数据来源：Simple English Wikipedia（CC BY-SA 4.0），host 侧预先抓取好写入
本地 JSON（容器无外网，同 T.10 workaround），本脚本只做导入：
  1. 分级泛读：每篇文章算 Flesch-Kincaid 难度分，按语料库内分位数切 1-5 档，
     入 reading_passages（body_text 截断到约 400 词，保留完整句子边界）。
  2. 词汇 FSRS：对全语料库（未截断原文）统计词频，剔除常见功能词后取
     top-N 实义词，按语料库内分位数切 1-5 频率档（与难度档同一把尺子，
     供 i+1 对齐），为每个词从语料库里挑一个真实例句，批量调 LLM 生成
     词性+中文释义，入 vocabulary_items。

跑法（容器内）：
  docker compose exec api python scripts/import_english_vocab_reading.py \
    --articles /path/to/articles.json --top-n 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim: import oprim from mneme/vendor)
from oprim._readability_score import assign_difficulty_bands, flesch_kincaid_grade  # noqa: E402
from oprim._vocab_gloss_generate import generate_vocab_glosses  # noqa: E402
from oprim._word_frequency_stats import (
    assign_frequency_bands,
    compute_word_frequency,
    find_lowercase_attested_words,
)  # noqa: E402

# 常见功能词排除表（事实性停用词表，非受版权保护的创作内容，跟 Flesch-Kincaid
# 公式本身一样是公开的语言学常识，非第二个内容来源）。
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "with",
    "as",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "he",
    "she",
    "they",
    "them",
    "his",
    "her",
    "their",
    "him",
    "i",
    "you",
    "we",
    "us",
    "our",
    "your",
    "my",
    "me",
    "not",
    "no",
    "so",
    "if",
    "than",
    "then",
    "there",
    "here",
    "which",
    "who",
    "whom",
    "whose",
    "what",
    "when",
    "where",
    "why",
    "how",
    "all",
    "some",
    "any",
    "each",
    "other",
    "more",
    "most",
    "such",
    "into",
    "about",
    "after",
    "before",
    "also",
    "s",
    "t",
    "re",
    "ve",
    "ll",
    "d",
    "m",
    "one",
    "two",
    "up",
    "out",
    "over",
    "between",
    "because",
    "during",
    "while",
    "against",
    "under",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WIKI_HEADER_RE = re.compile(r"^\s*=+.*=+\s*$", re.MULTILINE)


def _clean_wiki_text(text: str) -> str:
    """去掉 ``== Section ==`` 式标题行（explaintext 不会展开成句子，会污染
    分句/词频/例句抽取），标题行之间的换行折成空格。"""
    text = _WIKI_HEADER_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _truncate_to_sentences(text: str, max_words: int = 400) -> str:
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    out: list[str] = []
    n = 0
    for s in sentences:
        w = len(s.split())
        if out and n + w > max_words:
            break
        out.append(s)
        n += w
    return " ".join(out) if out else text


def _find_example_sentence(word: str, texts: list[str]) -> str:
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    for text in texts:
        for s in _SENTENCE_SPLIT_RE.split(text):
            s_clean = s.strip()
            if 20 <= len(s_clean) <= 200 and pattern.search(s_clean):
                return s_clean
    return word


async def run(articles_path: str, top_n: int, dry_run: bool) -> None:
    with open(articles_path, encoding="utf-8") as f:
        raw_articles = json.load(f)
    articles = [{**a, "text": _clean_wiki_text(a["text"])} for a in raw_articles]
    print(f"读入 {len(articles)} 篇文章")

    # ── 1. 分级泛读 ──────────────────────────────────────────────────────────
    scored = []
    for art in articles:
        score = flesch_kincaid_grade(art["text"])
        scored.append({**art, "readability_score": score})
    banded_passages = assign_difficulty_bands(scored, n_bands=5)

    # ── 2. 词汇 FSRS：全语料库词频 → 剔除功能词/专有名词 → top-N → 分档 ──────
    all_texts = [a["text"] for a in articles]
    freq = compute_word_frequency(all_texts)
    # Simple Wikipedia 随机词条大量是人物/地名条目，词频榜会被专有名词淹没——
    # 只保留在语料库里以纯小写形式出现过的词（专有名词几乎总是大写开头）。
    lowercase_attested = find_lowercase_attested_words(all_texts)
    content_words = [
        w
        for w in freq
        if w["word"] not in _STOPWORDS
        and len(w["word"]) >= 3
        and w["word"] in lowercase_attested
    ]
    # freq 里的 rank 是过滤前的原始排名，过滤后有空洞——重新按当前顺序编号
    # （filter 保留相对顺序，不影响频率高低次序），assign_frequency_bands
    # 按 rank/n 切分位数依赖 rank 是过滤后的连续序列。
    content_words = [{**w, "rank": i + 1} for i, w in enumerate(content_words)]
    banded_words = assign_frequency_bands(content_words, n_bands=5)
    # 分层取样：每档各取 top_n//5 个（档内保留高频优先），而不是整体取 top-N——
    # 整体取 top-N 会因为最常见的词天然聚集在低 rank，导致 5 个档几乎全落进
    # band=1，vocabulary_items 覆盖不到中低频段，i+1 分级读物就没法对齐。
    per_band = max(1, top_n // 5)
    top_words: list[dict] = []
    for band in range(1, 6):
        band_words = [w for w in banded_words if w["frequency_band"] == band]
        top_words.extend(band_words[:per_band])

    print(f"候选实义词 {len(content_words)}，每档取 {per_band}，共取 {len(top_words)}")

    entries = []
    for w in top_words:
        example = _find_example_sentence(w["word"], all_texts)
        entries.append({**w, "example_sentence": example})

    # 批量调 LLM 生成词性+中文释义（batch_size 控制单次 prompt 长度）
    # 复用项目单源 provider 装配（services.providers.setup.configure_llm_providers，
    # 同 API/worker 启动时用的那一份；MNEME_LLM=ollama 时切本机 Ollama）。
    from obase.provider_registry import ProviderRegistry
    from services.providers.setup import configure_llm_providers

    configure_llm_providers()
    try:
        caller = ProviderRegistry.get().llm("default")
    except Exception:
        caller = None

    glossed: list[dict] = []
    batch_size = 25
    for i in range(0, len(entries), batch_size):
        batch = entries[i : i + batch_size]
        if caller is None:
            print(f"  ⚠️ 无可用 LLM provider，批次 {i}-{i + len(batch)} 词性/释义留空")
            glossed.extend(
                [{"word": e["word"], "pos": None, "meaning_cn": None} for e in batch]
            )
            continue
        try:
            result = await generate_vocab_glosses(
                [
                    {"word": e["word"], "example_sentence": e["example_sentence"]}
                    for e in batch
                ],
                caller=caller,
            )
        except Exception as exc:
            print(f"  ⚠️ 批次 {i}-{i + len(batch)} LLM 调用失败（{exc}），留空")
            glossed.extend(
                [{"word": e["word"], "pos": None, "meaning_cn": None} for e in batch]
            )
            continue
        glossed.extend(result)
        print(f"  已生成 {i + len(batch)}/{len(entries)}")

    gloss_by_word = {g["word"]: g for g in glossed}

    if dry_run:
        print("dry-run，示例前 10 条：")
        for e in entries[:10]:
            g = gloss_by_word.get(e["word"], {})
            print(
                f"  {e['word']} (band={e['frequency_band']}, rank={e['rank']}) "
                f"{g.get('pos')} {g.get('meaning_cn')} | {e['example_sentence'][:50]}"
            )
        print(f"读物 {len(banded_passages)} 篇，难度档分布：")
        from collections import Counter

        print(Counter(p["difficulty_band"] for p in banded_passages))
        return

    dsn = os.environ.get(
        "DATABASE_URL_SYNC", "postgresql://postgres:postgres@db:5432/mneme"
    )
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    n_passages = 0
    for p in banded_passages:
        body = _truncate_to_sentences(p["text"], max_words=400)
        pid = f"reading-{uuid.uuid4().hex[:12]}"
        cur.execute(
            """
            INSERT INTO reading_passages
                (id, subject, title, body_text, source_url, license,
                 word_count, readability_score, difficulty_band)
            VALUES (%s, 'english', %s, %s, %s, 'CC BY-SA 4.0', %s, %s, %s)
            """,
            (
                pid,
                p["title"],
                body,
                p["source_url"],
                len(body.split()),
                p["readability_score"],
                p["difficulty_band"],
            ),
        )
        n_passages += 1
    conn.commit()

    n_vocab = 0
    for e in entries:
        g = gloss_by_word.get(e["word"], {})
        vid = f"vocab-{e['word']}"
        cur.execute(
            """
            INSERT INTO vocabulary_items
                (id, word, pos, meaning_cn, example_sentence,
                 frequency_rank, frequency_band, source, ai_generated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'simplewiki', true)
            ON CONFLICT (id) DO UPDATE SET
                pos = COALESCE(vocabulary_items.pos, EXCLUDED.pos),
                meaning_cn = COALESCE(vocabulary_items.meaning_cn, EXCLUDED.meaning_cn)
            """,
            (
                vid,
                e["word"],
                g.get("pos"),
                g.get("meaning_cn"),
                e["example_sentence"],
                e["rank"],
                e["frequency_band"],
            ),
        )
        n_vocab += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"完成：导入 {n_passages} 篇读物 + {n_vocab} 个词汇")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=str, required=True)
    parser.add_argument("--top-n", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.articles, args.top_n, args.dry_run))
