# ADR-IMMERSIVE-AGPL-BOUNDARY：DashPlayer AGPL 边界（Immersive Learning）

- 状态：Accepted
- 日期：2026-08-29
- 范围：Mneme Immersive Learning / Media Learning Engine 相对
  [solidSpoon/DashPlayer](https://github.com/solidSpoon/DashPlayer)（AGPL-3.0）的
  许可与实现边界
- 编号别名：`0006-immersive-agpl-boundary.md` 指向本文件

## 背景

DashPlayer 是 AGPL-3.0 的 Electron 沉浸式影音学习播放器。Mneme 需要同类产品能力
（句级导航、双语字幕、循环复听、查词练习），但作为网络服务若复制 AGPL 源码或依赖
其组件，会触发 copyleft 传染风险。`package.json` 上的 MIT 标记视为样板错误，**以
LICENSE / SPDX 的 AGPL-3.0 为准**。

## 决策

Mneme Immersive Learning 对 DashPlayer **仅允许 `INSPIRED_BY`**：

| 类别 | 规则 |
|------|------|
| **INSPIRED_BY** | 允许：UX 模式、产品概念、键盘图示的意译、能力清单与架构研究 |
| **COPY_SOURCE** | 禁止：TS/React/Electron 源码、解析器、IPC、prompts、CSS、tests、assets |
| **PORT_COMPONENT** | 禁止：除非单独法律审阅并书面批准 |
| **DEPEND_ON_AGPL_COMPONENT** | 默认拒绝；若需依赖须显式 license review |

实现路径必须是 **clean-room**：从需求/规格独立实现，落在 Mneme 自身许可证下。
不得把 DashPlayer 仓库当作脚手架、vendor、或“参考粘贴”来源。

编号文档 `docs/adr/0006-immersive-agpl-boundary.md` 仅作指针；本文件为 AGPL 边界
权威正文。

## 不变的红线

- 禁止把 DashPlayer 源码、样式、测试、prompt 或资源拷入 `mneme` / `mneme-web`。
- 禁止 runtime 依赖 AGPL 播放器包或其 fork（含“只抄一小段”）。
- 能力对照表（`outputs/DASHPLAYER-CAPABILITY-MAP.md`）只描述产品能力，不是许可
  豁免；表中每一项仍须独立实现。
- Immersive Learning 仍走 Mneme 既有 LearningEvent → Evidence → CognitiveState →
  Policy → FSRS 环路，不得为“对齐 DashPlayer”另起掌握度/调度内核。

## 验证

- PR / CI 抽检：无 DashPlayer 路径、包名或明显逐行移植痕迹。
- 设计文档可引用能力对照；代码 review 以本 ADR 为否决依据。
- 若未来考虑 AGPL 依赖，必须先改本 ADR 并完成法律审阅，不得静默引入。
