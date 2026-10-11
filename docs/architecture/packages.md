# Packages

The backend is a single Python package, `orchestwin`, in `src/orchestwin/`. It provides the three installed commands: `orchestwin-api` for the API, `orchestwin-migrate` for the migrations, and `ut`. Unless stated otherwise, a path starts from `src/orchestwin/`, and the numbers count the files tracked by Git at commit `a850cd6`.

## The Python backend

The split follows responsibilities. The domain packages (`projects`, `twins`, `agents`, `artifacts`, `workflow`, `identity`) describe steps, versions and rules without knowing anything about HTTP. None of them imports FastAPI, and the only module that takes anything from `api` is `artifacts/workflow_inputs_runtime.py`, for a response type. Around them, the `api` package composes the services and publishes the routes, while `models` talks to the providers. The `knowledge` package turns the approved versions into the knowledge folder, `persistence` holds the database engine and the migrations, and `cli` is the `ut` command.

| Package | Files | Lines | Responsibility | Main modules |
|---|---|---|---|---|
| `cli` | 158 | 42,888 | the `ut` command: commands, flows, HTTP client, browser, MCP server, texts in Italian and English | `main.py`, `client.py`, `commands/design.py`, `flows/push.py`, `mcp/tools.py` |
| `artifacts` | 51 | 23,524 | design: alternatives, visual directions, generated mockups and their validators, style distance, critique, revisions, the "Why?" and traceability | `generated_mockups.py`, `visual_directions.py`, `design_distance.py`, `design_critique.py`, `traceability.py` |
| `projects` | 62 | 21,692 | project, brief and dialogue, Definition, sections, development (commits, acceptance tests, alignment), twin learning | `sections.py`, `sections_service.py`, `requirements_application.py`, `code_changes.py`, `knowledge_alignment.py` |
| `api` | 56 | 21,319 | 42 FastAPI routers, service composition, authentication, generation jobs | `app.py`, `services.py`, `auth.py`, `generation_jobs.py`, `requirements.py`, `design.py` |
| `models` | 58 | 21,064 | provider adapters, tasks and prompts, response schemas, generation evidence and budgets | `claude_code_cli.py`, `proposal_generation.py`, `real_runtime.py`, `model_proposals.py` |
| `knowledge` | 58 | 15,277 | knowledge folder: documents, schemas, Mermaid diagrams, CSV tables, archive, import | `folder.py`, `schema.py` with the 16 modules of `schema_models/`, `diagrams.py`, `state_documents.py`, `tables.py` |
| `persistence` | 85 | 13,037 | engine, configuration, base unit of work, Alembic with the 76 migrations (12,622 lines) | `migrations/env.py`, `unit_of_work.py`, `migrate.py` |
| `twins` | 26 | 8,930 | persona, User Twin, epistemics, lifecycle, archetypes, conversations, revisions | `user_twins.py`, `application.py`, `epistemics.py`, `revisions.py` |
| `agents` | 15 | 5,174 | agent catalogue, perspectives, team proposal, Perspectives gate | `catalog.py`, `perspectives.py`, `selection_rules.py`, `team_gate.py` |
| `evaluation` | 13 | 3,196 | twin review and critique, local evaluator | `proposer_evaluator.py`, `critique_evaluator.py`, `twin_review.py` |
| `workflow` | 7 | 1,551 | gate state machine and the shared protocol of the five gates | `gates.py`, `gate_flow.py` |
| `identity` | 11 | 1,522 | accounts, passwords, tokens, sessions | `application.py`, `tokens.py`, `sessions.py` |
| top-level modules | 7 | 2,624 | the "Why?", workflow inputs, activity log, validation, configuration | `why_builder.py`, `workflow_inputs.py`, `activity.py`, `validation.py`, `why.py`, `config.py` |
| total | 607 | 181,798 | | |

The `models` package also holds paths that the Studio does not use when it runs with `claude --print`. These are the adapters for the Anthropic API and for OpenAI-compatible services, and the deterministic `fake_*` generators, which answer when the Studio runs without a model. The model contracts are in [Providers, model contracts and guard](models.md).

## Who imports whom

