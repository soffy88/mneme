# Atlas of Physics 嫁接：物理真值模型 + 不变量检查 + 计算题纪律

方法来源：nathanliow/atlas-of-physics（MIT，交互式 3D 物理教科书）。
只学方法、干净重写：本分支不含对方代码、文本或题目。所学的方法是
model→checks→practice 纪律——一个纯函数真值模型是唯一数值来源，
checks 用另一算法独立重算每个量，练习答案由模型算出、再由 checks
重算对上。模型、参数值、检查项、题项、代码全部自写，公式取自通用
物理（平抛运动、单摆小角度近似）。

## 1. 模型协议

`services/physics_models.py`：物理模型实现 teaching_figure 的
TruthModel 协议（initial_state / apply_action / derive / step），
语义态只含物理量；非法输入拒绝、越界 clamp，绝不编造结果。
另有两条物理专属约定：

- `recompute(readout, bound, actions)`：每条数值读数必须有一条
  独立重算路径（数值积分、步进模拟、二分求根、中心差分、RK4
  之一），与 derive 的解析路径对上才算通过；没有路径的读数，
  门禁判失败（fail-closed）。
- `ignored_terms()`：模型声明的理想化假设（如空气阻力）。规格
  caveat 必须逐条点名（中英双语），缺一不可。门禁只验“写了”，
  语义由作者自查（与 teaching_figure 的 caveat 门禁同口径）。

参照模型（自写，参数值与检查项均为本分支原创）：

- `projectile_motion`（平抛）：v0＝12 m/s、h＝20 m、g＝9.8 m/s²。
  26 条不变量检查：步进/积分重算 x/y、能量守恒、Torricelli 关系、
  二分求根飞行时间、步进模拟落点、落地后停住。
- `pendulum_small_angle`（单摆小角度）：L＝0.8 m、摆角 6°、
  g＝9.8 m/s²。25 条不变量检查：RK4 精确非线性方程对照、
  线性化能量守恒、精确/线性化能量差距以 θ0⁴ 为界、过零点二分
  周期、摆角 ≤10°  regime 门。单摆比对容差取近似误差阶 θ0³
  （见 `compare_tolerance` 覆写与注释）：RK4 解的是精确方程，
  与线性化解的差正在此阶；容差取该阶，符号/量级错误仍会落网。
  摆角超过 10° 时模型直接拒绝（initial_state  raise）。

注册：`physics_models` 模块导入时把物理模型幂等地注册进
teaching_figure 的 MODEL_REGISTRY（`register_physics_models()`），
于是 verify_figure 的模型门禁可直接认物理模型作教学图的
model_ref 后端；teaching_figure 本身一字不改。路由模块导入时
同样调用注册，测试直接导入模块即完成注册。

## 2. 模型规格验证门（verify_physics_model，p1–p6）

p1 schema（id slug、必填齐全、verified 字段禁入、双语齐全）；
p2 锚点 KU 真实存在（ku_id 可为空，不锚定时跳过；一旦给出则
fail-closed）；p3 模型已知、参数绑定成功、期望含复位态与跃迁态
且与模型一致、动作不改原状态、复位可恢复；p4 caveat 点名全部
忽略项；p5 不变量检查全过；p6 数字三标签全覆盖（复用
find_untagged_numbers）。verified 只由服务端 verify 端点重跑
门禁后设置。

## 3. 计算题纪律（services/physics_practice.py）

- 生成：`build_practice_item` 绑定参数、跑模型 derive，把算出的
  答案写进题项——答案永不手写。选择题的 4 个选项由作者提供，
  keyed 选项须与模型值对上。
- 验证：`verify_practice_item`（q1–q6）：q1 schema；q2 模型已知、
  参数绑定成功、答案读数存在且单位一致、容差为正、锚点 KU（若
  给出）真实存在；q3 答案由模型算出且独立重算对上（比对 bar 取
  题项 tolerance 与数值噪声下限的最大值）；q4 题干占位符 `{name}`
  只许引用模型参数名或读数名；q5 假设文本点名全部忽略项；q6
  选择题间距（keyed 对上真值、干扰项拉开 2% 以上、选项互不相同）。
