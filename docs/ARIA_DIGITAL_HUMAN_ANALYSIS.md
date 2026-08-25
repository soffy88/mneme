# Aria 数字人重构：深度分析与技术方案

> 2026-07-31 · 基于当前实现代码审计 + 三个开源库深入分析

---

## 一、当前 Aria 为什么"很差"——根因诊断

### 实际渲染技术（代码实证）

当前 Aria 的**默认渲染路径**（`AriaDigitalHuman.tsx`）是：

```
房间背景 = 2 张静态 JPG（room_play.jpg / room_talk.jpg）
人物     = 2 张抠图 PNG（person_play.png / person_talk.png）
动画     = GSAP 改 CSS left/bottom/width/scale（位移+缩放）
弹琴     = SVG 手部形状 + GSAP bounce 动画
说话     = CSS 嘴部柔光脉冲（viseme_css）或预渲染 EchoMimic 视频片段
走路     = 不存在——两张图交叉淡入淡出
```

**这不是数字人，这是一个带 CSS 动画的幻灯片。**

### 具体问题清单

| 问题 | 根因 | 代码位置 |
|------|------|----------|
| 人物不动 | 只有 2 张静态 PNG，无骨骼动画 | `AriaDigitalHuman.tsx` ASSETS 对象 |
| 弹琴假 | SVG 手掌形状上下弹跳，无手指动画 | `AriaHands.tsx` |
| 说话假 | CSS box-shadow 脉冲模拟嘴动 | `requestAriaLipsync` fallback: `viseme_css` |
| 走路不存在 | 无 walk 动画，只有 play↔talk 两张图切换 | `isTalk()` 二态判断 |
| Director 指挥的是幻灯片 | LLM 输出 layout 百分比（left_pct/scale），不是骨骼指令 | `aria_director.py` AriaLayout 模型 |
| EchoMimic 是批处理 | 生成一段视频要数十秒，不是实时驱动 | `docker/echomimic/server.py` |
| VRM 路径是摆设 | 存在但明确不是默认（"3D 不进默认"） | TASKS.md Aria 段 |
| 无自主行为 | Director tick 是前端 setInterval 轮询，不是真正的自主调度 | `AriaStage.tsx` |

### 核心矛盾

当前架构把"数字人"理解为"LLM 输出 CSS 参数 → 前端移动图片"。
真正的数字人需要：**骨骼动画 + 实时唇形 + 全身运动 + 自主行为调度**。

---

## 二、三个开源库深度分析

### 2.1 rachel-digital-human-production

**本质**：HeyGen + MiniMax 的云 API 视频生产流水线（Codex Skill）。

```
输入：portrait.jpg + voice-source.mp3 + script.md
流程：MiniMax 克隆语音 → HeyGen Image-to-Video → 15s 预览 → 1080p 成片
输出：预渲染 MP4 视频
```

| 维度 | 评价 |
|------|------|
| 实时性 | ❌ 完全离线批处理，一个 15s 视频要等几分钟 |
| 交互性 | ❌ 零交互，纯单向视频生产 |
| 运动能力 | ❌ 只有说话头部微动（HeyGen 的 image-to-video） |
| 弹琴 | ❌ 不可能 |
| 自主行为 | ❌ 无 |
| 可借鉴 | 仅"预校验资产再调付费 API"的工程纪律 |

**结论：与 Aria 需求完全不匹配。** 这是给营销团队批量生产数字人短视频的工具，不是实时交互数字人。

### 2.2 female-portrait-director

**本质**：AI 人像图片 prompt 工程工具（Codex Skill）。

```
输入：风格/场景/服装/情绪等文字参数
输出：一段精修的图像生成 prompt（或调 image API 生成静态图）
```

| 维度 | 评价 |
|------|------|
| 实时性 | ❌ 生成静态图片 |
| 交互性 | ❌ 零 |
| 运动能力 | ❌ 静态图 |
| 弹琴 | ❌ |
| 自主行为 | ❌ |
| 可借鉴 | 20 种风格路由 + 参数锁定 + 负面约束的结构化 prompt 设计 |

**结论：与数字人完全无关。** 这是一个图片 prompt 生成器，不是数字人框架。唯一价值是它的"风格路由"设计模式可以参考用于 Aria 的视觉风格管理。

### 2.3 Fay（⭐ 唯一有价值的参考）

