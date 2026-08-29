# ADR-0014：媒体与派生文本的 Content Provenance

- 状态：Accepted
- 日期：2026-08-29
- 范围：MediaAsset / Transcript / Translation 等的来源与版权边界记录

## 决策

凡进入 Immersive Learning 的媒体与派生文本**必须**记录 content provenance。
`MediaAsset.content_provenance` 取值：

`user_uploaded` | `user_owned` | `licensed` | `public` | `external_reference`

派生 Transcript / Translation / ASR 产物额外记录：`source`、`model/version`、
`confidence`、`timestamp`（及既有 Event `provenance` 字段）。低置信输入不得静默
升级为高置信事实。

版权与获取硬规则：

- **禁止** DRM 破解、付费墙绕过、平台限制绕过。
- **禁止** YouTube（或同类）**downloader** 作为产品能力；外部平台仅可以
  **reference** 方式（见 ADR-0015），不得把规避下载做成功能。
- 上传音视频按隐私类 P2–P3；语音作答 P3；新持久化表同 PR 纳入
  `services/purge_service._STUDENT_TABLES`，对象存储走既有 cleanup 模式。

## 不变的红线

- 无 provenance 的媒体不得进入可写认知/FSRS 路径（至少须拒绝或降级为不可投影）。
- 不得实现/依赖 downloader 或 DRM bypass 工具链。
- 导出/家长通道继续按既有隐私类脱敏，不外发非必要 PII 与原文片段。

## 验证

入库/API 契约要求 `content_provenance`；缺少则 4xx 或不可投影；CI/文档审查排除
downloader/paywall-bypass 依赖；purge 列表含新媒体相关学生表。
