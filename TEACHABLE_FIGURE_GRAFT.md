# 教学图规格＋验证门嫁接（分支 feat/teachable-figure-spec）

teachable-figures（predict → try → explain）方法论的 Mneme 干净实现：
方法可学，代码自己写，未复制对方 SKILL 文本、示例、参考文档或任何
代码。生产部署不在本分支授权内，等 Soffy 另行拍板。

## 改动清单

- 新建 `services/teaching_figure.py`（纯函数，无 DB/网络/LLM）：
  规格合同（id / ku_id 锚点 / 双语 title·lead·insight·caveat·frame /
  predict 选项 + 最佳答案 / 必填 misconception / config / renderer_hint /
  model_ref）、数字三标签（source_fact / calculation / illustrative，
  未标者门禁不通过）、真值模型协议（initial_state / apply_action /
  derive，时间模型可加 step；非法输入 clamp、拒绝不可能状态）、
  2 个自写参照模型（比例关系、二次增长；公式自述，取自 Mneme 自有
  K12 内容）、随机性口径（种子可复现、期望与采样分开）、验证门
  `verify_figure`（10 项，失败逐条列原因）、`spec_provenance`
  （复用 provenance.py 的档位与引用形态）。
- 新建 `alembic/versions/tfg1a2b3c4d5e_add_teaching_figure_specs.py`
  （down_revision f9a1b2c3d4e5）：表 teaching_figure_specs（id / ku_id /
  spec JSONB / verified 默认 False / author_id / created_at / updated_at
  + ku_id 索引）。
- `services/models.py` 追加 `TeachingFigureSpec`（同仓内模型惯例）。
- 新建 `services/routers/teaching_figures.py`（POST 创建 / GET 列表 /
  GET 详情 / POST verify；创建与验证仅 admin，沿用
  obase.admin_identity.is_admin；学生仅见 verified；verify 端点服务端
  重跑门禁，全过才置 verified）。
- `services/routers/__init__.py` 注册新路由模块。
- 测试 `tests/test_teaching_figure_spec.py`（纯函数 + 库上路由 + 迁移）。

## 门禁 10 项

1. schema 合法、id 唯一、必填齐全（verified 字段禁止由规格携带）；
2. 锚点 KU 真实存在（fail-closed：不传核验集即不通过）；
3. 恰好一个最佳答案且选项 2–4 个（中英数量一致）；
4. misconception 存在且与最佳答案不同；
5. caveat 双语非空且达长度下限（“写了”可验，“写得对”靠作者自查，
   如实记录，非语义判定）；
6. 模型期望一致（≥2 条、含复位态与跃迁态；clamp/拒绝行为由模型
   测试覆盖）；
7. reset 恢复初始派生态、apply_action 不改输入态、视图键不与语义
   态键重叠；
8. 数字三标签全覆盖（结构性数值 answer_index / seed / tolerance 与
   actions 子树除外）；
9. renderer_hint 在 svg-2d / iso-lite / iso-mechanical / turning-3d /
   webgl 五档内；
10. 语言字段齐全（title / lead / insight / caveat / frame /
    misconception 均含 zh + en；language 为 zh 或 en）。

设计注记（design_note：有意义的一次尝试、两个解释要点、迁移新案例）
为作者自查项：缺失只记 note，不判分；若提供 explanation_points 须
恰好两条。

## 迁移验证（如实记录）

- 迁移链单头已验（tfg1a2b3c4d5e ← f9a1b2c3d4e5）；本迁移的
  upgrade（建表＋索引）与 downgrade（删索引＋删表）在克隆库内走
  真实 alembic CLI 跑通过（克隆 mneme_test → 删固件表 → 版本行直
  写父 revision → upgrade head → downgrade 回父 revision → 删库）。
- 两个既有状态，本次不越界修：① 共享 mneme_test 的版本行现指
  prq1a2b3c4d5（其它分支迁移留下的版本行，本分支链内无此 revision），
  故测试固件按迁移同源 DDL 自建表（IF NOT EXISTS，仅测试库）；
  ② 全链从空库 upgrade 在既有 word-atlas 迁移处已断（建 FSRS 卡表
  时 vocab_units 不存在）——生产增量升级不受影响（见部署前置检查）。
- 生产部署前置检查（必须）：先只读查生产 alembic_version，须为
  f9a1b2c3d4e5（word-atlas 部署后的链头）；若不是，先停、查明版本
  行漂移原因再升级，绝不在生产库上 stamp。

## 偏差与取舍（如实记录）

1. 双语字段形态：仓内无既有 zh/en 字段惯例可循，故 title 等 copy
   字段定为 {"zh","en"} 双语对象、门禁要求两者齐全（与来源 skill 的
   双语示例一致）。如产品后续定其它惯例，改一处即可。
2. caveat 语义不做 NLP 判定：门禁只验双语非空与长度下限；假设与
   类比边界是否写得到位，靠作者自查与人工审。
3. 随机模型只立了协议与口径（seeded_sample / expected_distribution /
   stochastic 探针），两个参照模型均为确定性；随机教学图接入时须
   实现 sample() 并过复现探针。
4. MCP 只读工具未加：mcp_router 的工具注册与授权面较大，本次只做
   REST 接线；MCP 待接点见下。
5. 渲染器与前端展示未做：renderer_hint 仅提示；figure_refs 只验对象
   键形态（figures/<doc>/p<页>_<号>.png，沿用 figure_crop.py 的键），
   不验存储存在性。

## 待接点

- 渲染套件：两个 MIT 套件（Anatomy、iso-figure）不在本次范围，接入
  时须保留其 LICENSE 署名；HRA 网格 CC BY 4.0 须署名。
- 前端展示：教学图舞台组件（读 spec + 模型派生 + provenance 块 +
  figures[] 鉴权取图），按既有 geometry 交互课模式接。
- MCP 只读工具：在 mcp_router 既有模式上加 get 规格（只读）。

## 生产部署步骤（部署时按此执行，本分支不含部署动作）

1. 前置：确认生产 main 在 2109851；备份生产库（沿用 word-atlas
   部署同款整库备份）。
2. 合分支：`git merge feat/teachable-figure-spec` 到 main 后 push。
3. 迁移：随 api 启动的 `alembic upgrade head` 自动执行（本分支含
   一个新迁移 tfg1a2b3c4d5e）；迁移失败则服务不对外提供（既有
   部署纪律），先查 alembic_version 再处理。
4. 重启 mneme-api（compose 惯例）；冒烟：admin 创建一规格（应
   verified=False）、verify（应 True）、学生列表可见、未验证规格
   学生侧 404。
5. 回退点：后端 main 2109851；回退 = revert 合并提交 + `alembic
   downgrade` 到 f9a1b2c3d4e5 + 重启 api（新表无生产数据写入时可
   直接 downgrade；若已有人工录入的规格行，先导出 spec JSON 备份）。
