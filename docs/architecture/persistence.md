# Persistence and migrations

The Studio keeps in PostgreSQL everything it produces and everything the owner decides. One rule shapes the schema. A gate approves an exact artifact, by identifier, version number and SHA-256 fingerprint (`workflow/gates.py:84-102`), and that reference holds only if the row it points to never changes again. That is why versions are numbered and immutable, and why many tables accept inserts and nothing else.

## Engine and sessions

The database is PostgreSQL 18 in a Docker container (`compose.yaml:5`). The API reaches it asynchronously with SQLAlchemy 2.0 through psycopg 3 (`pyproject.toml:13-23`), and it accepts only `postgresql+psycopg` addresses read from the `ORCHESTWIN_DATABASE_*` variables (`persistence/config.py:12-51`). Sessions are created without autoflush and without expiring objects on commit (`persistence/database.py:29-51`).

Tables are declared in two ways that live side by side. Nine are ORM classes on the `OrmBase` base, which gives regular names to indexes, constraints and keys (`persistence/orm.py:10-24`). The others are declared with `sa.table(...)` in the module that uses them and stay out of the shared metadata, except the three generation evidence tables. The Alembic environment imports eight ORM classes and those three tables (`persistence/migrations/env.py:14-58`), so the complete schema, with its constraints and triggers, exists only in the migration files. Why there are two ways is not recorded.

## Units of work and repositories

Versions of the brief, Perspectives, twins, Definition and design are written inside a unit of work. Since sprint 46 the shared part lives in `SqlAlchemyUnitOfWork` (`persistence/unit_of_work.py:9-57`). On entry it opens a session and a transaction and binds the repositories with `_bind`; on exit it commits, or rolls back if an exception came out. Six units in `identity`, `projects` and `agents` inherit from it. Twins, Definition and design have "Managed" units that always close the session and carry the links to the generation evidence with them (`twins/runtime.py:48-83`, `projects/requirements_runtime.py:58-101`, `projects/design_runtime.py:52-86`), so a generated version and its link to the generation enter the same transaction. Other modules, such as the development, critique and twin discussion routes, open a transaction on their own with `session.begin()`.

Almost every access starts with the same question. Does the project exist, does it belong to the caller, and is it not archived? Before the refactor the query that answers it existed in 15 copies. Now there is one, `owned_project_query` (`projects/persistence/owned.py:11-16`), imported by thirteen modules; the sprint 46 measurements show the same compiled SQL in 36 statements, before and after. `OwnedProjectRepository` builds on it. On writes it locks the project row with `FOR UPDATE` (`projects/persistence/owned.py:19-31`), and it is the base of the repositories for acceptance tests, code changes, alignment and twin learning. Both changes are in commits 5bb11fe and e7f6049 of 11 October 2026.

## Tables by domain

After 0075 the schema holds 57 application tables, plus `alembic_version`.

| Domain | Tables | Declared in |
|---|---|---|
| Identity | `users`, `user_guidance_choices`, `auth_sessions` | `identity/persistence/` |
| Project and brief | `projects`, `project_brief_versions`, `brief_assumptions`, `brief_dialogues`, `brief_dialogue_turns`, `project_usage_events`, `project_imports` | `projects/persistence/`, `knowledge/` |
| Gates | `human_gates`, `human_gate_events` | `workflow/persistence/` |
| Perspectives | `team_proposals` | `agents/persistence/` |
| User Twins | `persona_profile_versions`, `user_twin_profile_versions`, `user_modeling_snapshot_versions`, `user_twin_profile_diffs`, `twin_conversations`, `twin_conversation_turns`, `twin_updates`, `twin_learned_observations`, `research_evidence_versions`, `research_evidence_texts`, `research_evidence_changes` | `twins/`, `projects/persistence/` |
| Definition | `requirements_specification_versions`, `requirements_specification_diffs` | `projects/` |
| Design and evaluation | `design_package_versions`, `design_package_diffs`, `design_evaluation_runs`, `design_synthetic_findings`, `design_finding_validations`, `insight_applications`, `design_discussions`, `design_discussion_rounds`, `design_critique_sources`, `design_critique_shots`, `design_critique_runs` | `artifacts/`, `projects/persistence/` |
| Validation and owner input | `project_validation_hypotheses`, `project_validation_outcomes`, `project_workflow_decisions`, `project_provided_prototypes` | `artifacts/` |
| Dossier | `knowledge_package_versions`, with the zip archive | `knowledge/` |
| Development | `project_code_changes`, `code_change_reviews`, `code_tasks`, `acceptance_test_plans`, `acceptance_test_runs`, `acceptance_test_reviews`, `knowledge_alignment_runs`, `knowledge_alignment_proposals` | `projects/persistence/` |
| Generation evidence | `model_proposal_generations`, `model_proposal_generation_events`, `model_proposal_artifact_links` | `models/` |
| No code | `training_dataset_versions`, `training_dataset_quality_reports`, `training_runs`, `training_run_checkpoints` | no module |

## Rows that never change

A change produces version N+1 and the previous one stays. The database enforces this with `BEFORE UPDATE OR DELETE` triggers on the versions of brief, Perspectives, persona, twin, Definition and design, on gate events, on generation evidence and on twin conversations. The same holds for Dossiers, imports, validation, gaps and supplied prototypes, the usage journal and the mode choice. A gate row does change state, but every transition adds an event to `human_gate_events`, and that event then stays as it is. On the evidence tables, 0038 also forbids `TRUNCATE` and checks the order of the events.

