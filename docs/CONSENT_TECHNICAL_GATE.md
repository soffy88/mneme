# Consent Technical Gate

这是技术 gate，不是法律、研究伦理或监护政策定义。

`ConsentStatus`：

- `UNKNOWN`
- `NOT_REQUIRED`
- `PENDING`
- `GRANTED`
- `REVOKED`

当 protocol `requires_consent=true`（默认）时，enrollment 必须带：

- `consent_status=GRANTED`
- `consent_version`
- `consent_recorded_at`

缺失任一项都拒绝 enrollment。撤回同意会将 enrollment 标为 `REVOKED`，并使未完成
的 measurement schedules 进入 `INVALIDATED`；普通学习功能不受影响。purge service
覆盖 student-scoped pilot tables，export 只包含最小 metadata。

owner 仍需决定适用法律、年龄/监护规则、consent 文案和研究伦理流程；代码不替 owner
做这些决定，也不伪造 consent。
