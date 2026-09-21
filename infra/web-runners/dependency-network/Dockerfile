FROM docker.io/library/node:26.7.0-bookworm-slim@sha256:4db36457f406501e6f608802e5da617e5fbd0e80b75901b6a09de1ae5a667d32

COPY --chown=65532:65532 proxy.mjs /opt/orchestwin/dependency-proxy.mjs

USER 65532:65532
WORKDIR /tmp
ENTRYPOINT ["node", "/opt/orchestwin/dependency-proxy.mjs"]
