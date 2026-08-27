# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

ARG NODE_IMAGE=node:26.6.0-bookworm-slim@sha256:81502e860176e63695d769d3d1a2d3a403abc1c27c6a02169b765f3e43b60ede
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.31.4-alpine-slim@sha256:021f32b23e2bfc8610ccdec499b709625dcee1369884d7a51bd8a23a3accb301

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