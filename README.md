# OrchesTwin Studio

OrchesTwin Studio is a human-governed multi-agent platform for operationalizing an end-to-end Agentic User-Centered Design workflow, from project intake to executable software evaluation.

This repository is currently in its foundation sprint. The initial technical baseline provides repository automation, test execution, build verification, dependency updates, and semantic releases. Application behavior will be introduced in later commits.

## Toolchain baseline

- Python 3.12 or newer;
- Node.js 22.14 or newer;
- Node.js 26.6.0 selected through `.nvmrc`;
- npm;
- Git and GitHub Actions.

## Local setup

From the repository root:

```bash
nvm install
nvm use

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

npm install