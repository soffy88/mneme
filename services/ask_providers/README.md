# ask_providers — 无 LLM 的语文/英语确定性答题

给拍照问题目的求解路由用。数学/物理/化学精确内核（`services/ask_kernels*`）之后、LLM 之前调用。

## 钩子（给 router）

```python
from services.ask_providers import solve_with_providers          # 编排好的入口
from services.ask_providers.english import english_lookup_solve  # (text) -> dict | None
from services.ask_providers.chinese import chinese_lookup_solve  # (text) -> dict | None
```

- 同步、纯本地、毫秒级（SQLite 只读 + 纯 Python 规则），**永不抛**；不适用返回 `None`。
- 在 async 代码里用 `await asyncio.to_thread(solve_with_providers, text, subject)`。
- 现在的接线：`services/photo_ask_service.solve_question` 在 `solve_exact` 未命中后调用，`solver="provider"`。
  若新 router 合入，把这一处换成 router 内的一个 provider 槽位即可（返回形状与 `KernelSolution.to_dict()` 一致）。

## 返回

```json
{"kernel": "chinese.poem", "answer": "低头思故乡", "steps": ["..."], "hint": "...", "explanation": "...",
 "card": {"type": "poem", "title": "静夜思", "author": "李白", "dynasty": "唐", "lines": ["..."], "highlight": 1, "answer": "低头思故乡"}}
```

| kernel | 触发 | card.type |
|---|---|---|
| `english.word` | 1–3 个英文词（可带「什么意思/翻译/音标」） | `english_word` {word, phonetic, meanings[], inflections{}, tags[], lemma_of} |
| `english.inflection` | 过去式/过去分词/现在分词/三单/复数/比较级/最高级/原形，或 "past tense of go" | `english_word`（若词典可用） |
| `english.grammar` | 英文句子含确定性语法错误：be/do 一致、三单 -s、a/an、时间状语与时态、情态动词后原形、There be | — |
| `english.choice` | 带空格 + A–D 选项的语法单选（逐项代入 + 时间词定时态） | — |
| `chinese.pinyin` | 注音/拼音/读音/怎么读/多音字 | `pinyin` {items:[{char, pinyin}]} |
| `chinese.poem` | 默写空（`____` / `（ ）`）、上一句/下一句、出处/作者、或整句诗 | `poem` {title, author, dynasty, lines[], highlight, highlights[], answer} |
| `chinese.idiom` | 成语本身（≤8 字）或带「意思/解释/出处」 | `idiom` {word, pinyin, explanation, derivation, example} |

## 数据（不进 git）

`python3 scripts/ask_data/fetch_and_build.py` 按 `data/ask_providers/MANIFEST.json`（固定 commit + 逐文件 sha256）下载并构建：

| 文件 | 来源 | 许可 |
|---|---|---|
| `ecdict.sqlite` | [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| `poetry.sqlite` | [chinese-poetry/chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)（全唐诗/全宋诗/宋词/元曲/诗经/楚辞/曹操诗集 + rank） | MIT |
| `idiom.sqlite` | [pwxcoo/chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua) `data/idiom.json` | MIT |
| 拼音 | [pypinyin](https://github.com/mozillazg/python-pinyin)（pip 依赖，自带词典） | MIT |

输出目录 `MNEME_ASK_DATA_DIR`，默认 `<repo>/data/external/ask_providers`（gitignored；容器里 `/app/data/external/ask_providers`）。
繁转简（全唐诗/全宋诗原文是繁体）只在构建期用 `opencc-python-reimplemented`（Apache-2.0）。
数据缺失时对应功能静默返回 `None`（拼音、不规则动词、语法规则不依赖数据文件）。
