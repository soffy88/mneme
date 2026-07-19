# ⚠️ 本目录已废弃 —— 请勿开发、勿审计、勿作为验收依据

**真前端 = `/data/soffy/projects/mneme-web`（Next.js App Router PWA，善学记）。**

本 `frontend/`（Vite + React）是遗留旧版，**不在任何部署路径**：
- 不在 docker-compose，无生产 Dockerfile，无 Cloudflare 路由；
- 线上 `sxueji.com` 指向 `mneme-web`（`.env.production` → `api.sxueji.com`）。

## 为什么留这个文件

审计（2026-07-03）发现 TASKS.md 的 R.1–R.17 一整批"前端"工作误建在本目录，
并用 `vite build 通过` 当验收标准 —— 而 mneme-web 早已独立重做同一批功能，
造成约 8 个 task、25–30 个组件的重复劳动。**看板验收门与真前端脱节。**

## 硬规矩

1. 任何前端改动去 `mneme-web` 仓；本目录只读、待归档。
2. 验收标准一律用 `cd mneme-web && npx tsc --noEmit && npm run build`，**不用 `vite build`**。
3. 后端端点是真资产、mneme-web 在用——本目录作废的只是 UI 层。