**本质**：数字人 Agent 框架——"大脑"架构，不做渲染，通过 WebSocket 驱动外部渲染器。

```
架构：
  Fay Core（大脑）
    ├── LLM（OpenAI 兼容，流式）
    ├── TTS（ali/gptsovits/volcano/ms，流式音频+唇形数据）
    ├── ASR（FunASR，语音识别）
    ├── Agent（工具调用，MCP，自主决策）
    ├── Memory（仿生记忆）
    ├── Scheduler（日程式主动对话）
    ├── Action Signals（action_rules.csv → behavior/affect/intensity）
    ├── Emotion（情绪值 + 适应模型）
    └── WebSocket Server
         ├── port 10002 → 数字人渲染客户端（Unity/Web/App/大屏）
         └── port 10003 → Web 管理面板
```

| 维度 | 评价 |
|------|------|
| 实时性 | ✅ 全链路流式（LLM 流式 → TTS 流式 → 音频分片推送） |
| 交互性 | ✅ 文字/语音/透传三种交互模式，支持打断 |
| 运动能力 | ⚠️ Fay 本身不渲染——它推送指令，渲染由外部客户端做 |
| 弹琴 | ⚠️ 取决于渲染客户端的能力，Fay 可以推送 action signal |
| 自主行为 | ✅ 日程式调度 + agent 自主决策 + 主动对话 |
| 多用户 | ✅ 多路并发 |
| 记忆 | ✅ 仿生记忆系统 |
| MCP | ✅ 支持 |
| 可借鉴 | **大量**——见下方详细分析 |

#### Fay 的核心设计洞察（Aria 缺失的）

**1. 大脑/身体分离**

Fay 最重要的架构决策：**大脑（agent/LLM/TTS/调度）和身体（渲染）完全解耦**，通过 WebSocket JSON 协议通信。

```python
# Fay 推送给渲染器的消息格式
{
  "Topic": "human",
  "Data": {"Key": "question", "Value": "用户说的话"},
  "Username": "user1"
}
# 音频分片 + 唇形数据 + 情绪 + action signal 分别推送
```

Aria 当前是**大脑和身体耦合**的：Director LLM 直接输出 CSS 百分比，前端直接执行。没有协议层，没有解耦。

**2. 流式音频 + 唇形同步推送**

Fay 的 TTS 不是"生成完整音频再播"，而是：
- LLM 流式输出文本 → 按句切分 → 每句立即送 TTS → 音频分片 + 唇形数据实时推送
- 渲染器收到音频分片立即播放，同时用唇形数据驱动嘴部动画
- 支持打断（`should_stop_generation`）

Aria 当前：edge-tts 生成完整音频 → 播放 → CSS 脉冲假装嘴动。

**3. 自主行为调度（日程式）**

Fay 有 `scheduler/` 模块，数字人可以按日程自主行动（不需要用户触发）：
- 定时播报
- 主动打招呼
- 基于上下文的自主对话

Aria 当前：前端 `setInterval` 轮询 `/v1/aria/act`，LLM 每次返回一个 action。这不是真正的自主行为——是定时乞讨。

**4. Action Signal 系统**

Fay 的 `action_signal.py`：基于关键词规则表（`action_rules.csv`）将文本映射为结构化动作信号：

```python
@dataclass
class ActionRule:
    code: str          # 动作编码
    behavior: str      # 行为描述
    affect: str        # 情感
    intensity: float   # 强度
    priority: int      # 优先级
    sentiment_hint: float
    keywords: Tuple[str, ...]
```

渲染器收到 action signal 后播放对应动画。这比 Aria 的"LLM 输出 left_pct=38"高了一个抽象层级。

**5. Fay 不解决的问题**

Fay 明确说"数字人渲染是非必须的"——它不管你怎么画。文档里推荐用 Unity 或第三方渲染器。这意味着：

- Fay 解决了"大脑"问题（agent/调度/流式/记忆）
- Fay **没有**解决"身体"问题（3D 渲染/骨骼动画/唇形驱动/手指动画）

---

## 三、能力矩阵对比

