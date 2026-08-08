# Aria 完整数字人实施计划 (Full Implementation Plan)

> **目标**：让 Aria 成为真正独立的数字人——有大脑（NIM/Director）、能感知周围（VLM）、能用手弹钢琴（EchoMimic V2）、站在不动的房间里（分层渲染）。
>
> **制定日期**：2026-07-29
> **当前状态**：Phase 0 已完成（分层架构 + Director brain + layout/hands + TTS + viseme）

---

## 总览

| 阶段 | 目标 | 工期 | 新增硬件 | 核心依赖 |
|------|------|------|---------|---------|
| **P0 当前** | 分层数字人 + 导演大脑 + 位置/手势控制 | ✅ 已完成 | 无 | Director, GSAP, edge-tts |
| **P1 感知层** | Aria 能"看见"房间和琴谱 | 1 周 | 无（3080 够用） | Qwen-VL / InternVL |
| **P2 手势增强** | 更真实的手部模拟 + MIDI 同步 | 1 周 | 无 | GSAP timeline, MIDI parser |
| **P3 真实驱动** | EchoMimic V2 侧车，音频驱动半身视频 | 3-4 周 | 需云 GPU 或第二台机 | EchoMimic V2, Docker, GPU |
| **P4 全身自由** (可选) | MetaHuman/ACE 级全身渲染 | 2-3 月 | 云 Pixel Streaming | UE5, NVIDIA ACE |

```
                    ┌─────────────┐
                    │  Director    │  ← NIM 大脑（已完成）
                    │  (Brain)     │
                    └──────┬──────┘
                           │ action + layout + hands + emotion
                    ┌──────▼──────┐
           ┌────────┤  Perception ├────────┐
           │        │  (VLM) P1   │        │
           │        └─────────────┘        │
           │                               │
    ┌──────▼──────┐              ┌─────────▼─────────┐
    │  Simulated   │              │  EchoMimic V2      │
    │  Hands (P2)  │              │  Sidecar (P3)      │
    │  GSAP+MIDI   │              │  audio→video       │
    └──────┬──────┘              └─────────┬──────────┘
           │                               │
           └──────────┬────────────────────┘
                      │
              ┌───────▼───────┐
              │  Frontend      │
              │  Room + Person │  ← 分层渲染（已完成）
              │  Compositing   │
              └───────────────┘
```

---

## Phase 0 — 当前已完成 ✅

### 交付物
| 组件 | 文件 | 状态 |
|------|------|------|
| Director 大脑 | `services/aria_director.py` | ✅ |
| Layout/Hands 输出 | `AriaLayout`, `AriaHands` 模型 | ✅ |
| 媒体规划器 | `services/aria_media.py` | ✅ |
| TTS (edge-tts) | `POST /v1/aria/tts` | ✅ |
| 前端分层组件 | `AriaDigitalHuman.tsx` | ✅ |
| GSAP 动画 | layout 位置 + hands 手臂 | ✅ |
| 房间/人物资产 | `room_*.jpg` + `person_*.png` | ✅ |
| 用户位置微调 | "往左/放大/坐琴凳" 指令解析 | ✅ |

### 已知局限
- 人物是静态抠图，手臂动画是 GSAP 模拟（不是真人运动）
- 不能"看见"房间里的物体/钢琴/乐谱
- 说话时嘴巴是 CSS viseme 模拟（不是真嘴型）
- 手部动作和实际钢琴音符不同步

---

## Phase 1 — 感知层 (VLM Perception)

### 目标
让 Aria 能"看见"当前场景：识别房间里的物体（钢琴、书架、窗户）、判断时间/光线、感知用户状态。

### 技术方案

```
┌──────────────┐    截图/描述     ┌──────────────┐
│  场景状态     │ ──────────────→ │  VLM 模型    │
│  (room type, │                  │  (Qwen-VL    │
│   time, etc) │ ←────────────── │   或 API)    │
└──────────────┘    结构化描述    └──────────────┘
       │
       ▼
  Director state.perception = {
    objects: ["grand_piano", "bookshelf", "window"],
    lighting: "warm_afternoon",
    mood: "focused_practice",
    user_visible: true
  }
```

### 实现步骤

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 1.1 | VLM oprim：调用视觉模型，返回结构化场景描述 | `oprim/vlm_scene.py` | 4h |
| 1.2 | 场景缓存：同一房间不重复推理 | `services/aria_perception.py` | 2h |
| 1.3 | Director 集成：`state["perception"]` 注入 prompt | `services/aria_director.py` | 3h |
| 1.4 | 前端场景快照：定时截图或 room 描述上传 | `aria-stage.ts` | 4h |
| 1.5 | 测试 | `tests/test_aria_perception.py` | 2h |

