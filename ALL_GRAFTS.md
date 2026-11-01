# 9 项全嫁接（DeepTutor 方法 4 项＋Parroto 方法 5 项）

分支 `feat/all-grafts-batch`，基线 main `694c92a`。全部干净重写、只学方法；
不改前端、不新增依赖、不调 LLM 做内容生成、不做请求时 TTS/STT 合成；
BKT 是掌握唯一裁决源、FSRS 只排期；verified 只由服务端门禁设置；
既有行为一字不改。生产部署不在本分支授权内，见末尾“部署与回退”。

方法来源与许可证红线：DeepTutor（HKUDS/DeepTutor，Apache-2.0）只取方法
（视频课循环、数学保义引用核查＋eligibility 门、任务板＋日历、检索评估
harness）；Parroto（parroto.app，闭源商业产品）只学方法（听写环、跟读环、
分级有声＋逐词高亮、模考包装），绝不搬其视频/题库内容；离线/外部知识
引擎、语伴匹配、游戏三项明确没接。

## 1. 视频课循环（DeepTutor）

- 合同：`services/video_lesson.py`——10 项门禁 `verify_video_lesson`（场景/
  帧/字幕/形状/旁白预算与引用）、确定性组装 `assemble_video_lesson`（只出
  场景＋字幕＋旁白文本，不产媒体）、顺序进度 `advance_progress`（乱序不计）；
  参照课《三角形内角和》`triangle_angle_sum_spec`（3 景 3 字幕）。
- 持久化：`video_lesson_specs`（ku_id 锚点可选，verified 默认 False）。
- 路由：`services/routers/video_lessons.py`——`POST /v1/video-lessons`（admin）、
  `GET /v1/video-lessons`（学生仅见 verified）、`GET /v1/video-lessons/{id}`、
  `POST /v1/video-lessons/{id}/verify`（admin，服务端重跑门禁）、
  `GET /v1/video-lessons/{id}/assemble`（重跑门禁后组装）。
- MCP：`GetVideoLesson`（只读快照，仅 verified）。
- 偏差：assemble 端点重跑门禁（fail-closed：锚点 KU 被删后不再组装）；
  ku_id 锚点可选（无锚点课仍可建，由门禁决定可见性）。
- 待接点：前端播放器（场景/帧/字幕渲染）、视频旁白 TTS 离线产出链路、
  进度持久化（目前 `advance_progress` 为纯函数，进度不落库）。

## 2. 引用核查＋eligibility 门（DeepTutor）

- 合同：`services/citation_check.py`——`check_citations` 逐段核查引用
  （`refs: [{kind: ku|textbook|figure, id}]`；ku/textbook 查库内真实 id 集合，
  figure 查 key 格式；未知集合 fail-closed）；数学断言默认不做定性判定
  （`math_unverifiable`，不编造结果）；`eligible_review_scope` 按既有路径锁
  只读拆分 allowed/denied，理由原样返回。
- 路由：`services/routers/citation_check.py`——`POST /v1/citation-check/verify`
  （无状态，调用方提交分段；已知 id 集合由服务端从库内查存在性后传入）、
  `POST /v1/citation-check/eligibility`（仅学生本人，`_ensure_student_self`）。
- MCP：无（stateless 函数调用，不设 MCP 工具）。
- 偏差：verify 端点对空分段判 422（`check_citations` 本身返回 `passed: False`
  带 `empty_segments` issue；端点层用 422 表达“请求不合法”）；eligibility
  仅本人，家长/管理员不走此端点；数学定性判定无 HTTP 入口传回调。
- 待接点：chat 严格门 `strict_provenance` 默认关（循环尚无分段标签时不开）；
  定性判定回调接入（`qualitative_verify`）。

## 3. 任务板＋日历（DeepTutor）

- 合同：`services/task_board.py`——`validate_task_payload`（标题/状态/日期/
  位置）、`apply_move`（只改 status/position）、`sort_tasks`（position 优先，
  归档最后）、`build_calendar`（任务到期＋FSRS 到期按日合并，只读视图）。
