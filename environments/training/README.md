# OrchesTwin isolated training environment

This directory defines the Linux/WSL2-only dependency boundary for the Sprint 11 User Twin
evaluator model spike and Unsloth QLoRA work. It is intentionally separate from the root
Python environment and the default cross-platform CI matrix.

## Direct toolchain pins

| Component | Pin |
|---|---|
| Python minor | `3.13` |
| `uv` | `0.12.3` |
| `unsloth` | `2026.8.22` |
| `unsloth-zoo` | `2026.8.16` |
| `trl` | `0.24.0` |

The three Python packages above are exact direct inputs. The complete transitive resolution is
represented by `uv.lock`, which must be generated and checked on the authorized WSL2 target.
No transitive package version is invented in source when the resolver has not observed it.

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
4. an NVIDIA Windows driver that exposes the GPU inside WSL2;
5. `nvidia-smi` available in the WSL2 distribution.

Install the exact `uv` version through an organization-approved method, then verify:

```bash
python3.13 --version
uv --version
nvidia-smi
```

The bootstrap script rejects a different Python minor, a different `uv` version, non-Linux
execution, and Linux execution without a WSL marker.

## Contract-only verification without network

```bash
cd environments/training
./bootstrap-wsl.sh
```

Without explicit authorization, the script validates the local toolchain and exits before
resolution or download. It does not install packages, download model weights, or start
training.

## First authorized dependency resolution

```bash
cd environments/training
ORCHESTWIN_TRAINING_ALLOW_NETWORK=1 ./bootstrap-wsl.sh
```

The authorized path performs these bounded steps:

1. create `uv.lock` when it is absent, otherwise verify that it is current;
2. synchronize `.venv` from the frozen lock;
3. capture `artifacts/environment.json` using only fixed local probes.

It still does not download model weights or start a training run.

After the command, review:

```bash
sha256sum uv.lock
cat artifacts/environment.json | python3.13 -m json.tool
```

Retain the exact `uv.lock` digest and environment-record digest with the model-spike or
training-run artifact. A record whose `complete` field is `false` is evidence of missing
observations, not a passing environment.

## Reproduction from an accepted lock

With the reviewed `uv.lock` present:

```bash
cd environments/training
uv lock --check --python 3.13
uv sync --frozen --no-dev --python 3.13
uv run --frozen python capture_environment.py --output artifacts/environment.json
```

Do not use `uv lock --upgrade` during a frozen experiment. A dependency update requires a new
lock digest, a new environment record, and a documented reason.

## Artifact policy

The local `.gitignore` excludes virtual environments, caches, runtime artifacts, checkpoints,
and common model-weight formats. A later training adapter must store large outputs in the
content-addressed artifact store rather than Git.

`uv.lock` is deliberately not ignored. Once it has been generated and reviewed on the actual
WSL2 target, its treatment must be explicit: either commit the reviewed lock in a follow-up
candidate or preserve it as an immutable artifact referenced by digest. Do not silently
regenerate it during a frozen benchmark or training run.
