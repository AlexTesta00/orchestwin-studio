# Requirements and installation

The whole Studio runs on your computer. A Python API keeps the projects in a PostgreSQL database inside Docker, a Vue web interface lets you work from the browser, and the `ut` command brings the same steps to the terminal. Generations go through the Claude Code command line, which is tied to your subscription, so there is no key to keep safe.

Windows 11 is the reference system, because the scripts that start and stop the Studio are written in PowerShell. The API, the web interface and `ut` also run on macOS and Linux, and the CI tests them in every run on the `ubuntu-24.04`, `macos-14` and `windows-2025` runners.

## What you need

Besides PowerShell you need Docker Desktop, which keeps the database running. For the rest, versions matter.

| Program | Version | Needed for |
|---|---|---|
| Python | 3.12 or later (3.13 locally, 3.14 in the CI) | the API, the migrations and `ut` |
| Node | 26.6.0, pinned in `.nvmrc` | building and serving the web interface |
| PostgreSQL | 18, image `postgres:18-alpine` | the projects and their versions |
| Claude Code | 2.1.280 or later, with a subscription | generating with Claude Opus 5.5 |

Without Claude Code the Studio can run with deterministic generators in place of the model. You can create projects and go through the steps, but you cannot choose or approve a design, because that needs the model. [Without a model](studio.md#without-a-model) describes this setup.

## Cloning and installing

Clone the repository and move into its folder.

```powershell
git clone https://github.com/AlexTesta00/orchestwin-studio.git
cd orchestwin-studio
```

Create the virtual environment and activate it. The README uses Python 3.13, but `pyproject.toml` accepts any version from 3.12 up.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

Then install the root tools, the backend and the frontend.

```powershell
npm ci
npm run install:python
npm run install:frontend
```

The first command brings in the tools that check commits and prepare releases. The second installs the `orchestwin-studio` package in editable mode, with its development dependencies, and creates three commands in the virtual environment: `ut`, `orchestwin-api` to start the API and `orchestwin-migrate` for the migrations. The third installs the web dependencies in `frontend`.

## The compose.env file

The database and the API have to share the same credentials, and credentials must not end up in Git. That is why they live in `compose.env` at the root, a file excluded by `.gitignore` and read by both Docker Compose and `scripts/studio_runtime.py`. Write it like this, with your own values in place of the placeholders.

```text
ORCHESTWIN_API_PORT=8000
ORCHESTWIN_FRONTEND_PORT=8080
ORCHESTWIN_POSTGRES_DB=orchestwin
ORCHESTWIN_POSTGRES_USER=orchestwin
ORCHESTWIN_POSTGRES_PASSWORD=<local password>
ORCHESTWIN_AUTH_JWT_SECRET=<secret of at least 32 characters>
```

The ports, the database name and the user are the defaults from `compose.yaml`. The secret signs the access tokens and needs at least 32 characters, otherwise the API does not start. If the password or the secret is missing, `studio_runtime.py` stops straight away with "Missing local credential configuration: ORCHESTWIN_POSTGRES_PASSWORD", or with the name of the other variable.

The `var/` folder is kept out of Git as well. In `var/studio` you will put the providers file and the local settings, and the start script will write its logs and sessions there.

## The repository folders

| Folder | What it contains |
|---|---|
| `src/orchestwin` | the backend, with the FastAPI API, the model providers and the `ut` command (`cli`) |
| `src/test` | the Python tests and the integration tests on PostgreSQL |
| `frontend` | the Vue 3 application, in Italian and English |
| `editors/vscode` | the Visual Studio Code extension |
| `scripts` | start and stop, sample providers files, the model check, the Docker smoke test |
| `docs` | this documentation and the brand |
| `.github/workflows` | the CI/CD |
| `environments/training` | only a `.gitignore` |

At the root you find `pyproject.toml`, `package.json`, `compose.yaml` with its variants, the API's `Dockerfile`, `alembic.ini` and `mkdocs.yml`.

The last row of the table is a leftover. The folder used to hold the environment of the training package, which was removed on 11 October 2026 with commit `66f8988`. The `.gitignore` that stayed behind keeps the local artifacts of that work out of Git. [The journey](../journey/the-cut.md) tells why the training was abandoned.

## Where to go from here

First you start the database and apply the migrations, as [Starting and stopping the Studio](studio.md) explains. Then you prepare Claude Code and the providers file with [Generating with claude --print](generation.md). Before the first start, choose between local mode and accounts in [Local mode and accounts](local-mode.md). For the terminal there is the [`ut` reference](../ut/index.md).
