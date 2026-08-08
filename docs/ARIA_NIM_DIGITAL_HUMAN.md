# Aria 数字人 · Hybrid B + NIM 指挥架构

> 目标：Aria 由 **AI Director 指挥**，**3D 身体可自由行动**（走 / 坐琴 / 弹 / 对话），**脸为照片级真人贴图**；可回退全景静图；真 NIM 脸流可选。

## 分层

```
┌─────────────────────────────────────────────┐
│  Intelligence（本仓库）                        │
│  POST /v1/aria/act  ·  services/aria_director │
│  LLM 输出：action + utterance + emotion       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  Runtime（前端）                               │
│  hybrid（默认 B）| photo（全景静图）| nim（可选）│
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  hybrid 渲染                                   │
│  3D 身体（R3F 状态机）+ 照片脸贴图 + 简易口型   │
│  资源：/aria/face-front.jpg · face-play.jpg   │
└─────────────────────────────────────────────┘
```

## 前端默认

| 模式 | 组件 | 说明 |
|------|------|------|
| **cinema（默认，Phase 1+2）** | `AriaCinemaLayer` | 写真双层 + GSAP 琴键 + CSS viseme / GPU 口型视频 |
| hybrid / VRM | `scene3d/*` 代码保留 | **不进默认 UI** |
| lipsync GPU | `ARIA_LIPSYNC_BASE_URL` | LivePortrait/Echo 侧车 → `POST /v1/aria/lipsync` |
| nim | `ARIA_NIM_BASE_URL` | Audio2Face（可选） |

## Phase 1–3 + 语音 API

| 端点 | 作用 |
|------|------|
| `POST /v1/aria/act` | Director 行动 |
| `POST /v1/aria/lipsync` | 口型：有侧车返 `video`，否则 `viseme_css` |
| `POST /v1/aria/tts` | edge-tts `en-US-AriaNeural` → `audio_b64`；失败前端 Web Speech |
| `GET /v1/aria/media-plan?action=` | 静图池 / clip 规划 |
| `GET /v1/aria/runtime` | features: cinema / clip_pool / tts_edge / lipsync_gpu |

### Clip 池（Phase 3）

- 静图：`mneme-web/public/aria/clips/playing_00.jpg` … `_02.jpg`，约 9s 交叉轮播  
- 可选视频：放置 `playing_loop.mp4` 或设 `ARIA_CLIP_PLAYING_URL`（存在则优先播）  
- OmniHuman/Echo 离线产出后放入同目录即可，无需改代码  

侧车约定：`POST {ARIA_LIPSYNC_BASE_URL}/v1/lipsync` JSON `{text,emotion,still_url}` → `{video_url,duration_ms}`。  
依赖：`edge-tts>=6.1.0`（`requirements.txt`）。

用户可在首页右上角 **「◎ 3D·真人脸 / ▣ 全景照片」** 切换。

## 本机条件

- GPU：RTX 3080 10GB（WebGL 足够；完整 ACE/MetaHuman 另议）
- 脸贴图：从写实写真裁切的 `face-front` / `face-play`
- 身体：程序化女性体态 + 黑裙（可后续换 VRM 同 `goal` 接口）

## 行动集

`play_piano | look_at_user | speak | think | return_to_piano | idle`

## 与「循环视频 / 纯胶囊人」区别

| 循环视频 | 纯胶囊 3D | Hybrid B（当前） |
|----------|-----------|------------------|
| 固定片源 | 不像人 | 脸=照片真人级 |
| 无走动 | 可走但不像 | 可走可弹可聊 |
| 无指挥 | 可接 Director | Director 已接 |

## 后续升级路径

1. **VRM/写实 GLB** 替换 `AriaHumanoid` 身体（同 `HumanoidGoal`）
2. **LivePortrait / Audio2Face** 驱动脸贴图或 blendshape（`nimAdapter.nimDriveFace`）
3. Unreal MetaHuman + Pixel Streaming（独立运维，非本阶段）
