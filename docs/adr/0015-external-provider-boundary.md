# ADR-0015：外部媒体 Provider 边界

- 状态：Accepted
- 日期：2026-08-29
- 范围：媒体源适配器与认知层对具体 provider 的隔离

## 决策

媒体源策略分阶段：

| Adapter | V1 | Later | 说明 |
|---------|----|-------|------|
| `LOCAL_UPLOAD` | ✅ | | 用户上传至对象存储 |
| `OBJECT_STORAGE` | ✅ | | 签名 URL 正规提供 |
| `DIRECT_MEDIA_URL` | 有限 | ✅ | 仅 CORS/公开且无 DRM；无 bypass |
| `EXTERNAL_PROVIDER` | ❌ | ✅ | YouTube 等作 **reference**，非 downloader |

**认知层（LearningEvent / Evidence / CognitiveState / Policy / FSRS / Memory
Router）必须 provider-agnostic**：不得 import 具体云厂商/平台 SDK；只消费归一化
后的 `MediaAsset` + provenance + 学习事件。Provider 适配停在 Media 摄入/播放
边界（services/worker 适配器），失败不得腐蚀掌握度写路径。

外部 provider 晚于 V1；引入时仍遵守 ADR-0014（provenance 必填、无 DRM/paywall
bypass、无 downloader）。

## 不变的红线

- 认知 / 调度 / 策略代码禁止依赖具体 EXTERNAL_PROVIDER SDK。
- 外部引用 ≠ 授权下载；不能把“能播”做成“能存平台受保护媒体”。
- V1 不得偷偷上线 YouTube downloader 或同类能力。

## 验证

架构/import 守卫：认知写路径与 omodul 无 provider SDK；Media adapter 可替换而不
改 Evidence/FSRS 契约；EXTERNAL_PROVIDER 特性门默认关闭直至单独 ADR/发布。
