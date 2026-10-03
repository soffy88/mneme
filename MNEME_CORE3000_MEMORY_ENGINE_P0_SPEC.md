# MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC

> **状态**：P0 工程规格（2026-10-03）。取代 `VOCABULARY MEMORY ENGINE SPEC v1.0` 作为
> **可执行契约**；原 spec 作为**意图来源**保留（记忆引擎要解决的问题不变）。
> **权威设计**仍是 `MNEME_MASTER_DESIGN.md`；本文件是它的下位实施细则，冲突时以 Master 为准。
> **执行看板** = `TASKS.md`。

## 0. 这份文档为什么存在

原 spec 把「词 → LLM → 记忆」当成一条链。经生产库实测（2026-10-03，见 §2），
按字面实现会得到一批**生成很好但进不了产品链**的数据：没有教材例句源、没有图片
provider、影视片段已被否决、核心词实际是 2,761 单词而非 3,000。

因此 P0 的目标不是「把 spec 全部实现」，而是：

1. 打通 **Context Retriever → Memory Engine → Quality Verifier → FSRS 复习阶梯**
   这条**端到端真实可跑**的链，并留下可审计的质量数字；
2. 对 spec 中**当前不可达**的部分，明确标注 `BLOCKED` 与**解锁条件**，不假装能做；
3. 用**确定性派生优先、LLM 只做记忆联想**的原则重划字段归属（§4）。

**红线不变**：数值/词源类结论必来自可追溯来源，LLM 只产出联想层；`vocab-*` 掌握度
只经 `SubmitAnswer → process_interaction` 写路径。

---

## 1. 输入 / 输出契约（与原 spec 的差异已标注）

### 1.1 输入（Context Retriever 产出，非直接喂 LLM）

```json
{
  "vocabulary_id": "…",
  "word": "abandon",
  "pos": "verb",
  "meaning_cn": "放弃；抛弃",
  "phonetic_arpabet": "AH0 B AE1 N D AH0 N",
  "context": {
    "tier": 3,
    "tier_name": "NCE",
    "textbook_tier_available": false,
    "sentences": [
      {"text": "The team abandoned the project.", "chinese_text": "…",
       "source": "NCE", "lesson": "Lesson 32", "sentence_id": "…"}
    ]
  },
  "affix": {"prefix": null, "root": null, "suffix": null,
            "etymology_status": "reference_confirmed"},
  "xiangxing": {"ipa_ascii": "…", "example_en": "…"},
  "collocations": [{"phrase_en": "abandon a plan", "phrase_cn": "放弃计划"}]
}
```

`context.tier` 取值（**Priority 由小到大 = 优先级由高到低**）：

| tier | 名称 | 现状 |
|---|---|---|
| 1 | `CURRENT_LESSON` 当前课句子 | **BLOCKED**：无源（§2.1） |
| 2 | `CURRENT_BOOK` 当前教材句子 | **BLOCKED**：无源（§2.1） |
| 3 | `NCE` 课文真实句 | ✅ 13,017 句，覆盖 2,066/2,761 单词 |
| 4 | `PUBLIC_CORPUS` 高质量公共语料 | **BLOCKED**：无库 |
| 5 | `NONE` 无上下文 | ✅ 显式降级路径，695 单词 |

> 接口按 5 层建好，1/2/4 层返回 `textbook_tier_available=false` 并附
> `unavailable_reason`，**不静默降级冒充有语境**。

### 1.2 输出（MemoryNode 落库形态）

```json
{
  "vocabulary_id": "…",
  "tier": "A",
  "memory_core": {"image": "船长松开缆绳弃船", "meaning": "放手，不再负责",
                  "logic": "放手→失去控制→放弃"},
  "scene": "暴风雨中船长逃离沉船",
  "family": [{"word": "abandoned", "meaning_cn": "被遗弃的", "vocabulary_item_id": "…"}],
  "sound_hook": "…",
  "spelling_hook": "…",
  "recall_question": "船长松手弃船是什么动作？",
  "answer": "abandon",
  "image_prompt": "A child protecting the Earth with a transparent shield, cartoon educational style, clear action",
  "animation_candidate": true,
  "animation_scene": "Earth covered by protective shield",
  "context_tier": 3,
  "context_evidence": [{"sentence_id": "…", "text": "…", "lesson": "Lesson 32"}],
  "generation_model": "veya1.2-128K",
  "generation_version": "p0",
  "quality_score": 0.86,
  "verified": true
}
```

### 1.3 与原 spec 的四处**刻意偏离**（每条都有理由）

