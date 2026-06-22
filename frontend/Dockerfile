# ---------------------------------------------------------------
# Sahab frontend — multi-stage Docker build
# Stage 1: install deps
# Stage 2: build Next.js standalone output
# Stage 3: minimal runtime image
# ---------------------------------------------------------------

FROM node:20-alpine AS deps
WORKDIR /app

# Copy package files only for layer caching
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# ---------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Next.js standalone output is enabled in next.config.js
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------------------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy the standalone bundle produced by `output: "standalone"`
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