- 持久化：`study_tasks`（`status` 取值以 `TASK_STATUSES` 为准：
  todo/in_progress/done；`position` 排序；`archived` 归档）。
- 路由：`services/routers/tasks.py`（创建/列表/详情/更新/移动/归档/恢复，
  仅本人，他人 id 一律 404）、`services/routers/calendar.py`
  （`GET /v1/calendar`，默认当天起 14 天；review 条目键为 `fsrs_due`）。
- MCP：`GetTaskBoard`（只读，仅本人任务，板序排列）。
- 偏差：创建接受客户端传 `id`（UUID，重复判 409）；`due_date` 只接受 ISO 日期
  字符串；日历 review 侧以 `WrongQuestion.fsrs_due` 为准。
- 待接点：前端看板/日历展示；任务与学习计划联动。

## 4. 检索评估 harness（DeepTutor）

- 合同：`services/retrieval_eval.py`——`METRIC_KEYS`（recall@k/precision@k/
  ndcg@k/mrr/map/hit@k）、`score_ranking`/`score_rankings`（离线打分）、
  `eval_diff`（两次运行的逐指标差值＋变化用例）、`score_retrieval`（走真实
  `search_knowledge_base` 的 live 打分，gold 按 chunk id 集合）。
- 固件：`tests/fixtures/retrieval_eval_qa.jsonl`（24 条）与
  `tests/fixtures/retrieval_eval_baseline.json`（k=5 回归 pin，由容器实跑
  `score_rankings` 生成；aggregate：recall@k 1.0、precision@k 0.2833、
  ndcg@k 0.7889、mrr 0.7153、map 0.7083、hit@k 1.0）。
- MCP：无（离线 harness，不设 MCP 工具）。
- 偏差（重要）：固件 gold chunk id 为 synthetic 占位（`chunk:synthetic/*`），
  未接真实 chunk id——baseline 是“固定 ranked 下的回归 pin”，不是检索质量
  基线；`score_retrieval` 未在测试中跑真检索（无 embedding/知识库夹具），
  仅离线部分有测试覆盖。
- 待接点：以真实 chunk id 策展 QA 集（查询＋gold 均来自真实知识库行）后重算
  baseline；把 harness 接入 CI 做检索回归门。

## 5. 听写环（Parroto）

- 合同：`services/dictation.py`——6 项门禁 `verify_dictation_spec`（段索引
  连续、段长上限、source 种类、段-文一致性 fail-closed、verified 字段禁传）；
  `tokenize`（小写归一）/`diff_words`/`grade_dictation`（逐段＋整篇计分）；
  `compute_dictation_schedule`（detached FSRS 卡排期，不碰 WrongQuestion）；
  3 篇自写短段 `self_written_passages`（levels 1–3）。
- 持久化：`dictation_specs`＋只追加的 `dictation_attempts`（成绩、错词、FSRS
  排期快照；音频/原文永不入库）。
- 路由：`services/routers/dictation.py`——规格 CRUD＋verify（admin，graded_passage
  须以 `source.passage_id` 溯源 `ReadingPassage.body_text` 做一致性核验）、
  `GET /v1/dictation/passages`（自写短段）、`POST /v1/dictation/specs/{id}/attempts`
  （判分＋排期＋错词以 `QuestionRecord` 行追加，source="dictation"，不写 BKT/FSRS
  到 WrongQuestion）、尝试列表。
- MCP：`GetDictationSpec`（只读快照，仅 verified）。
- 偏差：`tokenize` 小写归一，`missed_words` 均为小写；错词 QuestionRecord 的
  `student_answer` 置空（只知错词，不知其 typed 对应）；`subject` 取 spec 的
  subject 字段、无则默认 english；`passage_id` 在 `source` 对象内（非 spec 顶层）。
- 待接点：音频播放/录音前端；错词复测队列与 FSRS 卡的联动展示。

## 6. 跟读环（Parroto）

- 合同：`services/shadowing.py`——5 项门禁 `verify_shadowing_spec`
  （`target_sentences` 字符串列表、level 1–5、verified 字段禁传）；
  `score_shadowing`（发音/转写双调用均可注入 fake，默认走既有
  `wrap_pron`/`wrap_stt`；评分维度只取 `PronunciationResult` 合同：
  overall/fluency/accuracy/word_scores，不编造语调/节奏维度）。