| 原 spec | P0 实际 | 理由 |
|---|---|---|
| `etymology{origin, certainty}` 由 LLM 输出，靠 `ETYMOLOGY_CONFIRMED` 门禁 | **LLM 契约里没有 etymology 字段** | 门禁挡不住幻觉，**不存在即不可能编造**。词源一律读 `vocabulary_affixes.etymology_status`（已分 `reference_confirmed` 67 / `mnemonic_association` 288 / `disputed` 24） |
| `movie_scene` + `media_reference` 影视片段 | `scene` = 记忆场景（联想），**不建 media 列** | 影视片段已于 2026-10-02 因未成年 + 版权被人决策否决 |
| `root_logic` / `collocations` 存进 MemoryNode | **不存**，渲染时读 `vocabulary_affixes` / `vocabulary_collocations` | 单源红线（CLAUDE.md §写要求升级）。复制即产生第二份会漂移的事实源 |
| `IMAGE_COVERAGE ≥ 80%` | 改为 `IMAGE_PROMPT_COVERAGE` | 无图片 provider，图片 URL 覆盖率今天恒为 0，门槛不可达（§2.2） |

---

## 2. 生产实测基线（2026-10-03，只读查询）

### 2.1 语境源：今天**只有 NCE**

| 事实 | 值 | 后果 |
|---|---|---|
| `timed_sentences`（英文非空） | 13,017 | 唯一可用真实句库 |
| `lessons` 总数 / 全部为 NCE | 559 / 559 | 无「当前教材课」概念 |
| `lessons.book_id ∩ books` | **0** | 教材链与课本表**未打通**，tier 1/2 无源 |
| `reading_passages` | **41** 行 | 不能当语料库 |
| 核心范围内有 NCE 句的**单词** | 2,066 / 2,761 = **74.8%** | `EXAMPLE_COVERAGE ≥ 95%` 今天不可达 |

**解锁 tier 1/2 需要**（不在 P0）：① 非 NCE 教材句导入器；
② `lessons.book_id ↔ books` 打通或新增教材课本维度；③ 句级 `source_scope`
标注（当前 NCE 导入器不产出该字段）。

### 2.2 素材：图片 / 动画 / 影视

| 项 | 现状 |
|---|---|
| 外部图片 provider 集成 | **0** |
| 图片生成模型 | **无**（仅 VLM 可做排序/描述） |
| `vendor/oskill/asset_reference_inject.py` | hevi 视频 `shot_spec`，与词汇无关，无挂载点 |
| 影视片段 | 已否决（未成年 + 版权），`license_status` 是字段不是授权 |

→ P0 只产出 `image_prompt` 文本，**不产出 `memory_image_url`**。

### 2.3 核心范围构成（collection `core-exam-zhongkao-gaokao-k12`）

| 口径 | 词数 |
|---|---|
| 集合总数 | 3,369 |
| **其中单词**（`^[A-Za-z][A-Za-z-]*$`） | **2,761** ← 验收分母 |
| 多词短语（`a bit of` / `according to` / `agree with sb.`） | 608 |

> 「核心 3000 词」这个口径必须说明，否则验收数字虚高 22%。短语单列统计。

### 2.4 字段完备度与分层（单词 2,761）

| 维度 | 词数 | 占比 |
|---|---|---|
| `meaning_cn` | 2,200 | 79.7% |
| `pos` | 1,568 | 56.8% |
| NCE 例句 | 2,066 | 74.8% |
| ARPAbet 音标 | 2,757 | 99.9% |
| **释义+词性+例句+音标 四者齐全** | 1,252 | 45.3% |
| 有语境但缺释义 | 461 | 16.7% |
| 无语境 | 695 | 25.2% |

⚠️ **实测纠正（2026-10-03，dry-run 验证）**：`canonical_meaning` **非空 ≠ 可派生**。
跑 `scripts/derive_meaning_from_canonical.py` 的结果是：

```
待填 meaning_cn 词数 = 1169 → 可派生 = 0
  canonical 是 IPA（读音不是释义）= 807 · 占位符 = 361 · 需 LLM = 1
```

即 `meaning_cn` 停在 **2,200**，确定性补齐这条路 today 走不通 —— 被 2026-10-02 已
记录但**未修**的「导入时列错位（音标进了释义列）」挡住（`escape`/`freedom`/`survive`
等 807 条）。

→ P0 的处置：**这 461 词走既有 `scripts/backfill_vocab_glosses.py`**（它们**有**真实
NCE 例句，满足生成器「例句由语料库确定性抽取」的契约，零编造），**不**新写 LLM 释义
路径。修 IPA 列错位是独立的数据质量 epic，不在本 P0。

分层（取代原 spec 的 500/1500 假设）：