The mode choice has the strictest rule. `user_guidance_choices` is keyed by `user_id`, so each account has a single choice, and its downgrade refuses with a `RuntimeError` if the table holds any rows (`0072_guidance_choice.py:13-37`). The same refusal protects text sources, validation, owner input and the usage journal in migrations 0068 to 0071.

## The 76 migrations

The migrations live in `src/orchestwin/persistence/migrations/versions/`: 76 files, from 0001 to 0075 plus 0005a. The chain is linear, with its head at `0075_design_critiques`, and every file has its downgrade. The dates are those of the commit that added each file, as `git log` reports them.

| Revisions | Date (2026) | What |
|---|---|---|
| 0001–0010 | 7–13 August | users and sessions, projects, brief, gates, Perspectives, persona and twins |
| 0011–0016 | 18–21 August | Definition, design, architecture and their gates |
| 0017–0029 | 25–31 August | existing code, sandbox, web and JVM sources and executions, workflow, evaluations, final review, export |
| 0030–0031 | 2–3 September | datasets and training runs |
| 0032–0051 | 9–23 September | browser inspections, web and JVM validations, generation evidence (0038), source generation, twin conversations (0048) |
| 0052 | 24 September | drops 25 tables and 21 functions |
| 0053–0056 | 24–25 September | source triggers removed, up to 8 twins, the brief dialogue in place of the clarification rounds |
| 0057–0059 | 26–27 September | twin evaluation rounds, decisions on findings, discussions between twins |
| 0060–0061 | 28 September | Dossier versions, project imports |
| 0062 | 29 September | API providers in the events |
| 0063–0066 | 29–30 September | commits and their reviews by the twins, acceptance tests, tasks, twin learning |
| 0067 | 1 October | the `CLAUDE_CODE_CLI` provider in the events |
| 0068–0069 | 2–3 October | the twins' text sources, validation hypotheses and outcomes |
| 0070 | 3 October | owner input that came with the guided and expert modes: gaps, supplied prototypes, `OWNER_PROVIDED` Perspectives |
| 0071–0072 | 4–5 October | usage journal, mode choice per account |
| 0073 | 6 October | `ut align` runs and proposals |
| 0074 | 8 October | drops the uniqueness of project and fingerprint in design versions |
| 0075 | 9 October | critique of an existing design |

On 24 September 2026, after the review with the supervisors that stopped the Studio at the design, 0052 dropped 25 tables, the 20 functions of their triggers, and the `retain_running_jvm_operation_gate` trigger with its function (`0052_design_first_scope.py:8-58,1194-1199`). They are the tables created by 0015 to 0037, apart from the training ones. The downgrade recreates schema, functions and triggers but not the data, which stayed in a backup taken beforehand. The `human_gates` constraint and the `HumanGateType` enumeration still list the types `ARCHITECTURE`, `HIGH_IMPACT_OPERATION` and `FINAL_OUTPUT`, which no module uses (`workflow/gates.py:14-24`).

The later migrations follow the work sprint by sprint. Migrations 0062 and 0067 create no tables. They widen `validate_model_proposal_event`, the function that checks the evidence events, first to the API providers and then to the Claude Code command line. Migration 0074 removes a constraint because a restore creates a new design version identical to an old one (`0074_design_version_restore.py:9-17`). The last one, 0075, takes in sources, PNG or JPEG screenshots up to 5 MB, and the runs of the critique of an existing design.

## The `training_*` tables

The four tables from 0030 and 0031 are still in the database, with their triggers. Migration 0052 left them alone, and sprint 46 deleted the `training` package (commit 66f8988, 11 October 2026) without a migration that drops them. No module reads them; only the tests of 0052 name them. They remain as a declared leftover, and the decision on whether to drop them is not recorded.

## Creating and applying a migration

The Studio applies migrations by itself. At startup `scripts/start-studio.ps1` runs `python scripts/studio_runtime.py migrate`, which brings the database to the head (`scripts/studio_runtime.py:64-68`); in the all-Docker variant the `migrations` service does it before the API starts (`compose.yaml:33-42`). By hand the command is `orchestwin-migrate` (`pyproject.toml:29`), with the address in `ORCHESTWIN_DATABASE_URL` or in the `.env` file.

```powershell
$env:ORCHESTWIN_DATABASE_URL = "postgresql+psycopg://orchestwin:<password>@127.0.0.1:15432/orchestwin"
```

```powershell
orchestwin-migrate upgrade head
```

```powershell
orchestwin-migrate current
```

The last command prints the revision the database is at. There is also `downgrade`, which requires an explicit revision and, from 0068 to 0072, stops when it meets data.

A new migration is a file `NNNN_name.py` in `versions/`, with `revision` equal to the file name and `down_revision` equal to the previous head. `alembic.ini` and `script.py.mako` provide a skeleton, though no file from 0039 onwards follows it. The names of tables, constraints, functions and triggers sit in constants, and upgrade and downgrade are written out in full, because Alembic's autogeneration would not see the tables declared with `sa.table`.