### 硬件需求
- **本地方案**：Qwen2-VL-7B-Instruct-GPTQ-Int4（~5GB VRAM）可在 3080 跑
- **API 方案**：调用阿里云 Qwen-VL / 通义千问视觉 API（按量付费，~0.02元/次）
- **推荐**：先用 API 验证效果，确认有价值后再本地部署

### 依赖
- `transformers` + `qwen-vl-utils`（本地）或 `dashscope` SDK（API）
- 无需新增容器

### 交付效果
Aria 能说："我看到你面前是一架三角钢琴，下午的阳光从窗户照进来，适合弹一首肖邦。"

### 工期：**1 周**

---

## Phase 2 — 手势增强 (Simulated Hands + MIDI Sync)

### 目标
在不引入 EchoMimic 的前提下，让现有的 GSAP 手臂动画更真实：
- 手指级动画（不只是整个手臂摆动）
- 与钢琴音符同步（MIDI 数据驱动手势）
- 不同演奏技巧的手型（和弦、琶音、音阶）

### 技术方案

```
┌──────────────┐   MIDI events    ┌──────────────┐
│  pianoAmbience│ ──────────────→ │  Hand Choreo  │
│  (audio+MIDI) │                  │  Engine       │
└──────────────┘                  └──────┬───────┘
                                         │
                              ┌──────────▼──────────┐
                              │  GSAP Timeline       │
                              │  - left_hand {x,y,r} │
                              │  - right_hand {x,y,r}│
                              │  - finger_spread     │
                              │  - wrist_bounce      │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  SVG 手部叠加层      │
                              │  (person PNG 上)     │
                              └─────────────────────┘
```

### 实现步骤

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 2.1 | MIDI 解析 oprim：从 pianoAmbience 提取 note-on/off 事件 | `oprim/midi_parse.py` | 3h |
| 2.2 | 手型编排：和弦/琶音/音阶 → 手部参数映射 | `oskill/hand_choreo.py` | 6h |
| 2.3 | 手部 SVG 叠加层：半透明手部轮廓 + GSAP 骨骼动画 | `AriaHands.tsx` (新组件) | 8h |
| 2.4 | Director hands 扩展：支持 `hand_choreo` 字段 | `aria_director.py` | 2h |
| 2.5 | 音频同步：Web Audio analyser → 实时音高 → 手部触发 | `aria-digital-human.tsx` | 4h |
| 2.6 | 测试 | `tests/test_hand_choreo.py` | 2h |

### 硬件需求
- **无新增**：纯前端 GSAP + SVG 动画

### 依赖
- `midi-file` npm 包（MIDI 解析）或 Python `mido`
- GSAP（已安装）
- 手部 SVG 素材（需绘制或生成，约 4 组手型 × 3 状态）

### 交付效果
Aria 弹钢琴时，手臂和手指会随着实际的音符节奏和位置移动，不再是"随机摆动"。

### 工期：**1 周**

---

## Phase 3 — EchoMimic V2 侧车 (Real Digital Human Driving)

### 目标
用 EchoMimic V2 替换当前的静态人物抠图层，实现：
- 音频驱动的面部表情和嘴型（真嘴型，不是 CSS viseme）
- 半身运动（自然的上半身晃动、头部转动）
- 可选：手部姿态输入 → 生成弹琴动作

### 技术方案

```
┌──────────────┐    audio (mp3)    ┌──────────────────────┐
│  edge-tts    │ ───────────────→  │  EchoMimic V2        │
│  (或用户语音) │                   │  Sidecar Container    │
└──────────────┘                   │                      │
                                   │  输入:                │
┌──────────────┐   hand_pose (opt) │   - audio.mp3        │
│  hand_choreo │ ───────────────→  │   - ref_image.jpg    │
│  (from P2)   │                   │   - hand_pose.json   │
└──────────────┘                   │                      │
                                   │  输出:                │
                                   │   - video.mp4 (半身)  │
                                   └──────────┬───────────┘
                                              │
                                   ┌──────────▼───────────┐
                                   │  前端视频替换          │
                                   │  person layer → video │
                                   │  room layer 不变      │
                                   └─────────────────────┘
```

### 架构决策

