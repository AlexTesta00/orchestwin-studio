# syntax=docker/dockerfile:1

ARG NODE_IMAGE=node:26.6.0-bookworm-slim
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.31.3-alpine-slim

FROM ${NODE_IMAGE} AS frontend-builder

ENV NODE_ENV=development

WORKDIR /workspace/frontend

COPY package.json package-lock.json .npmrc ./

RUN npm ci \
    --no-audit \
    --no-fund

COPY index.html \
     tsconfig.json \
     tsconfig.node.json \
     vite.config.ts \
     ./

COPY src ./src

RUN npm run build

FROM ${NGINX_IMAGE} AS runtime

LABEL org.opencontainers.image.title="OrchesTwin Studio Frontend" \
      org.opencontainers.image.description="Static Vue frontend for OrchesTwin Studio." \
      org.opencontainers.image.licenses="Apache-2.0"

COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=frontend-builder \
     /workspace/frontend/dist/ \
     /usr/share/nginx/html/

USER 101:101

EXPOSE 8080

HEALTHCHECK \
    --interval=10s \
    --timeout=3s \
    --start-period=5s \
    --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/healthz > /dev/null || exit 1

STOPSIGNAL SIGQUIT