| tier | 判定（确定性，全查已有表） | 词数 | P0 产出 |
|---|---|---|---|
| **A** | 有 NCE 语境 **且** 有记忆锚点（`vocabulary_affixes` 或 `vocabulary_xiangxing`） | **1,050** | MemoryNode + `image_prompt` + `animation_candidate` |
| **B** | 有 NCE 语境，无锚点 | **1,016** | MemoryNode + `image_prompt` |
| **C** | 无语境 | **695** | 纯 MemoryNode，`context_tier=5` 且带 `degradation_reason` |

> `frequency_band` 在核心范围内**恒等于 5**，不能用于分层（沿用 2026-10-02 实测结论）。

### 2.5 记忆锚点存量（核心范围内）

| 表 | 覆盖词数 | P0 用法 |
|---|---|---|
| `vocabulary_affixes` | 379 | `root_logic` 唯一来源（带 epistemic 档位） |
| `vocabulary_xiangxing` | 1,218 | 象形记忆线索（归属 95.9% 已验证） |
| `vocabulary_collocations` | 48 词 / 66 搭配 | `collocations` 唯一来源 |

### 2.6 输入侧审计（`--audit-only`，2026-10-03 实跑）

```bash
python scripts/generate_vocab_memory_nodes.py --limit 0 --audit-only   # 全量
python scripts/generate_vocab_memory_nodes.py --limit 100 --audit-only # 试跑样本
```

**全量 2,761 单词**（走真实代码路径，与 §2.4 的 SQL 估算一致）：

| 指标 | 值 |
|---|---|
| tier 分布 | **A=1,050 / B=1,016 / C=695** |
| context_tier 分布 | 3(NCE)=2,066 / 5(无)=695 |
| 语境覆盖率 | **74.83%** |
| 平均句数/词 | 2.064 |
| 有词根分解 / 象形 / 搭配 | 379 / 1,218 / 48 |

**100 词试跑样本**（seed=20261003，确定性抽样）：

| 指标 | 值 |
|---|---|
| tier 分布 | A=37 / B=33 / C=30 |
| context_tier | 3=70 / 5=30 → 覆盖率 **70%** |
| 平均句数/词 | 1.89 |
| 有词根 / 象形 / 搭配 | 15 / 41 / 4 |

样本的 70% 覆盖率与总体 74.83% 接近（n=100 的抽样波动范围），说明这 100 词对
「无语境降级路径」有代表性 —— 约 3 成词会走 C 级，正是最该验的那条路。

> `--audit-only` 存在的理由：**输入侧是纯确定性的，不该被模型的可用性绑住**。
> 2026-10-03 实测本机无可用文本模型（见 §2.7），但「扩到 3,000 之前输入侧成色如何」
> 今天就能回答。

---

### 2.7 文本模型可用性（2026-10-03 实测；结论见 §2.9）

| 通道 | 状态 |
|---|---|
| Veya `veya1.2-128K`（`.env` `VEYA_MODEL`） | **该模型已不在网关模型表里** → 返回 `gpt-5.6-luna 兜底失败` |
| Veya `gpt-5.6-luna` | HTTP 429 `usage limit has been reached` |
| Veya `opencode-go/*`（deepseek-v4-flash / glm-5.x / gpt-5.6-luna …） | HTTP 429 `Go usage limit exceeded`（workspace 月度配额耗尽） |
| Qwen 云 fallback | `QWEN_API_KEY` **为空** → `No API-key provided` |
| Veya 监听 | 只 bind `127.0.0.1:8791`，**api 容器内的 `host.docker.internal:8791` 被拒**（connection refused） |

⇒ **100 词试跑的生成环节今天跑不了**。这不是代码问题（`--audit-only` 已证明输入侧
与门禁链路可用），是配额/凭据/模型名三者都失效。

**解锁需要（任一）**：
1. 恢复 Veya 配额或换一个可用模型名，并同步更新 `.env` 的 `VEYA_MODEL`；
2. 配 `QWEN_API_KEY` 走云 fallback；
3. 把 Veya 监听到 `0.0.0.0:8791`（或给 compose 走 `network_mode: host`），
   这样容器内也能调 —— 注意这是**改生产监听**，须先确认。

在解锁之前，**不得**用桩数据或手写样本充当「试跑通过率」上报。生成质量数字只能是
「未测」，不是「已过」。

### 2.8 CME-P1.5：meaning 列错位的真实状态与判定

**真实状态**（2026-10-03 全表只读查询，不修历史数据）：

| 类别 | 行数 |
|---|---|
| 以 `[（(` 开头的 `canonical_meaning` | 9,855 |
| 其中**无汉字** → 真音标（读音） | **9,844** |
| 其中**有汉字** → 是释义，被旧规则**误拒** | **11** |