**为什么用侧车（sidecar）而不是嵌入主容器？**
- EchoMimic V2 需要 ~8GB VRAM（半身模式），与 API 服务隔离避免争抢
- 独立扩缩容：弹钢琴时启动，不弹时休眠
- 推理延迟（2-5 秒生成 10 秒视频）可异步处理

### 实现步骤

| # | 任务 | 文件 | 工时 |
|---|------|------|------|
| 3.1 | EchoMimic V2 Docker 镜像 | `docker/echomimic/Dockerfile` | 8h |
| 3.2 | 侧车 API 封装：`POST /generate` (audio, ref_image, hand_pose) → video | `docker/echomimic/server.py` | 6h |
| 3.3 | docker-compose 集成：`echomimic` service + GPU 分配 | `docker-compose.yml` | 3h |
| 3.4 | 后端 oprim：调用 EchoMimic 侧车，缓存结果 | `oprim/echo_drive.py` | 4h |
| 3.5 | 媒体规划器集成：`action=play_piano` 时调 EchoMimic | `services/aria_media.py` | 4h |
| 3.6 | 前端视频层：`<video>` 替换 person PNG | `AriaDigitalHuman.tsx` | 4h |
| 3.7 | 预生成缓存：常用动作预渲染，减少在线延迟 | `scripts/prebake_echo.sh` | 3h |
| 3.8 | 降级策略：EchoMimic 不可用时回退到 P2 模拟 | `aria_media.py` + 前端 | 3h |
| 3.9 | 测试 | `tests/test_echo_drive.py` | 3h |

### 硬件需求（关键）

| 场景 | 最低配置 | 推荐配置 |
|------|---------|---------|
| 只面部（无手部） | RTX 3060 12GB | RTX 3080 10GB（当前） |
| 半身 + 手部 | RTX 4070 12GB | **RTX 4090 24GB** 或 **云 A10G** |
| 并发 2 用户 | 不可行 | 2× RTX 4090 或云 2× A10G |

**3080 10GB 现实评估**：
- EchoMimic V2 半身模式需 ~8GB，留给 API 服务的空间很紧
- **方案 A**：用 `--gpus '"device=1"'` 隔离（如果有第二张卡）
- **方案 B**：云 GPU 侧车（阿里云 GPU 实例 / RunPod / Vast.ai），按需启动
- **方案 C**：只在"弹钢琴"场景调用云 GPU，日常对话仍用本地模拟

**推荐**：方案 C（混合），理由：
- 日常对话不需要 EchoMimic（P2 模拟够用）
- 弹钢琴是高频但非持续场景，按需调用云 GPU 成本可控
- 预计成本：~¥0.5-1/分钟 云 GPU（A10G）

### 依赖
- EchoMimic V2 仓库：https://github.com/Badmao/EchoMimicV2
- PyTorch 2.0+ CUDA 12.x
- ffmpeg（已安装）
- 参考图像：需要一张 Aria 的高质量正面参考图（当前 `face-play.jpg` 可用）

### 延迟与缓存策略
- 首次生成：2-5 秒（不可接受实时）
- **预渲染池**：提前生成 10 个"弹琴片段"（不同时长/情绪），随机抽取
- **流式生成**：EchoMimic 支持 chunk 输出时，边生成边播放
- **缓存命中率目标**：>80% 的请求命中预渲染缓存

### 交付效果
Aria 弹钢琴时：
- 真实的嘴型（如果边弹边唱/说话）
- 自然的半身运动
- 手部实际在动（如果提供 hand_pose 输入）
- 不再是"贴上去的抠图"

### 工期：**3-4 周**（含 GPU 环境搭建 + 调试）

---

## Phase 4 — 全身自由 (MetaHuman / ACE) [可选]

### 目标
完全自由的 3D 数字人：
- 全身运动（站/坐/走/转身）
- 面部微表情（眉毛、眼睛、嘴角 52 个 blendshape）
- 手指级精确控制
- 实时渲染

### 技术方案
- NVIDIA ACE + Unreal Engine 5 MetaHuman
- Pixel Streaming 云端渲染 → 浏览器接收视频流
- Director 通过 ACE API 控制动作

### 评估

| 维度 | 评估 |
|------|------|
| 效果 | ⭐⭐⭐⭐⭐（最佳） |
| 工期 | 2-3 个月 |
| 成本 | 高（UE5 开发 + 云 Pixel Streaming ~¥3-5/小时） |
| 运维 | 复杂（UE5 服务器 + TURN 中继） |
| 必要性 | **当前阶段不推荐** |

### 推荐
**暂不实施。** 当 P1-P3 全部上线且用户反馈需要更高自由度时再考虑。

