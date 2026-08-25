# ADR-0005：互操作出口与隐私安全观测边界

- 状态：Accepted
- 日期：2026-08-25
- 范围：Blueprint §17–18 的仓库内互操作、追踪和基础观测契约

## 决策

Mneme 的内部 `LearningEvent v2` 保持唯一事实契约，标准出口通过纯适配器生成：

- `xapi`：一条事件对应一个 xAPI statement；actor 使用 Mneme 基础 URI + UUID 的
  伪匿名 account，不导出姓名、邮箱或原始 URL 参数；
- `caliper`：输出 AssessmentEvent/Attempt/Result 的标准字段，Mneme 扩展字段置于
  namespaced extensions；
- `case`：输出 CFDocument、CFItems 和 CFItemAssociations。CASE 能力项关联只表示
  observed/exemplifies，不表示掌握或因果效果；
- `mneme`：保留原有完整 v2 导出格式，作为默认向后兼容行为。

适配器默认脱敏 P2/P3 的 response、process、metacognitive 和 intervention；学生本人
导出可按授权策略关闭该脱敏，家长/第三方导出仍走现有过程数据分享判定。外部消费者若要
回流数据，必须先转回 v2 并保留 `provenance.adapter`，不能直接写 projection。

HTTP 层为每个请求生成或接受受限 `X-Trace-Id`，返回同名响应头；观测指标只按 FastAPI
路由模板聚合，记录请求量、5xx 错误率和 p50/p95 延迟，不记录学生 ID、query/path 参数、
答案内容或 token。`/health/metrics` 是进程级 JSON scrape 基线；接入持久化 metrics
backend 不改变上述字段边界。

## 不变的红线

- 互操作出口不得把 `p_mastery`、`is_mastered` 或 policy decision 当作学习事实。
- 导出权限仍由现有学生/家长/admin 鉴权决定；适配器不自行放宽访问。
- 观测失败不能改变学习请求结果；指标为诊断信息，不参与掌握度或策略门控。

## 验证

`tests/test_event_interoperability.py` 覆盖 xAPI/Caliper/CASE 形状、隐私脱敏和格式
分派；`tests/test_observability.py` 覆盖 trace ID 边界、模板标签、错误率和延迟聚合。
