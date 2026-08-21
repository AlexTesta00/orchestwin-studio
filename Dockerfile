ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

FROM ${PYTHON_IMAGE} AS wheel-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src/orchestwin ./src/orchestwin

RUN python -m pip wheel \
    --wheel-dir /wheelhouse \
    .

FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

LABEL org.opencontainers.image.title="OrchesTwin Studio API" \
      org.opencontainers.image.description="Human-governed OrchesTwin Studio FastAPI backend." \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ORCHESTWIN_ENVIRONMENT=production \
    ORCHESTWIN_DEBUG=false \
    ORCHESTWIN_LOG_LEVEL=INFO \
    ORCHESTWIN_API_PREFIX=/api/v1

RUN groupadd \
      --gid "${APP_GID}" \
      orchestwin \
    && useradd \
      --uid "${APP_UID}" \
      --gid "${APP_GID}" \
      --create-home \
      --shell /usr/sbin/nologin \
      orchestwin

COPY --from=wheel-builder /wheelhouse /wheelhouse

RUN python -m pip install \
      --no-index \
      --find-links=/wheelhouse \
      "orchestwin-studio==0.0.0" \
    && rm -rf /wheelhouse

WORKDIR /app

USER ${APP_UID}:${APP_GID}

EXPOSE 8000

HEALTHCHECK \
    --interval=10s \
    --timeout=3s \
    --start-period=5s \
    --retries=5 \
    CMD python -c "import os, urllib.request; prefix = os.getenv('ORCHESTWIN_API_PREFIX', '/api/v1').rstrip('/'); urllib.request.urlopen(f'http://127.0.0.1:8000{prefix}/health', timeout=2).read()"

STOPSIGNAL SIGTERM

ENTRYPOINT ["orchestwin-api"]

CMD ["--host", "0.0.0.0", "--port", "8000"]