| 能力 | Aria 当前 | rachel | portrait-director | Fay | Aria 需要 |
|------|-----------|--------|-------------------|-----|-----------|
| 实时交互 | ❌ 轮询 | ❌ | ❌ | ✅ 流式 | ✅ |
| 全身骨骼动画 | ❌ 2张PNG | ❌ | ❌ | ❌ 不管渲染 | ✅ |
| 手指弹琴动画 | ❌ SVG弹跳 | ❌ | ❌ | ❌ | ✅ |
| 实时唇形同步 | ❌ CSS脉冲 | ❌ | ❌ | ✅ 数据推送 | ✅ |
| 走路/坐下 | ❌ 不存在 | ❌ | ❌ | ❌ | ✅ |
| 自主行为 | ❌ 轮询 | ❌ | ❌ | ✅ 日程式 | ✅ |
| 流式 TTS | ⚠️ edge-tts整段 | ❌ | ❌ | ✅ 分片 | ✅ |
| LLM 对话 | ✅ | ❌ | ❌ | ✅ | ✅ |
| 记忆 | ✅ 三层 | ❌ | ❌ | ✅ 仿生 | ✅ |
| 情绪系统 | ⚠️ 标签 | ❌ | ❌ | ✅ 数值+适应 | ✅ |
| 多用户 | ❌ | ❌ | ❌ | ✅ | ⚠️ 低优 |
| MCP/Agent | ✅ | ❌ | ❌ | ✅ | ✅ |

**结论**：
- rachel 和 portrait-director 对 Aria 的价值 ≈ 0
- Fay 的"大脑"架构高度可借鉴
- **但三个库都没有解决"身体"问题——真正的 3D 实时渲染 + 骨骼动画**

---

## 四、真正的数字人需要什么——技术分解

"独立运动、说话、弹钢琴"分解为 5 个独立技术问题：

### 4.1 身体：3D 模型 + 骨骼动画

**需求**：一个有完整骨骼（含 10 根手指 × 3 关节）的 3D 角色，能执行：
- idle（呼吸、眨眼、微调重心）
- walk（走到钢琴前 / 走向镜头）
- sit（坐下）
- play_piano（手指按键，手腕/手臂协调）
- talk（手势、头部微动、身体前倾）
- gesture（指向、挥手、点头）

**技术选项**：

| 方案 | 质量 | 实时性 | Web 交付 | 开发量 | 硬件需求 |
|------|------|--------|----------|--------|----------|
| **A. Three.js + VRM + Mixamo 动画** | 中 | ✅ 60fps | ✅ 原生 | 中 | 无额外 |
| B. Unity WebGL + FBX | 高 | ✅ 30-60fps | ✅ WebGL | 大 | 构建重 |
| C. Unity/Unreal 像素流 | 最高 | ✅ | ⚠️ 视频流 | 很大 | GPU 服务器 |
| D. Three.js + 程序化骨骼 | 中低 | ✅ | ✅ | 极大 | 无 |

**推荐：A（Three.js + 高质量 VRM + 动画片段库）**

理由：
- 已有 Three.js/VRM 基础设施（`AriaVRM.tsx`、`@pixiv/three-vrm`）
- Web 原生，无需额外服务器
- RTX 3080 不需要参与渲染（客户端 GPU）
- VRM 1.0 支持完整手指骨骼 + 表情 blendshape
- Mixamo 提供免费动画片段（walk/sit/idle/gesture），可重定向到 VRM

**关键改进**：
- 换一个高质量 VRM 模型（当前 aria.vrm 是 CC0 Olivia，质量低）
- 从 Mixamo 获取动画片段：idle、walk、sit_down、piano_play、talk_gesture
- 用 `VRMHumanoid` 的 `humanBones` 做程序化手指动画（MIDI 驱动）

### 4.2 唇形：实时 Viseme 驱动

**需求**：说话时嘴型与音频同步（不是 CSS 脉冲）。

**技术选项**：

| 方案 | 质量 | 实时性 | 硬件 |
|------|------|--------|------|
| **A. TTS viseme 时间戳 → VRM blendshape** | 中高 | ✅ | 无 |
| B. 音频分析 → 嘴型（rhubarb-lip-sync） | 中 | ✅ | 无 |
| C. NVIDIA Audio2Face | 最高 | ✅ | NVIDIA GPU |
| D. EchoMimic 视频 | 高 | ❌ 批处理 | GPU |

**推荐：A（TTS viseme → VRM blendshape）**

