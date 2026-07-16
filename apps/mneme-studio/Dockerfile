# mneme-studio 生产镜像（多阶段 standalone，参考 mneme-web）。
# @helios/blocks 走 vendor tarball（file:vendor/*.tgz），build context 内自足。

# 1) deps
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
COPY vendor ./vendor
RUN npm install --no-audit --no-fund

# 2) build（standalone 产物）
FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
# 同源：前端经 /mcp 调用留在 sxueji.com 本 host
ENV NEXT_PUBLIC_API_BASE=""
RUN npm run build

# 3) run
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3001
CMD ["node", "server.js"]