---

## 时间线总览

```
Week 1          Week 2          Week 3-4         Week 5+
────────        ────────        ─────────        ───────
[P1 感知层]     [P2 手势增强]   [P3 EchoMimic]   [上线+优化]
VLM 场景识别    MIDI 手部同步    侧车部署          缓存策略
Director 集成   SVG 手部叠加     视频层替换        延迟优化
~15h            ~25h             ~38h             持续
```

### 里程碑

| 里程碑 | 目标日期 | 验收标准 |
|--------|---------|---------|
| M1: Aria 能"看见" | Week 1 末 | Director 输出含 perception 字段，描述准确 |
| M2: 手部同步 | Week 2 末 | 弹琴时手指与 MIDI 音符同步 |
| M3: 真实驱动 | Week 4 末 | EchoMimic 视频替换 person 层，自然运动 |
| M4: 生产就绪 | Week 5+ | 缓存命中率 >80%，延迟 <3s，降级策略生效 |

---

## 硬件矩阵

| 组件 | 当前 (3080 10GB) | P1 需求 | P2 需求 | P3 需求 |
|------|-----------------|---------|---------|---------|
| API 服务 | ✅ 运行中 | ✅ 不变 | ✅ 不变 | ⚠️ 需隔离 |
| VLM 推理 | N/A | ✅ API 调用 | — | — |
| EchoMimic | N/A | — | — | ⚠️ 需云 GPU |
| 前端渲染 | ✅ | ✅ | ✅ | ✅ |

### 硬件投资建议

| 优先级 | 投资 | 成本 | 收益 |
|--------|------|------|------|
| 1 | 云 GPU 按需调用 | ~¥100/月 | P3 可用 |
| 2 | 第二张 GPU（3060 12GB） | ~¥2000 一次性 | API + EchoMimic 隔离 |
| 3 | 升级到 4090 24GB | ~¥12000 一次性 | 全本地运行 |

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|---------|
| EchoMimic 延迟不可接受 | 中 | 高 | 预渲染池 + 降级到 P2 模拟 |
| 3080 VRAM 不足 | 高 | 高 | 云 GPU 侧车（方案 C） |
| VLM 描述不准确 | 低 | 中 | 人工审核 + 缓存可信描述 |
| 手部 SVG 不自然 | 中 | 低 | 渐进优化，用户可关闭 |
| EchoMimic 手部输入不支持 | 中 | 高 | 退化为半身（无手部），P2 补充 |

---

## 立即行动项

根据当前状态，建议的执行顺序：

1. **本周**：开始 P1（感知层）— 风险低，无需新硬件，增强 Aria "智能感"
2. **下周**：并行 P2（手势增强）— 纯前端工作，与 P1 不冲突
3. **第 3 周**：P3 环境搭建（EchoMimic Docker + 云 GPU 账号）
4. **第 4 周**：P3 集成 + 测试 + 上线

---

## 文件结构规划

```
mneme/
├── oprim/
│   ├── vlm_scene.py          # P1: VLM 场景描述
│   ├── midi_parse.py         # P2: MIDI 事件提取
│   └── echo_drive.py         # P3: EchoMimic 调用
├── oskill/
│   └── hand_choreo.py        # P2: 手型编排
├── services/
│   ├── aria_director.py      # P1: +perception 字段
│   ├── aria_media.py         # P3: +EchoMimic 集成
│   └── aria_perception.py    # P1: 场景缓存
├── docker/
│   └── echomimic/            # P3: 侧车容器
│       ├── Dockerfile
│       └── server.py
└── tests/
    ├── test_aria_perception.py
    ├── test_hand_choreo.py
    └── test_echo_drive.py

mneme-web/
├── src/components/aria/
│   ├── AriaDigitalHuman.tsx  # P2/P3: 手部叠加 / 视频层
│   └── AriaHands.tsx         # P2: 手部 SVG 组件
└── public/aria/
    └── hands/                # P2: 手部 SVG 素材
```

---

## 总结

**当前能力**：Aria 有大脑、有位置控制、有简单手势模拟。

**完整能力**（P1-P3 完成后）：
- 🧠 **大脑**：Director + VLM 感知 → 知道"在哪、做什么、看到什么"
- 🎹 **弹琴**：MIDI 同步手部动画 + EchoMimic 真实驱动
- 👁️ **感知**：能描述房间、识别物体、感知用户
- 🗣️ **说话**：edge-tts + (未来) 真嘴型同步

**推荐立即开始 P1**，一周内可见效果，且不影响现有系统。