- 持久化：`shadowing_specs`＋只追加的 `shadowing_attempts`（评分、转写、弱项词；
  音频永不入库）。
- 路由：`services/routers/shadowing.py`——规格 CRUD＋verify（admin）、
  `POST /v1/shadowing/specs/{id}/attempts`（`sentence_index` 越界判 422、
  空音频判 422）、尝试列表。
- MCP：`GetShadowingSpec`（只读快照，仅 verified）。
- 偏差：规格句序字段为 `target_sentences`（字符串列表），不是 `sentences` 对象列表；
  尝试不做 TTS/STT 合成，只调既有服务。
- 待接点：韵律（语调/节奏）评分维度（需发音服务先返回该维度，禁止前端编造）；
  弱项词复练闭环。

## 7. 分级有声＋逐词高亮（Parroto）

- 合同：`services/graded_audio.py`——6 项门禁 `verify_graded_audio_spec`
  （文本非空、source 种类、段-文一致性 fail-closed、对齐长度与时间单调性）；
  `assemble_graded_audio`（分句＋词级时间码原样透传；无对齐时
  `word_timings: null`、`highlight_level: sentence`，不编造时间码）。
- 持久化：`graded_audio_specs`。
- 路由：`services/routers/graded_audio.py`——规格 CRUD＋verify（admin，
  `source.passage_id` 溯源规则同听写）、`GET /v1/graded-audio/specs/{id}/assemble`
  （重跑门禁后组装播放数据）。
- MCP：`GetGradedAudioSpec`（只读快照，仅 verified）。
- 偏差：无对齐时句子 `start_ms`/`end_ms` 均为 null；不做请求时 TTS，音频由既有
  管线离线产出。
- 待接点：对齐数据生产链路（强制对齐能力待验）；前端逐词高亮播放器。

## 8. 模考包装（Parroto）

- 合同：`services/mock_exam.py`——6 项门禁 `verify_mock_exam_spec`（section 秒数
  区间、题目去重＋存在性、`total_seconds` 等于 section 秒数和、verified 字段禁传）；
  `assemble_mock_exam`（只出题面，答案永不包含）；`score_mock_exam`（确定性判分，
  `grade_deterministic` 为主、math 科目回退 `grade_math`；`late` 只记位、不改分）。
- 持久化：`mock_exam_specs`＋只追加的 `mock_exam_attempts`（答案与评分明细快照）。
- 路由：`services/routers/mock_exams.py`——规格 CRUD＋verify（admin，存在性以库内
  全部 `WrongQuestion` id 集合核验）、assemble、submit（作答须覆盖全部题目，
  否则 422；`elapsed_seconds` 超 `total_seconds` 记 late）、尝试列表。
- MCP：`GetMockExamSpec`（只读快照，仅 verified）。
- 偏差：未复用 `submit_quiz`（它会写 BKT/FSRS）；交卷可多次（只追加，无幂等键）；
  题目来源只认 `WrongQuestion` 行（quiz 题目即 WrongQuestion 行）。
- 待接点：计时/防切屏等考试纪律（前端＋监考）；成绩单与复盘入口。

## 9. i18n 基建（zh/en）

- 合同：`services/i18n.py`——`SUPPORTED = (zh, en)`，默认 zh；`negotiate_language`
  （显式 `lang` 优先，其次 Accept-Language q 值排序，其余 zh）；`t(key, lang)`
  （zh 回退、再回退到 key 本身）；`CATALOG` 覆盖 9 项新模块的用户可见字符串。
- 约束：新路由的用户可见字符串一律走 `t()`；测试静态扫描 8 个路由文件的
  `t("…")` 字面量、断言全部在 CATALOG 有 zh＋en。
- 偏差：缺 key 时 `t()` 返回 key 本身（不是 `[missing:key]`）；catalog 键名以
  `services/i18n.py` 的 CATALOG 为准（如 `video_lesson.not_found`）。
- 待接点：前端翻译（后续项）；更多语种 catalog；既有模块字符串迁移。

