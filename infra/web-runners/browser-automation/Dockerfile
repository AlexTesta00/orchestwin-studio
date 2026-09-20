FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e

USER root
WORKDIR /opt/orchestwin/browser-automation
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY package.json ./package.json
# Do not invent npm integrity values. Resolve a real lock, install from it,
# and return that exact lock in the probe evidence. No lifecycle scripts.
RUN npm install --package-lock-only --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org \
    && npm ci --ignore-scripts --omit=optional --no-audit --no-fund --registry=https://registry.npmjs.org \
    && npm cache clean --force
COPY fixture.html probe.cjs ./
USER 65532:65532
ENV HOME=/tmp
ENTRYPOINT ["node", "/opt/orchestwin/browser-automation/probe.cjs"]
CMD []
