# wrong-notebook 双嫁接（干净重写，只学方法）

参考：margrop/wrong-notebook v2026.11.1（MIT）。本嫁接**不复制**对方的任何
代码、文本、示例或提示词；TS 实现只读方法，全部 Python 逻辑为干净重写。
不接对方前端 / Prisma / 打包体系；不新增依赖；不改前端；不碰生产。

分支：`feat/wrong-notebook-graft`（基线 main `694c92a`）。
迁移：`wnb1a2b3c4d5e`（down_revision `all1a2b3c4d5e`），
`services/routers/health.py` 的 `EXPECTED_MIGRATION_HEAD` 已同步改为新 head
（2026-10-31 teachfig 部署实撞的教训：漏改则 `/readiness` 报 migrations:false）。

## 1. 组卷打印闭环（ExamSheet）

命名避让：`papers` 表是拍照录入的来源试卷（processing/done/failed），
组卷产物另称 exam sheet，表 `exam_sheets` / `exam_sheet_results`。

### 规格合同

`services/exam_sheet.py`（纯核）：

- `ExamSheetSpec`：`id`、`student_id`（路由注入）、`title`、`items[]`、
`include_answer_page`（默认 False）、`whitespace`（默认 `auto`）。
每项：`wrong_question_id` 必填；可选单题留白 `whitespace_px`；
可选配图键 `figure_key`（只验形态 `figures/<doc>/p<页>_<号>.png`，
同 `figure_crop.py` 的键纪律，不验存在性）。
- `assemble_exam_sheet(spec, owned_items, attempt_stats)` 确定性拼装：
只接受属于该学生的已存在错题，不存在 / 非本人即逐条列原因失败
（fail-closed，`question_not_owned`）；输出题目区 sections 与可选答案页，
每题带 `whitespace_px`、来源错题 id、作答历史计数（只读计数，不现编）。
题干 / 答案只取错题行快照；无答案的题答案页留空并标注（`unanswered`）。
- 入库的是**拼装后规格**（`questions` / `answer_key` / `unanswered` 均已落库），
导出直接渲染入库规格；`_present` 在返回时再叠加实时统计。

### 留白规则（自定数值，非对方数值）

- 模式：`auto` 按题型推断；`none` / `small` / `medium` / `large` 四档固定。
- 固定档（px）：none 0、small 64、medium 128、large 256。
- auto（px）：选择 48、判断 40、填空 72、解答 200 ＋ 80/小问、上限 480。
- 单题 override：整数 0..480，优先于模式。
- 题型推断只看题干文字（选项字母 ≥2 个→选择；判断词→判断；填空符→填空；
其余→解答），小问数按 `（n）` / `(n)` 计数。
- 单卷上限 50 题。

### 结果回填

- `POST /v1/exam-sheets/{id}/results`：只追加 `QuestionRecord` 行
（`source="exam_sheet"`、`grader="sheet"`、`meta.solution="exam_sheet"`、
`meta.sheet_id`），并走既有 `schedule_after_answer` 排期纪律；
**绝不直接写 BKT 掌握度**（BKT 是掌握唯一裁决源，FSRS 只排期——
word-atlas 嫁接的既定分工；测试断言回填后 `kc_mastery` 无新增行）。
- 口径（写死）：同一题在同一组卷内重复回填返回 **409**，必须先说明；
题不在本卷 / 原题不存在或非本人 → 422。`exam_sheet_results` 另有
`(sheet_id, wrong_question_id)` 唯一约束兜底。
- `wrong_question_id` 只存值不设 FK（同 `QuestionRecord` 惯例）。

### 导出

- HTML：自包含内联 CSS、A4 打印样式、无外部资源（对方实现链 KaTeX CDN，
本嫁接有意不同）；题目 + 留白（`min-height`）+ 可选答案页（新页）；
配图只列对象键 caption，不嵌图片字节、不出签名 URL。
- DOCX：只用 stdlib（`zipfile` + 手写 OOXML：`[Content_Types].xml`、
`_rels/.rels`、`word/document.xml`、`word/styles.xml`；固定时间戳求确定性）；
留白用空段段后间距承载（1px ≈ 15 twips）；配图只写 caption。
- 附件头：文件名含中文时裸写会触发 latin-1 编码失败，改为 ASCII fallback
+ RFC 5987 `filename*` 双写（途中修掉的真 bug，见 §5）。

### 路由与 MCP