The table counts the absolute `import` statements that reach into another package, including those inside functions, through a syntax-tree analysis that leaves the migrations out. The first number counts the statements, the one in brackets the files that contain them.

| Package | Imports mostly from |
|---|---|
| `api` | `projects` 109 (24), `artifacts` 63 (17), `models` 62 (20), `twins` 36 (14), `knowledge` 27 (9) |
| `knowledge` | `artifacts` 56 (18), `projects` 56 (23), `twins` 39 (16), `agents` 19 (9), `workflow` 15 (13) |
| `models` | `projects` 50 (27), `artifacts` 39 (13), `twins` 29 (18), `agents` 13 (10), `knowledge` 6 (6) |
| `artifacts` | `projects` 47 (32), `twins` 10 (7), `evaluation` 10 (3), `workflow` 7 (3), `models` 5 (5) |
| `projects` | `artifacts` 29 (7), `twins` 28 (15), `workflow` 24 (14), `models` 16 (7), `knowledge` 9 (8) |
| `twins` | `projects` 13 (8), `workflow` 7 (4), `models` 5 (3), `agents` 3 (3) |
| `agents` | `projects` 13 (5), `workflow` 11 (6), `models` 8 (7), `persistence` 3 (3) |
| `evaluation` | `models` 21 (7), `projects` 5 (5), `artifacts` 2 (2), `twins` 1 (1) |
| `cli` | top-level modules 16 (10), `knowledge` 11 (4) |
| `identity` | `persistence` 2 (2) |
| `workflow` | `projects` 2 (1), `persistence` 1 (1) |

No import in `cli` points to `api`, `models` or `persistence`, and outside `orchestwin` the package uses only the standard library. This is a rule of the README written into the code: `ut` never calls the model, it talks to the Studio. The `knowledge` package enters `ut` only inside the functions that need it, such as the ones that verify the knowledge folder.

Among the domain packages the dependencies run both ways. `projects` imports from `artifacts`, `twins` and `models`, and all three import from `projects`. Three dependencies go against the grain, and each is isolated: `artifacts` towards `api`, at the point already mentioned, and `knowledge` towards `cli`, inside a function of `knowledge/validation_records.py`. The third runs from `workflow` to `projects`, in `workflow/persistence/repositories.py`, which uses the models and the ownership query of `projects.persistence`; apart from that, `workflow` depends on no domain package. The `persistence` package also looks outside itself at a single point, `migrations/env.py`, where it registers the ORM models and the evidence tables for Alembic.

## The frontend

The web app is a Vue 3.5 application built with Vite 8, with Pinia 4 for state, vue-router 5, vue-i18n 11, Tailwind 4 and TypeScript 6. The code is in `frontend/src/`: 242 `.ts` and `.vue` files for 70,358 lines, plus 164 `*.spec.ts` test files.

| Folder | Files | Lines | What it contains |
|---|---|---|---|
| `components/` | 121 | 45,427 | the step components (`ProjectRequirementsFlow.vue`, `ProjectDesignFlow.vue` and the others), the 15 base `Ui*` components, 23 `*Copy.ts` text modules |
| `stores/` | 30 | 8,958 | the Pinia stores per step and per feature, with the shared helpers `storeErrors.ts` and `jobWatch.ts` |
| `api/` | 37 | 6,260 | one client per area of the API, the shared helpers in `http.ts`, `generationJobs.ts` for long generations |
| `types/` | 25 | 3,700 | the TypeScript types of the API contracts |
| `views/` | 8 | 3,223 | six views (home, login, registration, mode choice, projects, project) and two text modules |
| `test/` | 9 | 1,426 | test data and helpers for the specs, including the axe check |
| `i18n/` | 3 | 745 | `createAppI18n` and the shared interface texts in `locales/it.ts` and `locales/en.ts` |
| `composables/` | 4 | 217 | `useAuthorizedRequest`, `useGateState`, `useIntlFormats`, `useStepTargets` |
| `router/` | 2 | 140 | the six routes and the login guard |

A component keeps its texts in a `*Copy.ts` module next to it, with an `it` branch and an `en` branch. There are 25 of these modules, 23 among the components and 2 among the views. The shared stylesheet is `styles/tailwind.css`.