实现路径：
1. edge-tts / 阿里云 TTS 返回音频 + 时间戳（word boundary）
2. 按音素映射到 Oculus 15 viseme（PP/FF/TH/DD/kk/CH/SS/nn/RR/aa/E/I/O/U）
3. VRM 的 `blendShapeProxy` 驱动嘴型（a/i/u/e/o + 自定义 viseme）
4. 每帧插值，60fps 平滑

Fay 的做法正是这个——TTS 分片推送时附带唇形数据，渲染器实时驱动。

### 4.3 弹琴：MIDI 驱动手指动画

**需求**：弹钢琴时手指按键动作与音乐同步。

**已有资产**：`vendor/oprim/midi_parse.py`（MIDI 事件解析 + 88 键归一化 + 手区判定）+ `vendor/oskill/hand_choreo.py`（特征→GSAP 参数）。

**但这些是给 SVG 用的，不是给 3D 骨骼用的。**

**正确实现**：
1. 预录/生成 MIDI 文件（Aria 的"曲目库"）
2. 播放 MIDI 时，逐事件驱动 VRM 手指骨骼：
   - `note_on(key=60, velocity=90)` → 右手拇指（C4）按下，速度/力度映射到动画速度/幅度
   - `note_off(key=60)` → 抬起
3. 手腕/手臂用 IK（反向运动学）跟随手指目标位置
4. 身体微微随节奏摇摆（程序化正弦叠加）

**技术关键**：`@pixiv/three-vrm` 的 `humanoid.getNormalizedBoneNode('rightThumbProximal')` 等 API 可以直接设置手指关节旋转。88 键映射到 10 指需要简单的指法分配算法。

### 4.4 大脑：自主行为调度

**需求**：Aria 不需要用户触发就能自主行动（弹琴→停下→走向镜头→说话→走回→继续弹）。

**当前问题**：前端 `setInterval` 每 N 秒调 `/v1/aria/act`，LLM 返回一个 action。这是"定时乞讨"，不是自主行为。

**Fay 的做法（可借鉴）**：
- 日程式调度：预定义时间表（"下午 3 点弹一首曲子"）
- 事件驱动：用户进入房间 → 打招呼；用户说话 → 回应；沉默 30s → 主动搭话
- Agent 自主决策：LLM 作为 agent，有工具（弹琴/说话/走路/等待），自主规划下一步

**推荐架构**：

```
Aria Brain（后端，Celery beat 或长驻进程）
  ├── 状态机：idle → walking → sitting → playing → standing → talking
  ├── 事件队列：user_entered / user_spoke / silence_timeout / schedule_tick
  ├── LLM Agent：给定当前状态+事件+记忆，规划下一个 action sequence
  ├── TTS 流式：action 含说话 → 流式生成音频 + viseme
  └── WebSocket 推送：action_signal + audio_chunks + viseme_timeline
       → 前端渲染器执行
```

**关键改变**：大脑从"前端轮询的 HTTP 端点"变成"后端长驻的自主进程"。前端只是渲染器，被动接收指令。

### 4.5 协议：大脑↔身体通信

**当前**：HTTP 请求/响应（`POST /v1/aria/act` → JSON）。

**需要**：WebSocket 双向流式（Fay 的做法）。

```typescript
// 前端渲染器 → 大脑
{ type: "event", event: "user_entered", data: {...} }
{ type: "event", event: "user_spoke", text: "你好" }
{ type: "status", state: "animation_complete", action: "walk_to_piano" }

// 大脑 → 前端渲染器
{ type: "action", action: "walk", target: "piano_bench", speed: 1.0 }
{ type: "action", action: "sit" }
{ type: "action", action: "play_midi", midi_url: "/aria/songs/dreams.mid" }
{ type: "speech", text: "你好呀", audio_chunks: [...], visemes: [...] }
{ type: "emotion", value: 0.7, expression: "happy" }
{ type: "idle", duration_ms: 5000 }  // 5秒后自主决定下一步
```

---

## 五、推荐实施方案（分阶段）

### Phase 0：基础设施（1-2 天）

- [ ] 选定/获取高质量 VRM 模型（带完整手指骨骼 + 表情 blendshape）
  - 选项：VRoid Studio 自制 / Booth 购买 / 委托建模
  - 要求：`humanBones` 完整（含所有 finger 关节），`blendShapeProxy` 含 a/i/u/e/o + blink
