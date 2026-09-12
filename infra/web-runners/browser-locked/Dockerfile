FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e

USER root
WORKDIR /opt/orchestwin/browser-automation
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY infra/web-runners/browser-locked/package.json ./package.json
COPY infra/web-runners/browser-locked/package-lock.json ./package-lock.json
# Lock observed by the C63 infrastructure probe; dependency provenance, not Level D.
# SHA-256: 1b8e8ea4e50b4baa58a8fdf42882894a43e1f563d415e72f5441bb1179bff294
RUN npm ci --ignore-scripts --omit=optional --no-audit --no-fund \
    --registry=https://registry.npmjs.org \
    && npm cache clean --force
USER 65532:65532
ENV HOME=/tmp
ENTRYPOINT []
CMD ["node", "--version"]
