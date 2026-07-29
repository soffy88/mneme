# Aria 独立数字人路径（NIM 大脑 + EchoMimic 驱动）

> 用户结论（正确）：**房间背景不应整图晃动**；要的是**独立人像数字人**，大脑用 NIM/Director，驱动用 EchoMimic 一类。

## 1. 能不能做到底？

| 层次 | 能否 | 说明 |
|------|------|------|
| **NIM/Director 做大脑** | ✅ 已具备 | `POST /v1/aria/act` 已是 Intelligence 层 |
| **独立数字人（人动、景不动）** | ✅ 能 | 必须走 **人像驱动生成**，不是 Ken Burns / 整图运镜 |
| **本机 3080 实时 EchoMimic V2** | ⚠ 紧 | 半身驱动可试，长视频/高并发偏紧；常见 **异步出片 + 播放** |
| **实时可走可弹 MetaHuman** | ❌ 非本阶段 Web | 需 Unreal/Pixel Streaming 或云 ACE |

**结论**：能做到「NIM 指挥 + 写真身份 + EchoMimic 驱动的半身数字人」；做不到「浏览器里实时电影级自由走动」除非上另一套栈。

## 2. EchoMimic V2 适不适合？

**适合（对话 / 半身互动）**

- 输入：参考人像图 + **音频**（+ 可选手部 pose）
- 输出：半身动画视频——**脸、口型、上身、手势** 与音频相关
- 论文/项目明确面向 semi-body、hand + audio（CVPR 2025 方向）

**不完全适合（当「真·钢琴演奏仿真」）**

- 不是「对着固定三角钢琴场景做物理级指法」
- 无手部 pose 时手势范围有限；要特定弹奏动作需 **手部 pose 序列** 或后处理
- 场景/钢琴通常随参考图一起生成，**不是**自动把人从房间里抠出来叠层（除非你做 matting 合成管线）

**更贴切的分工**

| 场景 | 推荐驱动 |
|------|----------|
| 对话、看用户、说话 | **EchoMimic V2** 或 LivePortrait（脸/半身） |
| 弹琴观感 | 固定场景写真 + **半身/手区驱动片**；或 OmniHuman 全图短片（离线） |
| 自由走动 | VRM/Unreal，不是 EchoMimic |

## 3. 正确分层（房间固定）

```
┌─────────────────────────────────────────┐
│  NIM / Director（大脑）✅                 │
│  action = play_piano | speak | …        │
│  utterance → TTS 音频                    │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Media Runtime（身体）                    │
│  A. 背景层：固定房间静图（永远不动）         │
│  B. 人像层：EchoMimic 驱动视频 / 口型     │
│     或全图驱动片（参考图含固定构图）        │
└─────────────────────────────────────────┘
```

**禁止**：整图 Ken Burns / zoompan（已撤销为默认）。

## 4. 落地阶段（做到底的路径）

### Stage D1 — 产品诚实默认（已做）
- 固定写真；无整图晃动
- Director + edge-tts + CSS viseme
- 仅当 `ARIA_CLIP_*` / lipsync 侧车有**真驱动片**时才播视频

### Stage D1.5 — 独立图层数字人（已做 · 2026-07-29）
- `public/aria/dh/`：`room_*`（背景永不动画）+ `person_*` PNG 抠像
- 前端 `AriaDigitalHuman`：只对**人像层**做呼吸/弹琴/说话动画
- 角标：`ARIA · Digital Human`
- EchoMimic 视频仍可替换人像层

### Stage D2 — EchoMimic 侧车 ✅ 已完成（2026-07-29）
- `docker/echomimic/`: Dockerfile (CUDA 12.1) + FastAPI server (`POST /generate`)
- `docker-compose.yml` echomimic service (profile=gpu, nvidia 设备)
- API: `ECHO_BASE_URL` 环境变量 → `POST /v1/aria/echo-drive`
- 流程: `utterance` → edge-tts audio → EchoDrive(audio, hand_pose) → video_b64
- 前端: AriaDigitalHuman `echoVideoUrl` prop，`<video>` 优先于 person PNG
- 降级: EchoMimic 不可用 → P2 模拟 → 静态 PNG（三级降级，无中断）
- 预烘焙: `scripts/prebake_echo.sh` 生成缓存 → `public/aria/echo_cache/`

### Stage D2.5 — VLM 感知 + MIDI 手部编排 ✅ 已完成（2026-07-29）
- **P1 感知**: `vendor/oprim/vlm_scene.py` + `services/aria_perception.py`
  - 文本/VLM 双入口；LRU 缓存；Director 注入 perception_brief
  - `POST /v1/aria/perception` 端点；前端挂载时自动上传房间描述
- **P2 手部编排**: `vendor/oprim/midi_parse.py` + `vendor/oskill/hand_choreo.py`
  - MIDI 事件 → 音型分类 (chord/arpeggio/scale/bass/melody)
  - → HandChoreoParams (左右手 x/y/rotation/scale + finger_spread + wrist_bounce)
  - 前端: `AriaHands.tsx` SVG 叠加 + GSAP 骨骼动画
  - 实时: `pianoAmbience.onNote` → `choreoFromNote` → hand_choreo 更新
- **E2E 集成**: AriaStage 全链路串通，runtime.features 报告 P1-P3 特性
- **Tests**: 110 passed (P1:34 + P2:43 + P3:17 + E2E:7 + 原有:9)

### Stage D3 — 人景分离 ✅ 已在 D1.5 实现
- 背景：空房间静图 (`room_play.jpg` / `room_talk.jpg`)
- 人像：PNG 抠像或 EchoMimic 视频
- 合成：前端两层绝对定位（GSAP 只动人像层）

### Stage D4 — 弹琴专用 ✅ 已在 D2.5 实现
- 手部 pose 序列: `midi_parse` → `hand_choreo` → SVG/GSAP 动画
- EchoMimic V2 手部引导: `hand_pose` 参数传入 sidecar
- 预烘焙缓存: `prebake_echo.sh` 离线生成弹琴视频池

## 5. 与「NIM」的关系

- 你们说的 **NIM 大脑** ≈ 已实现的 **Director**（可换更强 LLM / 真 NVIDIA ACE Agent）
- **NIM Audio2Face** = 脸部 blendshape 另一条线；与 EchoMimic 二选一或对话用 Echo、以后再接 A2F
- 不要用 VRM 胶囊人冒充数字人（已证伪）

## 6. 资源

- EchoMimic V2: https://github.com/antgroup/echomimic_v2  
- 本仓库：`POST /v1/aria/act` · `/v1/aria/lipsync` · `/v1/aria/tts` · `AriaCinemaLayer`