- [ ] 从 Mixamo 获取动画片段（FBX → 重定向到 VRM 骨骼）：
  - idle_breathe、walk_forward、sit_down、stand_up、talk_gesture、wave
- [ ] 准备 3-5 首 MIDI 钢琴曲（Aria 曲目库）

### Phase 1：3D 渲染升级（3-5 天）

**目标**：替换 2 张 PNG 为真正的 3D 角色 + 骨骼动画。

- [ ] 重写 `AriaDigitalHuman.tsx` → 基于 `AriaVRM.tsx` 升级为默认路径
- [ ] 动画状态机（Three.js AnimationMixer）：
  ```
  idle ←→ walk ←→ sit ←→ play
                ↘ talk_gesture
  ```
- [ ] 房间场景保留（当前 room JPG 可改为 Three.js 平面背景，或简单 3D 房间）
- [ ] 相机：固定机位 + 说话时轻微推近
- [ ] 删除 SVG 手部覆盖层（`AriaHands.tsx`）、CSS 脉冲唇形

### Phase 2：唇形 + 弹琴（3-5 天）

**目标**：说话有真嘴型，弹琴有真手指。

- [ ] TTS viseme 管线：
  - 后端：edge-tts 返回 word boundary → 音素→viseme 映射 → 随音频分片推送
  - 前端：`VRMBlendShapeProxy` 按 viseme 时间线驱动嘴型
- [ ] MIDI 手指驱动：
  - 前端：`@tonejs/midi` 解析 MIDI → 逐 note 事件驱动手指骨骼旋转
  - 指法分配：简单规则（C4-C5 右手，C3-B3 左手，黑键就近）
  - 手腕 IK 跟随
- [ ] 弹琴时身体微摇（正弦叠加到 spine 骨骼）

### Phase 3：自主行为大脑（3-5 天）

**目标**：Aria 真正"活"起来——不需要用户触发就自主行动。

- [ ] 后端：`services/aria_brain.py`（长驻 asyncio 进程或 Celery 长任务）
  - 状态机 + 事件队列 + LLM agent 规划
  - 参考 Fay 的 scheduler + action_signal 设计
- [ ] WebSocket 端点：`/v1/aria/ws`（替代当前 HTTP 轮询）
  - 前端连接后被动接收指令
  - 前端上报事件（user_entered / user_spoke / animation_done）
- [ ] 行为脚本（LLM 可调用）：
  - `play_song(midi_id)` → 走到钢琴 → 坐下 → 弹 → 结束 → 站起
  - `greet_user(text)` → 走向镜头 → 说话（TTS+viseme）→ 手势
  - `idle_think()` → 随机小动作（看手、抬头、微笑）
  - `respond(text)` → 对话回复 + 表情 + 手势
- [ ] 日程式调度：
  - 用户打开页面 → Aria 正在弹琴 → 注意到用户 → 停下 → 打招呼
  - 沉默 60s → Aria 主动说话（"要不要听一首曲子？"）
  - 定时弹琴（每 5 分钟一首）

### Phase 4：打磨（持续）

- [ ] 动画混合（crossfade）平滑过渡
- [ ] 眨眼程序化（随机间隔 2-6s）
- [ ] 呼吸程序化（spine 微幅正弦）
- [ ] 情绪→表情/体态映射（开心→身体前倾/手势多；思考→歪头/手托腮）
- [ ] 多曲目 + 弹琴时随机身体摇摆变化
- [ ] 性能优化（VRM LOD、动画压缩）

---

## 六、架构对比：当前 vs 目标

```
当前（幻灯片架构）：
  前端 setInterval → HTTP POST /v1/aria/act → LLM 返回 CSS 参数
  前端 GSAP 移动 PNG → CSS 脉冲假装嘴动 → SVG 假装弹琴

目标（数字人架构）：
  后端 Aria Brain（长驻进程）
    ├── 状态机 + 事件驱动 + LLM Agent
    ├── TTS 流式（音频 + viseme 时间线）
    ├── MIDI 曲目库
    └── WebSocket 推送 action/speech/emotion
         ↓
  前端 渲染器（Three.js + VRM）
    ├── AnimationMixer（walk/sit/play/talk/idle）
    ├── VRM blendshape（viseme 唇形 + 表情）
    ├── 手指骨骼（MIDI note → 关节旋转）
    ├── 程序化微动（呼吸/眨眼/重心）
    └── 事件上报（user_entered/spoke/anim_done）
```

