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

## 实测：sxueji.com 已上线（`*.uex.hk`/`*.kanpan.co` 已停用）
- `https://sxueji.com` → 307 → mneme-web（现有 SPA）。
- `https://api.sxueji.com/health` → 200（**全 api 已公网，mneme-web 依赖**）。
- `https://sxueji.com/mcp/*` → 404、`https://sxueji.com/studio/*` → 404（**studio + /mcp 尚未接线**）。
- sxueji.com 的 ingress **不在本机任何 cloudflared 配置文件**里（本机 config-file tunnel 全是已停用的
  uex.hk；token/dashboard tunnel 属其他项目）——即 **sxueji.com 走 Cloudflare dashboard 托管 ingress**。

## 🔴 阻断（prod apply，需 Cloudflare dashboard 权限 + ops 受控窗口）
1. **sxueji.com ingress 是 dashboard 托管**：给 sxueji.com 加 `/studio/*→studio`、`/mcp/*→api` 路由，
   须在 **Cloudflare dashboard** 改该 tunnel 的 public hostname/ingress —— **本机 CLI/文件改不了**，需账号权限。
2. **活的多项目共享 prod 机**：本机同跑 mneme-web / hevi / aii / helios / stratum / tide / aegis 及各自 tunnel；
   加 studio 服务/改路由须受控窗口，防跨项目 blast radius。
3. **同 host 模型改活的 sxueji.com 路由**：/studio、/mcp 规则要排在 mneme-web 兜底前，验不与 SPA 冲突。
4. **pre-session 端点**：本模型只保证 sxueji.com 这个 host 上非 /studio·/mcp 不额外暴露；但**全 api 仍在
   api.sxueji.com 公网**（mneme-web 依赖，不动）——锁 api.sxueji.com 是独立的 web/api 安全评审，不在 S3-B。

**结论**：studio 代码 + standalone 产物 + 部署规范就绪；实际 apply（build 镜像、加 compose 服务、
**Cloudflare dashboard 加 sxueji.com 的 /studio+/mcp ingress**）需账号权限 + ops 受控窗口，交 Wiki/ops。
CC 不在 dev 会话改活的共享 prod / 无 dashboard 权限。
