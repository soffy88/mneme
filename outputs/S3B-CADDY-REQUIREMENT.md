# S3-B Caddy 配置需求（交 aegis 配置）

**给谁**：aegis（`/data/soffy/projects/aegis/Caddyfile` 的负责方）。
**做什么**：给 mneme-web 的 caddy 块（`:8083`）加**路径路由**，使 `sxueji.com/mcp` → 门控 api、
`sxueji.com/studio` → studio、其余 → 现有 mneme-web。**不新建域名、不改 Cloudflare、不动其他项目块。**

## 现状（Caddyfile 里）
```caddyfile
# Mneme API
:8081 {
    reverse_proxy mneme-api-1:8000
}

# Mneme 前端
:8083 {
    reverse_proxy mneme-web:3000
}
```
sxueji.com 的 tunnel 指向 caddy `:8083`（web）。**请 aegis 确认这一点**（tunnel 配置在 Cloudflare dashboard，mneme 侧读不到）。

## 需求：把 `:8083` 块改成路径路由
```caddyfile
# Mneme 前端 + studio + 门控工具面（S3-B 同 host 路径路由）
:8083 {
    handle /mcp/* {
        reverse_proxy mneme-api-1:8000
    }
    handle /studio* {
        reverse_proxy mneme-studio:3001
    }
    handle {
        reverse_proxy mneme-web:3000
    }
}
```
- `/mcp/*` → `mneme-api-1:8000`（**保留 /mcp 前缀**，api 就按 /mcp/* 提供）。
- `/studio*` → `mneme-studio:3001`（studio 的 basePath=/studio，**保留前缀**；用 `/studio*` 覆盖 `/studio` 本身与子路径）。
- 其余 → `mneme-web:3000`（现状不变）。

## 效果 / 安全
- `sxueji.com/studio/learn` → studio；`sxueji.com/mcp/*` → 门控工具面；`sxueji.com/*` → mneme-web。
- **pre-session api 端点不在 sxueji.com 暴露**：sxueji.com 上只有 /mcp、/studio 命中 api/studio，其余全落 mneme-web；非 /mcp 的 api 路径在本 host 到不了 api。
- `:8081`（api.sxueji.com 全 api，mneme-web 依赖）**不动**。
- **`mneme-studio:3001` 由 mneme 侧起容器并接入 helios-net**（见下），aegis 配好上面路由即可按容器名直连。

## 前置（mneme 侧负责，已授权）
- 构建 `mneme-studio:latest` 镜像 + 起 `mneme-studio` 容器，接入 `helios-net`，容器名 `mneme-studio`，监听 3001。
- 起好后 aegis reload caddy 前，`caddy validate` 一下（共享 Caddyfile，防语法错波及其他项目）。

## 验证（配置 + 起服务后）
```
curl -s -o /dev/null -w "%{http_code}\n" https://sxueji.com/studio/learn      # 期望 200
curl -s -X POST https://sxueji.com/mcp/GetKCInfo -H 'Content-Type: application/json' \
     -d '{"kc_id":"renjiao-math-g10-a-ku004"}'                                # 期望门控 JSON
curl -s -o /dev/null -w "%{http_code}\n" https://sxueji.com/v1/auth/login     # 期望非 200（pre-session 端点不在本 host 暴露→落 mneme-web/404）
```
