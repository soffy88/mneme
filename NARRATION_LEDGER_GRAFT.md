# G1 嫁接：narration 逐句出处台账契约

- 来源：vibe-knowledge 审查（`~/workspace/goals/mneme-pansgo/files/vibe-knowledge审查与Mneme对照.md`）G1 项，Soffy 2026-11-05 点选“只接 G1”。
- 方法来源：只学 facts 台账的**结构**（逐句断言行、分级、分歧两说并列、对抗审查记录）；措辞、标识、规则均为 Mneme 自写，未搬上游原文、提示词、样片稿、素材。
- 状态：分支 `feat/narration-source-ledger-g1`，未合并、未 push、未部署。

## 契约

模块 `services/narration_source_ledger.py`（纯函数，无 DB、无网络、无 LLM）：

| 结构 | 规则 |
|---|---|
| 台账行（一行一断言） | `id` 形如 L01 且唯一；`claim` 非空、≤120 字；`shot` 须是已存在的场景下标；同一断言不得在同一拍出现两次 |
| 出处证据 | 每条证据含非空 `source`、有效分级、非空原文摘录（≤400 字） |
| 分级 T1/T2/T3 | T1 原始/官方（教材原文、原始文献、官方页）；T2 权威二手（教材论述、带引用的百科、主流报道）；T3 社区线索，永不单独支撑上屏断言 |
| 溯源档位 | 行的 `label` 必须是现有三档之一（MATERIAL/SUPPLEMENT/GENERATED），消费 `services/provenance.py` 的档位、不另起体系 |
| 档位与证据 | MATERIAL 须至少一条 T1/T2 证据；SUPPLEMENT 须至少一条证据；GENERATED 为串场文字，须无证据、状态为 framing |
| 状态与证据 | verified 须 T1 或两条 T1/T2；single-source 须恰好一条 T1/T2；disputed 须完整 alternative（另一说的主张/出处/分级/摘录）＋T1/T2 支撑；framing 仅 GENERATED |
| 对抗审查记录 | 须具名审查者，四项检查（无无出处断言、每行已分级、分歧已两说并列、摘录齐全）须全过 |
| 覆盖 | 每个事实拍须至少一行台账覆盖；无台账的脚本 fail-closed（`missing_ledger`） |

## 与现有门禁的分工

- `services/provenance.py`：三档标签归属与“每段必带标签”门（回答段）。
- `services/citation_check.py`：引用解析（KU/教材/图须真实存在）与数学等价核查（回答段）。
- 本模块：逐句断言台账（旁白脚本）。不解析 KU/教材 id，不重定义档位。

## 持久化：零迁移

台账以结构化数据随 lesson 脚本走，位于 `spec["source_ledger"]`，存入既有 `VideoLessonSpec.spec` JSONB 列。不新增表、不新增迁移、不改 health pin。

## 调用点（唯一一处新增调用）

`services/routers/video_lessons.py` 的 `_gate_or_422` 增加 `require_ledger` 参数（默认 False）：

- create：不要求台账（草稿可先建，学生不可见）。
- verify / assemble：`require_ledger=True`，台账门不过则 422（沿用既有 `video_lesson.gate_failed` 文案，未新增 i18n key）。
- `services/video_lesson.py` 的十项门禁一字未改；`certify_lesson_script` 是组合入口（十项门禁＋台账门），供渲染前调用。

## 测试

- `tests/test_narration_source_ledger.py`：契约正例、缺出处/缺分级/缺摘录/分歧未并列/拍号不一致/覆盖缺失/审查记录不全均 fail、与 provenance 档位衔接、dataclass 往返、组合认证。
- `tests/test_all_grafts_routers.py`：`_video_spec` 夹具补有效台账，create→verify→assemble 全流程仍过。

## 未做事项

- 前端台账展示、MCP 工具：未建（本步只做契约＋门禁）。
- 既有已验证视频课规格的台账补录：生产 `video_lesson_specs` 现为 0 行，无存量需要补。
- 合并/部署：待 Soffy 定。