---

## 七、硬件/环境可行性

| 组件 | 需求 | 当前环境 | 可行？ |
|------|------|----------|--------|
| 3D 渲染 | 客户端 GPU（浏览器 WebGL） | 用户浏览器 | ✅ |
| LLM 对话 | 阿里云 Qwen / 本地 Ollama | qwen3-8b 本地 | ✅ |
| TTS | edge-tts（免费）/ 阿里云 | 已有 | ✅ |
| Viseme 计算 | CPU（纯映射） | 任意 | ✅ |
| MIDI 解析 | CPU | 已有 midi_parse.py | ✅ |
| WebSocket | FastAPI WebSocket | 已有基础设施 | ✅ |
| 自主大脑 | 长驻进程 | Celery / asyncio | ✅ |
| RTX 3080 | 不需要参与渲染 | 5GB 空闲 | ✅ 富余 |

**关键洞察**：渲染完全在客户端浏览器做（Three.js WebGL），服务器只负责"思考"和"推送指令"。RTX 3080 完全不需要参与实时渲染——它跑 LLM 和 TTS 就够了。

---

## 八、从三个库各取什么

| 来源 | 取什么 | 不取什么 |
|------|--------|----------|
| **Fay** | 大脑/身体分离架构；WebSocket 协议；流式 TTS+唇形推送；日程式调度；action signal 抽象；打断机制 | 它的 Python 2 风格代码；它的 Unity 渲染器依赖；它的多用户并发（Aria 单用户） |
| **rachel** | "预校验资产再调付费 API"的工程纪律 | 全部（云视频批处理，与实时数字人无关） |
| **portrait-director** | 风格路由 + 参数锁定的 prompt 设计模式（可用于 Aria 视觉风格管理） | 全部（静态图片 prompt 工具） |

---

## 九、风险与决策点

| 风险 | 影响 | 缓解 |
|------|------|------|
| 高质量 VRM 模型获取 | 没有好模型，动画再好也丑 | VRoid Studio 自制 / 委托 / Booth 购买（¥200-2000） |
| Mixamo 动画重定向到 VRM | 骨骼命名/比例不同可能变形 | three-vrm 有 `humanoid` 标准化层，Mixamo 兼容性好 |
| 手指动画自然度 | MIDI→手指映射简单规则可能僵硬 | 先做"能按对键"，再迭代加随机微动/力度变化 |
| WebSocket 长连接稳定性 | 断线后 Aria "死"了 | 自动重连 + 重连后恢复当前状态 |
| 前端性能（低端设备） | VRM + 动画 + 音频可能卡 | LOD + 动画帧率降级 + 检测 WebGL 能力回落 2D |

### 需要你决策的事

1. **VRM 模型来源**：自制（VRoid）/ 购买（Booth）/ 委托建模？预算？
2. **是否保留 2D 回落路径**：低端设备/移动端是否保留当前 PNG 方案作为降级？
3. **自主大脑的部署形态**：Celery 长任务 / 独立 asyncio 进程 / 前端本地状态机（无后端）？
4. **Phase 1 是否立即开始**：还是先确认模型来源再动手？

---

## 十、总结

**当前 Aria 的本质问题**：用 CSS 动画移动静态图片，冒充数字人。

**三个库的价值**：
- rachel / portrait-director：与实时数字人无关，价值 ≈ 0
- Fay：大脑架构高度可借鉴（解耦/流式/调度/协议），但不解决渲染

**真正的解法**：
- 渲染：Three.js + 高质量 VRM + Mixamo 动画 + MIDI 手指驱动 + viseme 唇形
- 大脑：Fay 式解耦架构（后端长驻 agent + WebSocket 推送 + 前端纯渲染器）
- 弹琴：MIDI → 手指骨骼旋转（已有 midi_parse.py 基础）
- 自主：状态机 + 事件驱动 + LLM 规划（替代 setInterval 轮询）

**可行性**：完全可行。渲染在客户端浏览器，服务器只做思考。RTX 3080 富余。所有技术组件都有成熟开源方案。预计 Phase 1-3 共 10-15 天可交付一个"真正能走、能坐、能弹琴、能说话、有嘴型"的 Aria。