## The command line

The `ut` command is the `cli` package. Commands sit in small modules, one per command, the longer logic lives in the flows, and all the texts are kept in one place, in Italian and English.

| Folder | Files | Lines | What it contains |
|---|---|---|---|
| `flows/` | 43 | 15,076 | the long flows: design, Definition, push, tests, verification, alignment, code |
| `messages/` | 27 | 9,318 | the texts of `ut` in Italian and English |
| `commands/` | 23 | 5,389 | one module per command, 22 plus `__init__.py` |
| `api/` | 24 | 3,537 | the calls to the Studio's routes, grouped by area, with `replies.py` to read the responses |
| `browser/` | 10 | 2,944 | the Chrome and Firefox drivers with CDP and BiDi, over a WebSocket written with the standard library |
| `mcp/` | 8 | 2,754 | the MCP server `orchestwin-twins` on stdio, its tools and the configurations for the editors |
| `views/` | 7 | 765 | the text views of the "Why?", persona, directions, validation |
| root | 16 | 3,105 | `main.py`, `client.py`, `session.py`, `jobs.py`, `project.py`, `folder.py`, `costs.py`, `shapes.py` and the others |

## The extension and the scripts

The Visual Studio Code extension lives in `editors/vscode`: 14 JavaScript files for 5,952 lines and 13 test files, run with `node --test` without opening the editor. It is described in [The Visual Studio Code extension](vscode-extension.md).

`scripts/` holds ten files.

| Script | What it does |
|---|---|
| `start-studio.ps1`, `stop-studio.ps1` | start and stop the native Studio on Windows |
| `studio_runtime.py` | prepares the environment and runs the migrations, the API or the model check |
| `check_real_model_runtime.py` | checks the providers and the database of the composed API, without inference |
| `model-providers.claude-code.example.json` | the example providers file for `claude --print` |
| `model-providers.example.json` | the same file for the Anthropic API, with a key and the prices |
| `build_backend.py` | builds and checks the distributable backend package |
| `smoke_compose.py` | builds and tests the all-Docker variant (`npm run test:compose`) |
| `cloud_proposer.py` | creates, starts and stops a remote pod and opens the tunnel to it |
| `model_database_bridge.py` | TCP bridge between the native API and the database's private network, started by `compose.models.yaml` |

The last two date from September: the bridge from 13 September 2026, when the Studio used locally served models, and the remote pod control from 21 September 2026. Generations with `claude --print` use neither. Sprint 46 listed the bridge and the non-hosted branch of `start-studio.ps1` among the leftovers it did not remove.

## The sprint 46 refactor

Between 10 and 11 October 2026, sprint 46 reworked the code without changing its behaviour. The existing tests stayed as they were, except those of the deleted package and the expected values of two leftovers from sprint 45. The outputs are identical byte for byte, and the hash of the OpenAPI document was compared after every unit of work on the API and found equal. The 22 commits touched 871 files and took the backend from 215,104 to 181,794 lines. About 24,500 of the 33,310 lines removed belonged to the `training` package, deleted at the author's decision.

The rest comes from helpers written once in place of many copies. The gate protocol in `workflow/gate_flow.py` brought the five services from 3,608 to 2,613 lines, `persistence/unit_of_work.py` gives the SQLAlchemy units of work a shared base, and the "owned project" query in `projects/persistence/owned.py` replaces 15 copies. The same happened with the readers of the twins' stored values (`twins/record_values.py`), with `refusals.py`, `dependencies.py`, `runtime_access.py` and `generation_evidence.py` in the API, with `shapes.py` and `api/replies.py` in `ut`, and with `api/http.ts` in the web app. Other modules were split behind the same facade: `knowledge/documents.py` shrank to 72 lines with seven per-step modules, `knowledge/schema.py` to 587 with sixteen modules. The fake Studio used by the `ut` tests, a single file of 15,215 lines, became a package of 28 modules. The frontend went from 72,575 to 70,358 lines, with about 6,000 lines of texts moved into the `*Copy.ts` modules. The story of the sprint is in [The last sprints](../journey/last-sprints.md).
