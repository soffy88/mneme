# mneme-studio 部署规范（W2b S3-B）

**状态**：**规范就绪，prod apply 阻断**（见 §阻断）。暴露模型已定：**同 host 路径路由**，域名 **sxueji.com**。

## 暴露模型（已拍板）
同一 host（sxueji.com）按路径路由；studio + `/mcp/*` 对外，其余走 mneme-web：
```
sxueji.com/studio/*  → mneme-studio:3001   （studio，basePath=/studio）
sxueji.com/mcp/*     → mneme-api-1:8000     （只放门控工具面）
sxueji.com/*         → mneme-web:3000       （现有 SPA）
```
studio 的 `NEXT_PUBLIC_API_BASE` = 同源（空/`https://sxueji.com`），故 `/mcp` 调用留在本 host、无 CORS。
**pre-session api 端点（auth/textbook/quiz…）不在 sxueji.com 暴露**（该 host 只有 /studio、/mcp，其余按 mneme-web 路由，非 /mcp 的 api 路径不对外）。

## cloudflared ingress（加到 sxueji.com 的 tunnel 配置，404 兜底前，**顺序在 mneme-web 规则之前**）
```yaml
  - hostname: sxueji.com
    path: ^/mcp/.*
    service: http://mneme-api-1:8000
  - hostname: sxueji.com
    path: ^/studio/.*
    service: http://mneme-studio:3001
  - hostname: sxueji.com
    service: http://mneme-web:3000   # 其余 → 现有 SPA
```

## compose 服务（加到部署 compose，helios-net 内名 mneme-studio:3001）
```yaml
  mneme-studio:
    build:
      context: .                     # apps/mneme-studio；@helios/blocks 为 file: 本地依赖，
      dockerfile: Dockerfile         # 构建需 blocks 包在 context 内（vendor 化，见下）
    image: mneme-studio:latest
    environment:
      NODE_ENV: production
      NEXT_PUBLIC_API_BASE: ""       # 同源
    networks: [helios-net]
    # 主机自检可加 ports: ["3301:3001"]；公网走 cloudflared，不直接开端口
```
`output: standalone` 已开（next.config）。Dockerfile 多阶段（deps→build→run），参考 mneme-web；
**注意 @helios/blocks 是 `file:` 本地依赖**，Docker build context 不含仓外 platform/ —— 需先把
`@helios/blocks` vendor 化（tarball 或 copy 进 context）再 `npm install`（同 mneme-web 的 vendor 方案）。

## 🔴 阻断（prod apply 前必须先解决，均属 prod 基础设施 / 需 Cloudflare 账号权限）
1. **sxueji.com 未接线**：跑着的 tunnel 只有 `*.uex.hk` / `*.kanpan.co`，**无任何 sxueji.com hostname**，
   mneme-web 现服务于 `mneme.uex.hk` 而非 sxueji.com。同 host 路由要求 sxueji.com 先作为 tunnel host 存在，
   且 mneme-web/api 也在该 host 提供 —— 即先把整个 sxueji.com（DNS + tunnel + web/api 路由）立起来。
2. **活的多项目共享 prod 机**：本机同时跑 mneme-web / hevi / aii / helios / stratum / tide / aegis 及各自 tunnel。
   改 tunnel/网络/compose 有跨项目 blast radius，须在受控窗口由 ops 执行。
3. **改动活的 mneme-web host 路由**（同 host 模型）：/studio、/mcp 规则要排在 mneme-web 兜底前，
   需验证不与 SPA 路由冲突。

**结论**：studio 侧代码 + 部署规范就绪；实际 prod apply（wiring sxueji.com、加服务、改活 tunnel）
需 Cloudflare 账号权限 + 受控窗口，交 Wiki/ops。CC 不在 dev 会话里改活的共享 prod。