核心范围（单词口径）：806 条真音标 + 1 条误拒。旧规则 `^[\[（(]` 是**双向**错的：

- 对 `[ˈeərən]` 判对；
- 对 `[法] 法案`、`[天] 十月`、`(使)远离，(使)不接近`、`[人名] 齐珀`、
  `（等于the United Kingdom）英国`、`won't → [澳大利亚、新西兰口语]厌恶`、
  `[口语]再见!` 判错 —— 那 11 条至今 `meaning_cn` 为空，**不是被正确拒绝，是被误判**。

**根因**：教材词表把 `[方括号]` 同时用于**义项/领域标签**（`[法]`/`[天]`/`[计]`/`[食品]`）
和**音标**。括号本身不携带语义，**只有「内部有无汉字」能区分**。

**判定（唯一源 `services/vocab_meaning.py`）**：

```
canonical/legacy/unusable 三档
  canonical  = meaning_cn 有可信释义        → 权威
  legacy     = 只有 canonical_meaning 能给出 → 可用但标为未派生
  unusable   = 音标 / 占位符 / 空            → 绝不可当释义
is_phonetic_transcription(t) := 括号开头 且 (内部无汉字 或 整体只是音标标记词)
```

`services/vocab_context.py` 的 `load_memory_input` 现在**只**把判定为可信的那一份
交给 LLM，音标一律变 `None`（读音仍有正确去处 `phonetic_arpabet`）。
`scripts/derive_meaning_from_canonical.py` 改为引用同一判定，消除两个互相矛盾的规则。

### 2.9 真实 LLM 打通（2026-10-03）

**根因不是连通性，是模型名。** 网关自己的注释写明：`veya1.2-128K` 是**已退役别名**，
「§11 要求废弃拼写仍可解析 —— 现在解析到 `veya-free`」，而 `.env` 里配的正是这个退役名。

| 配置 | 网关 `/models` 可达 | 真发一次补全（检查内容） |
|---|---|---|
| `veya1.2-128K`（现 `.env`，即线上） | ✅ | ❌ `gateway_returned_error_payload`（「gpt-5.6-luna 兜底失败」） |
| `veya1.2` | ✅ | ✅ `ok` |
| `veya1.1` / `veya-deepseek-v4-flash-nv` | ✅ | ✅ 可用 |
| `gpt-5.6-luna` / `opencode-go/*` | ✅ | ❌ HTTP 429 配额耗尽 |
| Qwen 云 fallback | — | ❌ `QWEN_API_KEY` 为空 |

**探针设计教训**：网关会用 **HTTP 200** 把上游故障当正文返回
（`{"content":"gpt-5.6-luna 兜底失败"}`）。第一版探针只判「有没有抛异常」，
于是把**调不通报成健康**（`veya1.2-128K` 显示 reachable=true）。现在
`/health/providers` 分两层：默认只做 ~3s 端点探活；`?deep=1` 真发一次最小补全并
**检查返回内容**是否命中 `_GATEWAY_ERROR_MARKERS`。

**契约缺陷（非 prompt 调优）**：首轮真实生成 3/3 词 `ANSWER_MATCHES_WORD` 失败 ——
`answer` 是 JSON 模板里的必填字段，但 `_SYSTEM` 里**没有任何一条规则定义它**，
模型于是返回了中文描述（「团团聚拢成团块」）而不是目标单词。补上第 8 条规则后消失。
这是契约缺定义，不是「继续优化 prompt」。

### 2.10 阶梯阶段判定的真实卡契约 bug（已修）

`resolve_stage` 第一版按 `card["state"]` 是字符串（`"learning"`/`"review"`）、并读
`card["reps"]`。**线上真卡两者都不成立**：

```json
{"due":"...","step":0,"state":1,"card_id":1784397667197,
 "stability":0.212,"difficulty":6.4133,"last_review":"..."}
```

py-fsrs 的 `Card` 字段只有 `card_id/state/step/stability/difficulty/due/last_review`
—— **没有 `reps`**，`state` 是 `State` 枚举 **int**（Learning=1 / Review=2 /
Relearning=3）。原写法只对自己编的 fixture 成立，接到真卡上直接 `AttributeError`。

修法：`state` 按 int 解析（并容错字符串/异常类型，渲染路径不允许因一张怪卡 500）；
Review 档内用**已排定间隔**当重复次数代理（py-fsrs 不存次数），
`<3 天 → review_early`、`<21 天 → review_mid`、否则 `review_late`。
测试夹具已全部换成**生产真卡形状**。

