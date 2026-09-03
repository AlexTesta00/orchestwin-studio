# OrchesTwin isolated training environment

This directory defines the Linux/WSL2-only dependency boundary for the Sprint 11 User Twin
evaluator model spike and Unsloth QLoRA work. It is intentionally separate from the root
Python environment and the default cross-platform CI matrix.

## Training toolchain contract

| Component | Required value |
|---|---|
| Python minor | `3.13` |
| `uv` | `0.12.3` |
| `unsloth` | `2026.8.22` |
| `unsloth-zoo` | `2026.8.16` |
| `trl` | `0.24.0` |
| Triton host toolchain | Ubuntu `build-essential` with `gcc`, `g++`, `make`, and `Python.h` |

The Python packages above are exact direct inputs. Their complete transitive resolution is
represented by the committed `uv.lock`. The system compiler is outside the Python lock, so its
resolved paths and version banners are captured in `artifacts/environment.json` for each model
spike or training run.

## Boundary and claims

- Core backend and frontend tests do not import this environment.
- CUDA, a GPU, model weights, and live model access are not required by default CI.
- This directory contains no credentials, model weights, adapters, checkpoints, or generated
  datasets.
- Dependency synchronization is not permission to download a base model or run training.
- A successful setup does not select a model, approve `S11-G2`, or prove QLoRA feasibility.
- Observed resource and adapter evidence must be captured separately and approved through the
  Sprint 11 gates.

## Prerequisites

Use WSL2 with:

1. a Linux distribution;
2. `python3.13` available on `PATH`;
3. `uv 0.12.3` available on `PATH`;
4. Ubuntu's `build-essential` package;
5. an NVIDIA Windows driver that exposes the GPU inside WSL2;
6. `nvidia-smi` available in the WSL2 distribution.

Install the host build toolchain explicitly; the repository bootstrap never invokes `sudo` or
changes operating-system packages:

```bash
sudo apt update
sudo apt install -y --no-install-recommends build-essential
```

Verify the complete local prerequisite set:

```bash
python3.13 --version
uv --version
command -v gcc
command -v g++
command -v make
gcc --version | head -n 1
g++ --version | head -n 1
make --version | head -n 1
nvidia-smi
```

The bootstrap rejects a different Python minor, a different `uv` version, non-Linux execution,
Linux execution without a WSL marker, a missing build command, or a missing `Python.h` header.

## Contract-only verification without network

```bash
cd environments/training
./bootstrap-wsl.sh
```

Without explicit authorization, the script validates WSL2, Python, `uv`, the Triton build
toolchain, and the Python development header, then exits before resolution or download. It does
not install packages, download model weights, or start training.

## First authorized dependency resolution

```bash
cd environments/training
ORCHESTWIN_TRAINING_ALLOW_NETWORK=1 ./bootstrap-wsl.sh
```

The authorized path performs these bounded steps:

1. verify that the committed `uv.lock` is current;
2. synchronize `.venv` from the frozen lock;
3. capture `artifacts/environment.json` using only fixed local probes.

It still does not download model weights or start a training run.

After the command, review:

```bash
sha256sum uv.lock
python3.13 -m json.tool artifacts/environment.json
```

The environment record contains the exact lock digest, GPU and driver evidence, CUDA-visible
version, package versions, compiler paths, compiler version banners, build-tool version, and
Python-header path. A record whose `complete` field is `false` is evidence of missing
observations, not a passing environment.

## Reproduction from the accepted lock

```bash
cd environments/training
uv lock --check --python 3.13
uv sync --frozen --no-dev --python 3.13
uv run --frozen python capture_environment.py --output artifacts/environment.json
```

Do not use `uv lock --upgrade` during a frozen experiment. A dependency update requires a new
lock digest, a new environment record, and a documented reason.

## Artifact policy

The local `.gitignore` excludes virtual environments, generated Unsloth compilation caches,
runtime artifacts, checkpoints, and common model-weight formats. A later training adapter must
store large outputs in the content-addressed artifact store rather than Git.

The committed `uv.lock` is the accepted Python dependency resolution for this environment.
Regenerating or upgrading it requires a separate reviewed candidate and a new environment
evidence digest.