- `POST /v1/exam-sheets`（仅本人；409 id 冲突 → 422 校验/拼装失败）、
`GET /v1/exam-sheets`（仅本人）、`GET /v1/exam-sheets/{id}`（他人 404）、
`GET /v1/exam-sheets/{id}/export?format=html|docx`（仅本人，attachment）、
`POST /v1/exam-sheets/{id}/results`（仅本人）。
- MCP 只读工具（既有模式现成可套，已接）：`POST /mcp/GetExamSheet`
（仅本人可见，他人/不存在报 `{"found": false}`，不泄露）。

## 2. SVG 动画讲解环（AnimatedExplanation）

`services/animated_explanation.py`（纯核）：

### 规格合同

- `AnimatedExplanationSpec`：`id`、`question_id`（可选，错题引用，只存值无 FK）、
`ku_id`（可选锚点，规格字段；行级 `ku_id` 列另存）、`title`（双语 `{zh, en}`）、
`language`（`zh` / `en`）、`steps[]`、`provenance`（复用 `provenance.py` 三档）。
- 每步：`scene`（复用 `animate_service` 的帧词汇：`shapes` 声明 + `frames`；
每帧的 `show` / `highlight` / `set` 只能引用已声明 shape）、
`narration_text`（必填双语非空）、`min_duration_ms`（有界）。
- `verify_animation`：10 项门（g1 schema；g2 语言字段；g3 步骤结构 1..20 步；
g4 旁白双语非空；g5 shape 声明闭合，复用 `SHAPE_TYPES`；g6 帧词汇
`FRAME_KEYS` + `show`/`highlight`/`set` 引用闭合 + `SETTABLE` + 帧时长
200..30000ms；g7 溯源齐全，material 须带 sources；g8 引用存在 fail-closed，
核验集不传时携带引用字段即不通过；g9 时长有界，单步 500..60000ms、
总计 ≤600000ms；g10 `verified` 字段禁带）。失败逐条列原因。
- `assemble_animation`：确定性拼装，`begin_ms` 累计时间线；输出步内键为
`narration`（非 `narration_text`）、`frames`、`shapes`；帧直接沿用
`animate_service` 的帧结构，不另造渲染器。
- 附 2 个自写参照动画（取自 Mneme 自有 K12 数学内容，各附 reset/分步期望）：
`linear_shift_spec`（一次函数 y=x+1 平移→y=x+3）、`pythagorean_spec`
（3-4-5 勾股验证）。两者溯源标签均为 `generated`，规格内不带 `ku_id` /
`question_id`（锚点由行级列承载，verify 时由路由传入核验集）。

### 不做的事（明确的后续项）

- **不做 AI 生成**：spec 由作者 / 确定性拼装提供，本次不调任何 LLM；
AI 生成动画是后续项。
- **不做请求时 TTS 合成**（成本与延迟原因）：spec 只带 `narration_text`，
拼装结果返回 narration 供前端用 Web Speech 或后续 TTS。
既有结论：edge-tts 在本机 egress 代理下 WebSocket 不可用、云端 TTS 付费。

### 持久化与接线（照搬 teaching_figures 纪律）

- 同一迁移内新建 `animated_explanation_specs` 表（`id`、`question_id`、
`ku_id`、`spec` JSONB、`verified` 默认 False、`author_id` FK users、
created/updated）。
- `POST /v1/animated-explanations`（admin，`verified` 恒 False，规格内带
`verified` 键即拒）、`GET` 列表/详情（学生仅见 verified，未验证对学生 404）、
`POST /v1/animated-explanations/{id}/verify`（admin，服务端重跑门禁，
全过才置 `verified`）、`GET /v1/animated-explanations/{id}/assemble`
（返回 steps + frames + narration；学生仅 verified 可见）。
- MCP 只读工具：`POST /mcp/GetAnimatedExplanation`（学生仅见 verified，
未验证/不存在报 `{"found": false}`）。

## 3. 与参考实现的有意偏差（任务书口径优先）

1. 参考的组卷是 AI 生成变式题；Mneme 版组的是**原错题快照**（题干/答案
只取错题行，不现编）。
2. 参考允许同一题多次录入结果；Mneme 版定死**重复提交 409**。
3. 参考 HTML 导出链 KaTeX CDN；Mneme 版**自包含、无外部资源**。
4. 参考有 SMIL/Web Speech 运行时；Mneme 版只存 `narration_text`，不做
运行时语音合成（见 §2 后续项）。