## 3. P0 交付物（DoD 逐条）

| # | 交付物 | 位置 | 完成判据 |
|---|---|---|---|
| 1 | 前置释义补齐 | `scripts/derive_meaning_from_canonical.py`（既有） | 复跑幂等，`meaning_cn` ≥ 2,659 |
| 2 | MemoryNode schema | `alembic/versions/…_add_vocabulary_memory_nodes.py` + `services/models.py` | 迁移可升可降；`EXPECTED_MIGRATION_HEAD` 与 head 断言同步更新 |
| 3 | Context Retriever | `services/vocab_context.py` | 5 层 tier 可插拔；tier 1/2/4 显式 `unavailable`；纯确定性、可单测 |
| 4 | LLM 生成 pipeline | `vendor/oprim/_vocab_memory_generate.py` | 单次 LLM 调用 = oprim；输出缺项即该词降级，**不假装有把握** |
| 5 | Quality Verifier | `services/vocab_memory.py` | 9 条确定性门禁，全部可单测 + 变异验证 |
| 6 | FSRS 复习阶梯渲染 | `services/vocab_memory.py::render_review_ladder` | 首次学习**全展开**；复习期分层揭示 + 显式「再看一层」 |
| 7 | 能力边界接线 | `services/mcp_router.py` | `tool_/POST` 两件套：`GenerateMemoryNode`、`GetMemoryNode` |
| 8 | 试跑 runner | `scripts/generate_vocab_memory_nodes.py` | **dry-run 默认**，不加 `--apply` 不写库 |
| 9 | 100 词试跑 | 报告 `reports/` | 单词全集 2,761 随机 100，产出可审计通过率 |
| 10 | 测试 | `tests/test_vocab_memory_engine.py` 等 | `./scripts/check.sh` 全绿 |

**P0 明确不做**：教材例句层（§2.1）、图片/动画生成（§2.2）、影视片段（已否决）、
3,369 全量生成（另开 epic）、写 `KCMastery`（避免污染生产学生数据）。

### 3.1 交付状态（2026-10-03）

| # | 交付物 | 状态 |
|---|---|---|
| 1 | 前置释义补齐 | ⚠️ **实测可派生 = 0**（IPA 列错位 bug 挡住），`meaning_cn` 停在 2,200 → 见 §2.8 与 TASKS `CME-P1.5` |
| 2 | MemoryNode schema | ✅ `e6f7a8b9c0d2`，已在 `mneme_test` 实际升级 |
| 3 | Context Retriever | ✅ 全量 2,761 审计通过；**已加释义污染闸**（§2.8） |
| 4 | LLM 生成 pipeline | ✅ 真实模型跑通（§2.9） |
| 5 | Quality Verifier | ✅ 9 条门禁 + 6 处变异验证 |
| 6 | FSRS 阶梯 | ✅ 阶段解析 + 首次全展开 + `expanded` 不改调度；**已修真实卡契约 bug**（§2.10） |
| 7 | `/mcp/*` 接线 | ✅ `GenerateMemoryNode`（落库需 admin）/ `GetMemoryNode` |
| 8 | 试跑 runner | ✅ 默认 dry-run、确定性 seed、`--require-context`、`--audit-only` |
| 9 | **100 词生成试跑** | 🔄 见 §2.9 |
| 10 | 测试 | ✅ 见 §3.2 |

> 变异验证记录（改坏判定 → 对应测试必须失败，均已复现）：
> `NO_ANSWER_LEAK` 恒过 → 1 败；无语境记 PASS → 2 败；首次改为折叠 2 层 → 2 败；
> B 级也给动画候选 → 1 败；`disputed` 放行 → 1 败；分层忽略锚点 → 2 败；
> 音标判定退回「只看括号开头」→ 20 败；污染的 `meaning_cn` 放行 → 1 败；
> 删掉音标标记兜底 → 1 败；`state` 不当 int → 3 败；阶梯按阶段分 KC（多卡化）→ 3 败。

### 3.2 P0 门禁（图片/动画已移出，见 §7）

| 门禁 | P0 口径 | 100 词实测 |
|---|---|---|
| 核心范围分母 | **2,761 单词**（608 短语单列） | 试跑池 = 有语境 2,066 |
| 试跑范围 | `CORE_EXAM_VOCAB` ∩ 有真实教材/NCE 例句（`--require-context`） | 100 |
| 9 条门禁全过 | 目标 100%；P0 口径 ≥85% | **89%** |
| false-etymology | **0** | **0**（结构保证，非门禁筛出） |
| empty-context | **0** | **0** |
| malformed node | **0** 入库 | 生成侧 1（未入库） |
| 调用错误 | 0 | **0** |
| FSRS | 一词一 node、一 KCMastery、一 KC | 契约测试覆盖 |
| **图片 / 动画** | **已从 P0 门禁移除** → 后续 Enrichment Layer（§2.2） | — |