## 迁移与 pin

- ONE 个迁移 `all1a2b3c4d5e`（`down_revision=tfg1a2b3c4d5e`），9 张表：
  video_lesson_specs、dictation_specs、dictation_attempts、shadowing_specs、
  shadowing_attempts、graded_audio_specs、mock_exam_specs、mock_exam_attempts、
  study_tasks；downgrade 全量回退。`services/routers/health.py` 的
  `EXPECTED_MIGRATION_HEAD` 已同步为 `all1a2b3c4d5e`；单头断言在
  `tests/test_all_grafts_batch.py`（新）与 `tests/test_teaching_figure_spec.py`
  （已更新：stamp 仍为 f9a1b2c3d4e5，升级后断言新 head，升级前删 10 张固件表）
  两处真跑通过。`alembic heads` 单头已验。
- 既有缺陷只记录不修：共享 mneme_test 版本行漂移（prq1a2b3c4d5）与空库全链
  upgrade 在 word-atlas 迁移处断裂（见 teachfig 迁移测试 docstring）。

## 测试证据（容器法：--network host＋生产 .venv/.env 只读挂载，uid 1000）

- 新测：`tests/test_all_grafts_batch.py` 27 项、`tests/test_all_grafts_routers.py`
  12 项，合计 39 passed（前台直读，含迁移克隆库真跑 upgrade/downgrade）。
- 相关旧测：`tests/test_teaching_figure_spec.py` 43 passed。
- ruff：新/改文件全过（行宽 88、py312）。
- 覆盖率门（60%）在子集运行时不达标（25%），属子集运行 artifact，非回归信号；
  全量套件以 `scripts/check.sh` 为准。

## 途中修掉的真 bug（均已复验）

1. `services/mock_exam.py` 的 `score_mock_exam` 从 `services.wrongbook_review_service`
   导入不存在的 `grade_math`（调用即 ImportError）。已改：`grade_math` 从
   `services.math_grade` 导入、`grade_deterministic` 保留原导入；实跑验证答案 "2"
   得 1.0、答案 "3" 得 0.0。
2. `StudyTask(id=None)` 会显式 INSERT NULL 到 server-default 主键。已改：仅当
   客户端传 id 时才赋值。
3. 跟读路由读错字段（`sentences` 对象列表）。已改：以门禁为准读
   `target_sentences` 字符串列表。
4. 听写/分级有声路由在 spec 顶层读 `passage_id`。已改：以门禁为准读
   `source.passage_id`。
5. 日历路由给 `build_calendar` 的 review 条目用 `due_date` 键。已改：用
   `fsrs_due`（门禁/视图合同字段）。
6. 模考路由以字符串 id 查 UUID 主键。已改：绑定前解析为 `uuid.UUID`。

## 未验证项

- admin 链路真机（冒烟号非 admin，行为由测试覆盖；与 teachfig 同口径）。
- 前端展示（本分支不改前端，8 路由＋6 MCP 工具均无前端）。
- `score_retrieval` 真检索、`wrap_pron`/`wrap_stt` 真 vendor 调用（只测 fake 注入
  与离线 harness）。
- DOCX/Word 真机打开（本分支无 DOCX 产出，不适用）。

## 部署与回退（须 Soffy 拍板，未执行）

1. 备份生产库（整库 dump，参照 teachfig 部署备份口径）。
2. `git merge --ff-only` 本分支到 main 并 push（若 Atlas Mneme 分支
   `feat/atlas-physics-models`（迁移 `phy1a2b3c4d5e`，同样
   `down_revision=tfg1a2b3c4d5e`）先合入：后合者须 rebase 改
   `down_revision`＋pin＋单头断言；先合者占位）。
3. 生产 checkout 拉取后只 restart api（bind 挂载），跑 `alembic upgrade head`。
4. 验 `/readiness` 全 true、`/health` 200；冒烟 8 路由＋6 MCP 工具。
5. 回退：revert 合并提交＋`alembic downgrade tfg1a2b3c4d5e`＋重启 api。
   回退点：main `694c92a`（alembic head `tfg1a2b3c4d5e`）。