- 题项的 `actions` 字段（到达求解状态的动作序列）走
  find_untagged_numbers 的 `actions` 子树跳过规则，与
  teaching_figure 的期望动作同口径。

## 4. 持久化与接线

- ONE 个 Alembic 迁移 `phy1a2b3c4d5e`（down_revision
  `wnb1a2b3c4d5e`）：`physics_models` 表（id、ku_id 可空、spec
  JSONB、verified 默认 False、author_id、时间戳）与
  `physics_practice_items` 表（id、model_id 存注册表模型名、
  spec JSONB、verified 默认 False、author_id、时间戳）。
  `health.py` 的 EXPECTED_MIGRATION_HEAD 已同步为本 head。
- 路由：`/v1/physics-models`（create/list/get/verify/checks）与
  `/v1/physics-practice`（create/list/get/verify），鉴权与
  verified 纪律照搬 teaching_figures 路由；checks 端点只读重跑
  不变量检查，不改 verified 与任何状态。
- MCP：只读工具 `GetPhysicsModel`（仅 verified 可见，无此模型
  返回 `{error}`，不抛 500），沿用 mcp_router 的
  tool_* + Req + `_ensure_student_access` 模式。
- physics_service.py（对话式受力分析/概念诊断）一字不改：它是
  对话层，本分支是模型层，两者互补，不互相依赖。
- AnimatedExplanation 的 scene 可引用物理模型派生量：组合方式为
  scene 规格携带 `model_ref`（同 teaching_figure 口径），渲染时
  读数由模型 derive 提供；渲染本身不在本分支范围。

## 5. 合并顺序（与并行的 all-grafts 分支）

本分支以 main 694c92a 为基，迁移 `phy1a2b3c4d5e` 与 all-grafts
分支的 `all1a2b3c4d5e` 同抢 `tfg1a2b3c4d5e` 之后的位置。合并顺序：

- 若 all-grafts 先合：本分支 rebase 到其 head，把本迁移的
  down_revision 改到对方 head、health pin 改到本 head、两处

> 2026-11-02 已按此顺序合入 main：all → wnb → phy，链头现为 phy1a2b3c4d5e。
  单头断言（本文件测试与 test_teaching_figure_spec.py）同步改到
  本 head，再重跑迁移测试。
- 若本分支先合：对方 rebase 时做对称修改（对方任务书已有此口径）。
- 两个分支均不改对方 worktree；合并前以 `alembic heads` 单头为准。

## 6. 偏差与待接点

- 偏差（有意为之，均已在代码注释中写明）：
  1. 单摆能量门用线性化二次型能量守恒（精确势能差距另立
     θ0⁴ 界），因线性化动力学本身不守恒精确势能——如实记录
     近似的代价，而非把近似当精确。
  2. 单摆比对容差取 θ0³ 阶（见第 1 节），其余模型保持 1e-6/1e-9。
  3. verify 的 p5 在模型不可用时记 False 而不重复记 issue，避免
     同一根因淹没门禁读数；passed 仍以 issues 为准。
- 待接点：
  1. 3D 渲染（纸质立体 + 墨线边 + 爆炸分解 + 点击拆解）归 hevi
     侧（另有分支 feat/atlas-figure-idiom），本分支不做渲染。
  2. 前端展示：教学图/题项的前端组件未做，待渲染与展示一起接。
  3. 内容：atlas 的 326 道 AP 式英文题与章文本虽 MIT 可署名复用，
     但须经课标映射 + 人工审校才可进 Mneme——方法先行，内容后议。
  4. 更多物理模型（牛顿/能量/电磁等）按同一协议追加：新模型类 +
     注册表一行 + 参照规格 + 检查项，无须改门禁代码。

## 7. 测试

`tests/test_atlas_physics_graft.py`：31 测（纯核模型/门禁/题项
纪律 23 + 路由/MCP 7 + 迁移单头与 upgrade/downgrade 真跑 1），
容器法前台直读全过；相关旧测（teaching_figure、provenance、
figure_crop、math_grade、cognitive_state_provenance）84 passed /
3 skipped；ruff 全过。共享库版本行漂移（prq1a2b3c4d5）与空库
upgrade 断裂（word-atlas 迁移处）为既有状态，只记录不修；
迁移测试走克隆库，绝不碰生产库。