### 3.3 100 词真实试跑结果（2026-10-03，模型 `veya1.2`，dry-run）

范围：`CORE_EXAM_VOCAB` ∩ 有真实 NCE 例句（2,066 池）抽 100，seed=20261003。
报告 `reports/vocab_memory_p0/trial_100_seed20261003_dryrun.json`。

| 指标 | 值 |
|---|---|
| 生成成功 | **99 / 100**（1 词 LLM 输出未过契约，已拒收未入库） |
| **9 门禁全过（`verified`）** | **89 / 100 = 89%** |
| 调用错误 | **0** |
| 降级（无语境） | **0**（范围已限定有语境） |
| `image_prompt` 覆盖 | 99% |
| 失败门分布 | `FAMILY_TRACEABLE` ×6、`HAS_ONE_CORE_IMAGE` ×4 |

**false-etymology = 0**（结构保证：LLM 契约里没有 etymology 字段，不是靠门禁筛的）。
**empty-context = 0**（范围限定）。**malformed = 1**（生成侧未过契约，**未入库**）。

⚠️ **因此 P0 的「9 门禁全部 PASS」在 100% 意义上尚未达成（实为 89%）**，按 ≥85% 的
P0 口径达标，但不能写成 QUALIFIED。

### 3.4 人工抽查 20/100 的四个发现

覆盖：高频具体（bed/deer/wet）、抽象（population/commitment/progress/lonely）、
多义（blind/wound/wind/fine/state/title/point）、动词（choose/encourage/require）、
易混（advice↔advise、wind↔wound）。报告 `trial_20_seed20261003_dryrun.json`。

**① `HAS_ONE_CORE_IMAGE` 下限 8 是误杀源（已修）。** 4/4 个该门拒收全是 **7 字好画面**：
`real`→「火烧假花露真蕊」、`each`→「老师逐个发糖果」、`stand`→「脚生根顶住狂风」、
`wet`→「拧湿毛巾水滴答」。10 次拒收里 4 次是误杀。下限降到 5，重跑这 4 词
**4/4 全过**。已加回归测试 + 变异验证（改回 8 → 失败）。

**② `meaning_cn` 系统性只截了第一个义项（数据问题，未修，需人决策）。**
`canonical_meaning` 是多义项的，但 `meaning_cn` 常常只留第一行：

| 词 | `meaning_cn`（引擎实际吃到的） | `canonical_meaning` 完整义项 | 后果 |
|---|---|---|---|
| `blind` | 掩饰，借口；百叶窗 | + **adj. 盲目的；瞎的** / vt. 使失明 | 记忆卡锚在**百叶窗**上 |
| `wet` | 雨天；湿气 | + **adj. 潮湿的；有雨的** | 锚在「雨天」而非「潮湿」 |
| `fine` | 罚款 | + adj. 好的；优良的 | 锚在「罚款」而非「好的」 |

实测规模：核心单词里 **1,288** 词 `canonical_meaning` 是多义项，
其中 **1,190** 词的 `meaning_cn` 长度不足 canonical 的一半（即只截了首个义项）；
另有 **490** 词 `pos` 与 canonical 首义项不一致（`pos` 来自另一来源：
`import_pos_from_dictation.py` 的默写表）。

→ 这不是引擎的 bug，但会让**最常用的义项**缺席，学生记住的是冷门义项。
修它等于改「学生看到的权威释义」，**需人决策**（TASKS `CME-P1.6`）。

**③ 记忆画面可能与语境句不是同一个义项。** `blind` 的 NCE 真实句是
`And though the gleams blind and dazzle`（**动词**义「使眩目」），而生成的画面是
百叶窗（**名词**义）。Context Retriever 把句子给了模型，但**没有任何机制强制画面
与该句的义项一致** —— 于是第 1 层（画面）与第 4 层（真实句）在讲两个意思。
多义词上这是结构性问题，需在 P1 解决（义项对齐门）。

**④ 无权威释义时仍可生成 verified 节点（门禁缺口）。** `title` 的
`canonical_meaning` 是纯音标 `[ˈtaɪt(ə)l]` → 判定 `unusable`，但节点仍
`verified=true`（模型靠 NCE 句推的，画面「法官高举金牌」其实不错）。
9 条门禁里**没有一条**要求「输入释义可信」。这道门加不加要人决策：
加了会拒掉 `title` 这种「靠语境救回来」的好节点；不加就意味着存在
「语义核心由模型发明、无教材出处」的卡片 —— 与「教材原文优先」有张力。

