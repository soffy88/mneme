# Monetization Readiness

Mneme has a provider-neutral commercial boundary. Prices are
`TBD_OWNER_DECISION`; no payment provider is configured by default.

- `FREE`: Learn Now, basic Cognitive State, reviews, and basic progress remain
  available so the core learning loop is not paywalled.
- `PRO`: advanced analytics, deep evidence history, advanced learning reports,
  longer history, advanced export, and premium AI usage may be entitled.

Entitlements are checked server-side. Unknown users, capabilities, expired or
canceled subscriptions fail closed for premium capabilities. `FakeBillingProvider`
is test-only and cannot be constructed in production. Without a real provider,
the system returns `BILLING_PROVIDER_NOT_CONFIGURED`.
