#!/usr/bin/env bash
set -euo pipefail
ROOT="${ORCHESTWIN_CLOUD_ROOT:-/workspace/orchestwin-studio}"
ENVIRONMENT="$ROOT/environments/training"
MODEL="${ORCHESTWIN_CLOUD_MODEL:-Qwen/Qwen3-Coder-30B-A3B-Instruct}"
REVISION="${ORCHESTWIN_CLOUD_REVISION:-b2cff646eb4bb1d68355c01b18ae02e7cf42d120}"
export HF_HOME="${HF_HOME:-/workspace/hf-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/orchestwin/uv-python}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/opt/orchestwin/uv-cache}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/opt/orchestwin/training-venv}"
export UV_LINK_MODE=copy
mkdir -p "$HF_HOME" "$UV_PYTHON_INSTALL_DIR" "$UV_CACHE_DIR"
test -f "$ENVIRONMENT/uv.lock"
UV_VERSION="${ORCHESTWIN_CLOUD_UV:-0.12.3}"
export PATH="/opt/orchestwin/bin:$PATH"
if ! command -v uv >/dev/null || [ "$(uv --version | cut -d" " -f2)" != "$UV_VERSION" ]; then
  mkdir -p /opt/orchestwin/bin
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR=/opt/orchestwin/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
uv --version
if ! command -v gcc >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends build-essential
fi
PYTHON_VERSION="${ORCHESTWIN_CLOUD_PYTHON:-3.13.15}"
PYTHON="$UV_PROJECT_ENVIRONMENT/bin/python"
if [ -x "$PYTHON" ] && [ "$("$PYTHON" -c "import platform; print(platform.python_version())")" != "$PYTHON_VERSION" ]; then
  rm -rf "$UV_PROJECT_ENVIRONMENT"
fi
uv python install --managed-python "$PYTHON_VERSION"
uv sync --project "$ENVIRONMENT" --frozen --no-dev --managed-python --python "$PYTHON_VERSION"
uv pip install --python "$PYTHON" --no-deps -r "$ENVIRONMENT/requirements-proposals.txt"
env -u HF_HUB_OFFLINE -u TRANSFORMERS_OFFLINE "$PYTHON" - "$MODEL" "$REVISION" <<'PY'
import sys
from huggingface_hub import snapshot_download
path = snapshot_download(
    sys.argv[1],
    revision=sys.argv[2],
    allow_patterns=["*.json", "*.safetensors", "*.jinja", "*.txt", "*.py"],
)
print(path)
PY
"$PYTHON" -c "import llguidance, unsloth, torch; print(llguidance.__version__, torch.__version__)"
VLLM_VERSION="${ORCHESTWIN_CLOUD_VLLM:-0.29.0}"
VLLM_ENVIRONMENT="${ORCHESTWIN_CLOUD_VLLM_ENVIRONMENT:-/opt/orchestwin/vllm-venv}"
VLLM_PYTHON="$VLLM_ENVIRONMENT/bin/python"
if [ ! -x "$VLLM_PYTHON" ] || [ "$("$VLLM_PYTHON" -c "import importlib.metadata as m; print(m.version('vllm'))" 2>/dev/null)" != "$VLLM_VERSION" ]; then
  rm -rf "$VLLM_ENVIRONMENT"
  uv venv --managed-python --python 3.12 "$VLLM_ENVIRONMENT"
  uv pip install --python "$VLLM_PYTHON" "vllm==$VLLM_VERSION"
fi
"$VLLM_PYTHON" -c "import importlib.metadata as m; print('vllm', m.version('vllm'), 'llguidance', m.version('llguidance'), 'torch', m.version('torch'))"
echo BOOTSTRAP_COMPLETE