**另观察**：`FAMILY_TRACEABLE` 在 family 全不可追溯时**整词拒收**（`X-ray` 画面本身
很好，只因家族词是编的就被丢）。这是「门禁全过」口径下的aligned 行为，但
「一个附属字段坏了就丢掉整张好卡」是否合适，属策略选择，未改。



---

## 4. 字段归属（单源红线）

```
vocabulary_items      ← 词 / 词性 / 释义 / 音标 / 例句        （既有，事实层）
vocabulary_affixes    ← 前缀·词根·后缀 + etymology_status   （既有，事实+分档）
vocabulary_collocations/vocabulary_xiangxing ← 搭配 / 象形    （既有）
vocabulary_memory_nodes ← **只存 LLM 生成的联想层**          （P0 新增）
```

`vocabulary_memory_nodes` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `vocabulary_item_id` | FK → `vocabulary_items.id` UNIQUE | 一词一条，多词短语也允许 |
| `tier` | `A`/`B`/`C` | 确定性分层结果 |
| `core_image` | TEXT | 唯一核心画面，9 字以上 |
| `semantic_core` | JSONB | `{image, meaning, logic}` |
| `scene` | TEXT | 记忆场景（**联想，非事实**） |
| `family_network` | JSONB | `[{word, meaning_cn, vocabulary_item_id}]`，成员须真实存在 |
| `sound_hook` / `spelling_hook` | TEXT | |
| `recall_question` / `answer` | TEXT | 主动回忆钩子 |
| `image_prompt` | TEXT | 交给未来图片生成器，**不含 URL** |
| `animation_candidate` | BOOL | 仅 A 级为 true |
| `animation_scene` | TEXT NULL | |
| `context_tier` | INT | 1..5，落库的是**实际取到的层** |
| `context_evidence` | JSONB | `[{sentence_id, text, lesson, source}]` |
| `context_absence_reason` | TEXT NULL | tier=5 时必填 |
| `generation_model` / `generation_version` | VARCHAR | 审计用 |
| `quality_score` | FLOAT | 0..1，门禁通过率映射 |
| `verified` | BOOL | 9 条门禁全过才为 true |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**合规**：`vocabulary_memory_nodes` 是**全体学生共享的参考内容**（与 `books` 同性质），
不含学生 PII，FK 带 `ON DELETE CASCADE` → **不进** `services/purge_service._STUDENT_TABLES`
（与 `vocabulary_affixes` 同一判断）。

---

## 5. 质量门禁（9 条，全部确定性）

| 门禁 | 判定 | 不过怎么办 |
|---|---|---|
| `HAS_ONE_CORE_IMAGE` | `core_image` 恰好一条、非空、长度 ∈ [8, 60] | 拒收 |
| `HAS_RECALL_HOOK` | `recall_question` 非空且以 `？/?` 结尾 | 拒收 |
| `ANSWER_MATCHES_WORD` | `normalize(answer) == normalize(word)` | 拒收 |
| `NO_ANSWER_LEAK` | `recall_question` **不含**目标词（分词后） | 拒收（原 spec 未列，会直接废掉主动回忆） |
| `NO_ECHO_OF_EVIDENCE` | `core_image` 不是 `context_evidence` 句子的复制 | 拒收 |
| `HAS_CONTEXT` | `context_tier < 5` | tier 5 时记 `DEGRADED_NO_CONTEXT`，`verified=false`，**不记 PASS** |
| `FAMILY_TRACEABLE` | `family_network` 每个成员能在 `vocabulary_items` 查到 | 丢弃该成员；全丢则拒收 |
| `NO_FALSE_ROOT` | 生成的 root 叙述与 `vocabulary_affixes` 不矛盾 | 矛盾则丢弃生成值，回落到存储值 |
| `NOT_DISPUTED_SOURCE` | 引用的 `etymology_status` 不是 `disputed` | `disputed` 不进 MemoryNode 展示 |

**关键设计**：`NO_FALSE_ROOT` 与 `NOT_DISPUTED_SOURCE` 是**读取既有分档**而非重新判定。
P0 不生成任何词源（§1.3），所以 `NO_FALSE_ROOT` 实际退化为「LLM 的 root_logic 若与
存储分解冲突则丢弃」——这是防止生成内容污染既有 379 条分档数据的闸门。

`verified=true` 要求 8 条全过（第 7 条允许部分丢弃）；`quality_score` = 通过条数 / 9。

---

## 6. FSRS 复习阶梯（按 2026-10-03 人决策）

