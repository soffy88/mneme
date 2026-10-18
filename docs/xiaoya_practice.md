# 小雅英语陪练 (Xiaoya English 陪练) — 设计说明

> 工作分支：`feat/xiaoya-practice`（基于 `release/v0.1.0-rc5`）
> 原型实现所在：`/data/soffy/projects/hevi-live`（hevi-live，`feat/live-host-3o`）
> 状态：**设计 + 原型**，未部署、未改动生产、未跑迁移。

## 1. 目标

把善学记（Mneme / api.sxueji.com）已有的英语教材内容，交给直播数字人「小雅」做口语陪练：

- 学生说/打一句英语 → 小雅从**预生成**的教材音频库里检索最近的一句（用自己的声音），回放音频 + 动作；
- 用 Mneme 既有的 `check_english_answer` 确定性批改逻辑给学生的作答打分（等价、听写、he/she 指代、句型）；
- 全程**不上实时 GPU 生成**：声音、视频、文本都进 EmbeddingGemma 2 的同一 768 维空间，直播变成「检索」，符合用户「text/audio/video/motion in one EG2 space」的方向。

## 2. 现状盘点（已确认）

以下均以本地 docker 只读查询核对（`docker exec mneme-db-1 psql -U postgres -d mneme`，
`SET default_transaction_read_only=on`），未连接 prod / api.sxueji.com。

- **英语教材内容已入库**：
  - PEP 人教版英语：`textbook_sentences` 表，12 本书、2869 条 OCR 句子（按页索引，**无 `unit` 列**）。
    有句子的书（`textbooks` 表）：七上 630、七下 731、八上 682、八下 470、九全 356；高中各册注册但 0 句。
    pilot 用的书 id = `pep-en-g7a`（义务教育教科书 英语 七年级上册）。
    **Unit 1 = 第 11–15 页**（问候/自我介绍聚类）；第 7–9 页是 starter 页/其他单元，第 16 页起是 OCR 噪声。
    本地 OCR 导出：`reports/vocab_memory_p0/pep_ocr_sentences.json`（结构与 DB 一致）。
  - 新概念英语 NCE：`timed_sentences` 表存在，按 lesson_key 索引（本原型未使用）。
  - **版权提示**：PEP 行 `license_status='unlicensed'`，学生面向内容，做整书 takedown 友好；demo 仅用 g7a Unit 1 一个单元做 pilot。
  - 表中 `chinese_text` **全为空**（0/2869），中文释义不在教材行里，需自备或走既有词汇表。
- **批改内核可复用**：`vendor/oskill/english_answer_check_skill.py` 的 `check_english_answer(request)` 是**纯函数、无状态、无 IO、无 LLM**，组合 oprim 原语（`english_answers_equivalent` / `score_dictation_words` / `find_pronoun_errors` / `uses_pattern`）。可直接 in-process 调用，**不经过** `POST /v1/english/check` 的鉴权与 `question_record` 写入。请求/结论模型为 `EnglishCheckRequest` / `EnglishCheckVerdict`（Pydantic）。
  已在本地验证：大小写/句末标点不敏感答案等价可判对；`He is my friend.` vs `She is my friend.`（中文上下文「她是我的朋友」）**未**报指代错——见 §6 待确认。
- **可运行的本地解释器**：mneme 仓库自身无 `.venv`（只有 `.venv-echo`，缺 structlog）；已备好 `/data/soffy/venvs/hevi-oskill`（有 structlog/pydantic），配 `PYTHONPATH=<mneme>:<mneme>/vendor` 可直接 import oskill/oprim。
- **已有口语练习骨架**：`vendor/oskill/_english_speaking_practice.py`（`topic` → `SpeakingPracticeResult`，注入 `tts/stt/pronunciation_eval/llm`，带 `_ensure_encouraging` 不直接纠错）。小雅的循环 = 该骨架 + `check_english_answer` 打分，无需重建。

## 3. 原型架构（hevi-live 侧）

```
教材句子 ──► CosyVoice3 跨语言 zero-shot（同一女声 prompt）
            └─► /data/soffy/englib/<book>/<unit>/  { manifest.json, wav/, index.npz(EG2 text 768) }

练习循环（本地）：
  student text ─► EG2 检索最近教材句(target) ─► 比对 check_english_answer
                                          └─► 小雅回放 target 的缓存音频 + motion
```

- 生成脚本：`hevi/live_host/eng_lib/build_unit.py` → 一个单元（pilot 用 pep-g7a / u1，22 条 OCR 句 + 精选词汇/对话，共 38 条）。
- 练习循环：`hevi/live_host/eng_lib/practice.py` —— 函数 API `PracticeSession.respond(text)` + 本地 HTTP（127.0.0.1:8791）。
- 评分：直接 `from oskill.english_answer_check_skill import check_english_answer`（PYTHONPATH 含 `vendor`），不重写逻辑。

## 4. 视频（口型/lipsync）策略

- **按需渲染，不落盘整段视频**（除少数样例）。小雅的声音 + 动作（halfbody  clips：g_wave/g_nod/g_heart/g_both/g_lean/talk_a/talk_b/idle）已是 EG2 检索体系的一部分（见 motionrag）；检索到的教材句带 `motion` 提示，运行时喂给 Wav2Lip 即可。
- `build_unit.py` 只存 wav + 文本向量；`practice.py` 在需要时联动 motionrag 选动作、用 halfbody 渲染短片段。

## 5. 生产接入建议（未来，非本次）

1. **资产入库 AII/Stratum**：每条教材音频作为 `media_asset(kind=voice_clip, embedding EG2 768)` 入 Stratum（契约见 `/data/soffy/motionrag/stratum_contract.md`），库内检索走本地 npz，网络只用于构建期。
2. **Mneme 侧端点**：新增 `POST /v1/english/practice` 或复用 `/v1/english/check`，由 Mneme 编排「给句 → 收学生作答 → 调 check_english_answer → 返回反馈」；音频由 hevi-live 侧按 unit/句 id 提供。
3. **鉴权与计费**：练习会话需要学生身份与额度，走现有 Mneme 会话体系，不在本原型范围。

## 6. 本次未做 / 待确认

- 未部署、未改生产数据库、未跑迁移（遵守「production = 本机」约束）。
- 仅 pilot 一个单元；整本书/跨书需要教材授权与批量生成（CosyVoice3 CPU RTF ≈ 8–9，整库需分批后台跑）。
- `check_english_answer` 的 he/she 指代在「她是我的朋友 → He is my friend」用例下**未**报错（实测 `answer_ok=False`、`pronoun_errors=[]`；`answer_ok` 是答案不等价导致的，不是指代检查发现的）。建议回归 `find_pronoun_errors` 的触发条件（非本原型阻塞项）。
- 英语 CosyVoice3 跨语言音质需人工听评；若差，fallback 到 Kokoro `af_*` 仅在 hevi 侧报告，不在 Mneme 侧决定。
- 教材行没有中文释义（`chinese_text` 全空），pilot 的中文 gloss 为人工/派生；接入时应改接既有词汇表（`vocabulary_derived_glosses` / `vocabulary_dictionary_glosses`）。
- 真人配音版权：教材音频用小雅自己的声音合成，不涉及原教材录音；但教材文本本身仍受版权约束，整书 takedown 需保证可批量删除（按 `textbook_id` 即删）。
