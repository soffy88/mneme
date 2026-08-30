# mneme-studio 生产镜像（多阶段 standalone，参考 mneme-web）。
# @helios/blocks 走 vendor tarball（file:vendor/*.tgz），build context 内自足。

# 1) deps
FROM node:20-trixie-slim AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
COPY vendor ./vendor
RUN npm install --no-audit --no-fund

# 2) build（standalone 产物）
FROM node:20-trixie-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
# 同源：前端经 /mcp 调用留在 sxueji.com 本 host
ENV NEXT_PUBLIC_API_BASE=""
RUN npm run build

# 3) run
FROM node:20-trixie-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
RUN groupadd --system nodejs && useradd --system --gid nodejs --home-dir /app nextjs
# npm is a build-time tool and its bundled dependency tree is not needed by
# the standalone server.  Keep it out of the production filesystem.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
COPY --chown=nextjs:nodejs --from=builder /app/.next/standalone ./
COPY --chown=nextjs:nodejs --from=builder /app/.next/static ./.next/static
COPY --chown=nextjs:nodejs --from=builder /app/public ./public
USER nextjs
EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3001/studio/learn').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