**每词 1 张卡、1 个 KC**（沿用 `vocab-{id}`，不动 mastery 写路径）。阶梯**不是 4 张卡**，
而是同一张卡内的**分阶段揭示**，由 FSRS 所处阶段决定露多少：

| 阶段 | 露出内容 |
|---|---|
| `learning`（**首次**，py-fsrs learning step） | **全部展开**：核心画面 + 语义 + 词根/词源 + 搭配 + 真实句 + 回忆问 |
| `review_early`（第 2 次） | 画面 + 语义 + 回忆问（真实句折叠） |
| `review_mid`（第 3 次） | 画面 + 词根/词源 + 回忆问 |
| `review_late`（第 4 次起） | 回忆问 → 作答后才展开答案与真实句 |

> **人决策原文要点**：第一次最重要，目标是**完全理解**，所以首次**不做下拉折叠**，
> 直接给完整内容；想多理解的用户另有「再看一层」的可选展开，不强制。

API：`render_review_ladder(node, *, stage, expanded: int = 0) -> dict`，
`expanded` 让愿意深挖的学生每次多揭一层，但**不改变 FSRS 调度状态**。

---

## 7. 门禁数字（重定基线）

| 原 spec 门禁 | P0 实际门禁 | 依据 |
|---|---|---|
| `CORE_WORD_COUNT ≥ 3000` | 分母 = **2,761 单词**（608 短语单列）；P0 **不声称** 3,000 | §2.3 |
| `EXAMPLE_COVERAGE ≥ 95%` | **不可达**（实测上限 74.8%）。P0 改为：试跑中有语境的词 **100%** 使用真实句，零编造 | §2.1 |
| `MEMORY_NODE_COVERAGE ≥ 90%` | P0：试跑 100 词中 `verified=true` 占比 **≥ 85%** | §5 |
| `MEMORY_QUALITY` 4 条 | 扩到 **9 条**（§5） | — |
| `ETYMOLOGY_CONFIRMED` | **结构性移除**：LLM 不产词源 | §1.3 |
| `IMAGE_COVERAGE ≥ 80%` | **BLOCKED** → P0 改 `IMAGE_PROMPT_COVERAGE = 100%`（试跑内） | §2.2 |
| `ANIMATION_COVERAGE ≥ 10%` | **BLOCKED**，P0 不做 | §2.2 |
| `FSRS_BINDING = 100%` | P0：100 词全部可解析 KC 且阶梯可渲染；**不写 KCMastery** | §6 |

---

## 8. 3O / 分层合规

| 关注点 | 归属 | 依据 |
|---|---|---|
| 单次 LLM 调用 | `oprim`（`vendor/oprim/_vocab_memory_generate.py`） | 单 LLM 调用 = oprim，不因复杂而升为 oskill |
| 上下文检索 / 质量门禁 / 阶梯渲染 / 编排 | `services/`（Layer 4） | 鉴权 + 编排 + 持久化装配，服务层零算法内核 |
| 生成走 `/mcp/*` | 是 | AGENTS.md 红线：唯一能力入口 |

新 oprim 落 `vendor/oprim/` 后，`scripts/sync_3o_from_platform.py --sync` 会把它记进
`3o-replication-lock.json` 的 `runtime_closure`，分类 `PROJECT_LAYER4`
（与既有 `oprim._vocab_gloss_generate` 同一处置）。**不手改 vendor 之外的 lock 字段。**

---

## 9. 扩展到 3,369 的前置条件（不是 P0）

1. 教材例句层落地（§2.1 解锁条件）→ `EXAMPLE_COVERAGE` 才可能上 95%；
2. 图片 provider 选定 + 成本上限 → `IMAGE_COVERAGE` 才可测；
3. 无语境 695 词的处置决策（补语料 / 接受 C 级 / 移出核心范围）；
4. 短语 608 条是否需要 MemoryNode（多数是搭配，`vocabulary_collocations` 可能已覆盖）；
5. 每层质量门在全量上的通过率必须**先在 100 词上验证**，再谈扩量。

---

## 10. 已知会被本 spec 触发的检查清单

- 新迁移 → `services/routers/health.py:EXPECTED_MIGRATION_HEAD` + `tests/test_nce_import_db.py` head 断言（STATUS 记载的第三个漂移源）；
- 新表 → 确认**不需要**进 `purge_service._STUDENT_TABLES`（§4 已给理由）；
- 新 oprim → `vendor_edu_closure.py` 文件存在性守卫 + lock `runtime_closure`；
- 任何 `pos`/释义写入 → 一律按 **id** 定位，`word` 在本表**不唯一**（2,761 单词 + 608 短语，另有跨集合重复词）。