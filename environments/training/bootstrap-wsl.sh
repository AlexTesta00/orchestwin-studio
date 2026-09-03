#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REQUIRED_PYTHON_MINOR="3.13"
readonly REQUIRED_UV_VERSION="0.12.3"
readonly NETWORK_GATE="ORCHESTWIN_TRAINING_ALLOW_NETWORK"
readonly SYSTEM_PACKAGE_HINT="build-essential"
readonly REQUIRED_BUILD_COMMANDS=("gcc" "g++" "make")

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Training environment requires Linux under WSL2." >&2
  exit 1
fi

if [[ -z "${WSL_DISTRO_NAME:-}" ]] && ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "Training environment requires WSL2; no WSL marker was observed." >&2
  exit 1
fi

if ! command -v python3.13 >/dev/null 2>&1; then
  echo "python3.13 is required and was not found on PATH." >&2
  exit 1
fi

python_version="$(
  python3.13 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
if [[ "${python_version}" != "${REQUIRED_PYTHON_MINOR}" ]]; then
  echo "Expected Python ${REQUIRED_PYTHON_MINOR}, observed ${python_version}." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv ${REQUIRED_UV_VERSION} is required and was not found on PATH." >&2
  exit 1
fi

uv_version="$(uv --version | awk '{print $2}')"
if [[ "${uv_version}" != "${REQUIRED_UV_VERSION}" ]]; then
  echo "Expected uv ${REQUIRED_UV_VERSION}, observed ${uv_version}." >&2
  exit 1
fi

for required_command in "${REQUIRED_BUILD_COMMANDS[@]}"; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "${required_command} is required for Triton compilation and was not found on PATH." >&2
    echo           "On Ubuntu, install it with: sudo apt install --no-install-recommends ${SYSTEM_PACKAGE_HINT}"           >&2
    exit 1
  fi
done

python_header="$(
  python3.13 - <<'PY'
import sysconfig
from pathlib import Path

print(Path(sysconfig.get_paths()["include"]) / "Python.h")
PY
)"
if [[ ! -f "${python_header}" ]]; then
  echo "Python development header was not found at ${python_header}." >&2
  exit 1
fi

cd "${SCRIPT_DIR}"

if [[ "${!NETWORK_GATE:-0}" != "1" ]]; then
  cat <<EOF
Training environment contract verified without network access.
Triton build toolchain verified with $(command -v gcc), $(command -v g++), and $(command -v make).
No dependency resolution, package download, model download, or training was executed.
To authorize dependency resolution explicitly, run:
  ${NETWORK_GATE}=1 ./bootstrap-wsl.sh
EOF
  exit 0
fi

if [[ -f uv.lock ]]; then
  uv lock --check --python "${REQUIRED_PYTHON_MINOR}"
else
  uv lock --python "${REQUIRED_PYTHON_MINOR}"
fi

uv sync --frozen --no-dev --python "${REQUIRED_PYTHON_MINOR}"
mkdir -p artifacts
uv run --frozen python capture_environment.py --output artifacts/environment.json

cat <<'EOF'
The isolated training environment is synchronized.
Review uv.lock and artifacts/environment.json before any smoke or full training run.
This bootstrap did not download model weights and did not start training.
EOF