## 4. 测试

新测 `tests/test_wrong_notebook_graft.py`：**32 passed**（只连 `mneme_test`）。
覆盖：组卷拼装正反例（非本人/不存在错题、留白越界、答案页、配图键）、
HTML/DOCX 导出内容断言（DOCX zip 完整、XML 良构、含全部题干）、结果回填
（QuestionRecord 追加 + 排期纪律 + 重复提交 409 + 不写掌握度）、动画规格
校验各失败模式、verify 绕不过门禁、迁移 upgrade/downgrade 真跑（克隆库）、
pin==单头断言、MCP 只读工具。

相关旧测：**141 passed、3 skipped**（含 `test_teaching_figure_spec.py` 等 10 个
文件）。其中 teachfig 的迁移测试按链演进更新了三处（单头断言改为
`wnb1a2b3c4d5e`、补 wnb down_revision 断言、克隆库清表补三张新表），
其余一字未改。

ruff：改动文件全过。

如实记录的既有缺陷（不修）：共享 `mneme_test` 的 `alembic_version` 行漂移在
他分支 revision；全链空库 upgrade 在 word-atlas 迁移处已断（建 FSRS 卡表时
`vocab_units` 不存在）——迁移测试走克隆库 + stamp 父 revision 绕过。

## 5. 途中修掉的真 bug（均已复验）

1. **写文件工具的 `` 标记处理**：`exam_sheet.py` 初版含 `` 正则，
整文件缩进被剥掉且该片段消失（AGENTS.md 已有此教训）；改用 `[]` 后
全文件重写，远程 `py_compile` + md5 验妥。
2. **导出附件头 latin-1 编码失败**：中文文件名裸写进 `Content-Disposition`
致 500；改为 ASCII fallback + RFC 5987 `filename*` 双写。
3. **结果路由 commit 后 MissingGreenlet**：`await db.commit()` 后再取 `row.id`
触发过期刷新；改为 commit 前快照 `sheet_id`（与 teachfig 路由同一纪律）。
4. **迁移测试密码被打码**：`str(URL)` 把密码打成 `***` 致子进程 alembic
认证失败；改用 `render_as_string(hide_password=False)`。
5. **测试断言写错的实码**：动画门禁的真实 issue 码以
`services/animated_explanation.py` 前台直读为准
（`bad_step_count` / `missing_language` / `not_settable` /
`frame_duration_out_of_range` / `step_duration_out_of_range` /
`material_needs_sources` / `bad_label` / `question_not_found` /
`ku_not_found`），拼装步内旁白键为 `narration`，参照动画溯源为
`generated`——初版测试按印象写的码与形态已全部按实纠正。

## 6. 部署步骤（未执行，等 Soffy 另行拍板）

1. 备份生产库（整库 dump，参照历次部署备份目录）。
2. `git merge --ff-only` 本分支进 main 并 push（生产 checkout 在
`/data/soffy/projects/mneme`，api 代码 bind 挂载）。
3. 只 `docker compose restart api`（无新依赖，无需重建镜像）。
4. 迁移一次成功：`alembic_version` 由 `all1a2b3c4d5e` → `wnb1a2b3c4d5e`；
验 `/readiness` 全 true（pin 已同步）、`/health` 200。
5. 冒烟（冒烟号，凭证只在远程 shell 内 source）：未登录新路由 401；
组卷创建→导出→回填→动画 verify→学生可见链路 200（admin 链路生产侧
须 ADMIN_USER_IDS 白名单账号，测试未覆盖真机 admin，见 §7）。
6. 回退：后端 revert 本合并提交 + `alembic downgrade all1a2b3c4d5e` +
重启 api；无数据迁移回写（新表空表可直接删）。

## 7. 未验证项与待接点

- 桌面 Word 真机打开 DOCX 未验（只验了 zip 完整与 XML 良构）。
- admin 创建→verify→学生可见链路未真机跑（冒烟号非 admin 白名单；
行为由测试覆盖，与 teachfig 部署时同一口径）。
- 待接点：渲染器 / 前端展示、AI 生成动画、图片嵌入导出、音频合成、
MCP 之外的前端组卷入口、前端 provenance/figures 展示。
- 链演进提醒：下一次新迁移须同步改 `EXPECTED_MIGRATION_HEAD`、
本文件的 pin 测试与 teachfig 迁移测试的单头断言。
