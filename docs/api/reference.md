# Routes

This list is generated from [`openapi.json`](openapi.json), the schema that the API produces from the code at commit `a850cd6`. It holds 179 paths and 212 operations, split into the 24 groups of the OpenAPI document (its `tags`) and listed in the order they appear in the schema, which is also the order of Swagger UI. The summary is the operation's `summary` as the code writes it; when the code leaves it out, FastAPI derives it from the function name.

An operation requires authentication when the schema gives it the `HTTPBearer` security scheme. The access token goes in the `Authorization: Bearer` header, except in local mode, where the Studio recognises the owner's requests by itself ([The API](index.md) explains when).

Regenerating the schema and this page takes two sprint 47 scripts that live outside the repository, both run from the repository root with the virtual environment's Python: `esporta_openapi47.py` first, then `genera_riferimento_api47.py`.

## health

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/health` | Check service liveness |

This operation does not require authentication.

## authentication

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/auth/mode` | Return how the Studio admits its users |
| POST | `/api/v1/auth/register` | Register a local account |
| POST | `/api/v1/auth/login` | Log in with local credentials |
| POST | `/api/v1/auth/refresh` | Rotate the refresh session |
| POST | `/api/v1/auth/logout` | Log out the current refresh session |
| GET | `/api/v1/auth/me` | Return the current local account |
| POST | `/api/v1/auth/guidance-mode` | Choose the guidance mode once |

Only `GET /api/v1/auth/me` and `POST /api/v1/auth/guidance-mode` require authentication.

## projects

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects` | List Projects Endpoint |
| POST | `/api/v1/projects` | Create Project Endpoint |
| GET | `/api/v1/projects/{project_id}` | Get Project Endpoint |
| PATCH | `/api/v1/projects/{project_id}` | Rename Project Endpoint |
| DELETE | `/api/v1/projects/{project_id}` | Archive Project Endpoint |
| POST | `/api/v1/projects/{project_id}/brief-versions` | Create Brief Version Endpoint |
| GET | `/api/v1/projects/{project_id}/brief-versions` | Brief History Endpoint |
| GET | `/api/v1/projects/{project_id}/brief-versions/current` | Current Brief Endpoint |
| GET | `/api/v1/projects/{project_id}/brief-versions/{version_number}` | Brief Version Endpoint |
| GET | `/api/v1/projects/{project_id}/sections` | Sections Endpoint |
| POST | `/api/v1/projects/{project_id}/sections/alignment` | Alignment Endpoint |

All 11 operations require authentication.

## project-clarification

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/brief-assumptions` | List Assumptions Endpoint |
| POST | `/api/v1/projects/{project_id}/brief-assumptions` | Create Assumption Endpoint |
| POST | `/api/v1/projects/{project_id}/brief-assumptions/accept-all` | Accept All Assumptions Endpoint |
| POST | `/api/v1/projects/{project_id}/brief-assumptions/{assumption_id}/accept` | Accept Assumption Endpoint |
| POST | `/api/v1/projects/{project_id}/brief-assumptions/{assumption_id}/reject` | Reject Assumption Endpoint |
| POST | `/api/v1/projects/{project_id}/gates/project-brief/submit` | Submit Brief Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/gates/project-brief/current` | Current Brief Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/gates/project-brief/{gate_id}/events` | Brief Gate Events Endpoint |
| POST | `/api/v1/projects/{project_id}/gates/project-brief/decisions` | Decide Brief Gate Endpoint |

All 9 operations require authentication.

## project-brief

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/brief-dialogue` | Current |
| POST | `/api/v1/projects/{project_id}/brief-dialogue` | Start |
| POST | `/api/v1/projects/{project_id}/brief-dialogue/answers` | Answer |
| POST | `/api/v1/projects/{project_id}/brief-dialogue/questions` | Next Question |
| POST | `/api/v1/projects/{project_id}/brief-dialogue/synthesis` | Synthesize |
| POST | `/api/v1/projects/{project_id}/brief-dialogue/close` | Close |

All 6 operations require authentication.

## agent-teams

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/team/owner-proposals` | Create Owner Team Endpoint |
| GET | `/api/v1/agent-catalog` | Agent Catalog Endpoint |
| POST | `/api/v1/projects/{project_id}/team-proposals` | Generate Team Proposal Endpoint |
| GET | `/api/v1/projects/{project_id}/team-proposals` | Team Proposal History Endpoint |
| GET | `/api/v1/projects/{project_id}/team-proposals/current` | Current Team Proposal Endpoint |
| PATCH | `/api/v1/projects/{project_id}/team-proposals/current` | Edit Team Proposal Endpoint |
| POST | `/api/v1/projects/{project_id}/gates/agent-team/submit` | Submit Agent Team Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/gates/agent-team/current` | Current Agent Team Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/gates/agent-team/{gate_id}/events` | Agent Team Gate Events Endpoint |
| POST | `/api/v1/projects/{project_id}/gates/agent-team/decisions` | Decide Agent Team Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/readiness` | Project Readiness Endpoint |

All 11 operations require authentication.

## user-modeling

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/user-modeling/owner-profiles` | Create Owner Profiles |
| GET | `/api/v1/projects/{project_id}/user-modeling/personas` | Current Personas |
| POST | `/api/v1/projects/{project_id}/user-modeling/personas/proposals` | Propose Personas |
| POST | `/api/v1/projects/{project_id}/user-modeling/personas/{persona_id}/decision` | Decide Persona |
| POST | `/api/v1/projects/{project_id}/user-modeling/snapshots/generate` | Generate Snapshot |
| GET | `/api/v1/projects/{project_id}/user-modeling/snapshots/current` | Current Snapshot |
| GET | `/api/v1/projects/{project_id}/user-modeling/snapshots` | Snapshot History |
| POST | `/api/v1/projects/{project_id}/user-modeling/twins/{twin_id}/revisions` | Propose Revision |
| POST | `/api/v1/projects/{project_id}/user-modeling/revisions/{diff_id}/decision` | Decide Revision |
| GET | `/api/v1/projects/{project_id}/user-modeling/revisions/{diff_id}` | Get Revision |
| POST | `/api/v1/projects/{project_id}/user-modeling/gate/submit` | Submit Gate Three |
| POST | `/api/v1/projects/{project_id}/user-modeling/gate/decision` | Decide Gate Three |
| GET | `/api/v1/projects/{project_id}/user-modeling/gate` | Current Gate Three |
| GET | `/api/v1/projects/{project_id}/user-modeling/gate/events` | Gate Three Events |
| GET | `/api/v1/projects/{project_id}/user-modeling/readiness` | Readiness |
| GET | `/api/v1/projects/{project_id}/user-modeling/archetypes` | List Archetypes |
| POST | `/api/v1/projects/{project_id}/user-modeling/archetypes` | Create Archetype |
| PATCH | `/api/v1/projects/{project_id}/user-modeling/archetypes/{persona_id}` | Edit Archetype |
| DELETE | `/api/v1/projects/{project_id}/user-modeling/archetypes/{persona_id}` | Archive Archetype |
| GET | `/api/v1/projects/{project_id}/user-twins/{twin_id}/conversation` | Conversation |
| POST | `/api/v1/projects/{project_id}/user-twins/{twin_id}/conversation/turns` | Ask |
| GET | `/api/v1/projects/{project_id}/user-modeling/twin-imports/sources` | Sources Endpoint |
| GET | `/api/v1/projects/{project_id}/user-modeling/twin-imports/sources/{source_project_id}` | Source Endpoint |
| POST | `/api/v1/projects/{project_id}/user-modeling/twin-imports` | Import Endpoint |
| GET | `/api/v1/projects/{project_id}/user-modeling/context-alignment` | Alignment Endpoint |
| POST | `/api/v1/projects/{project_id}/user-modeling/context-alignment` | Realign Endpoint |

All 26 operations require authentication.

## requirements

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/requirements/owner-specifications` | Create Owner Specification Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/proposals` | Generate Requirements Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/current` | Current Requirements Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements` | Requirements History Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/revisions` | Propose Revision Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/revisions` | Revision History Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/change-requests` | Request Change Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/revisions/{diff_id}` | Get Revision Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/revisions/{diff_id}/decision` | Decide Revision Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/traceability` | Traceability Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/coverage` | Coverage Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/gate/submit` | Submit Gate Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/gate/decision` | Decide Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/gate` | Current Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/gate/events` | Gate Events Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/readiness` | Readiness Endpoint |
| GET | `/api/v1/projects/{project_id}/requirements/twin-alignment` | Alignment Endpoint |
| POST | `/api/v1/projects/{project_id}/requirements/twin-alignment` | Realign Endpoint |

All 18 operations require authentication.

## design

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/design/proposals` | Generate Design Endpoint |
| GET | `/api/v1/projects/{project_id}/design/current` | Current Design Endpoint |
| GET | `/api/v1/projects/{project_id}/design` | Design History Endpoint |
| POST | `/api/v1/projects/{project_id}/design/revisions` | Propose Revision Endpoint |
| GET | `/api/v1/projects/{project_id}/design/revisions` | Revision History Endpoint |
| POST | `/api/v1/projects/{project_id}/design/change-requests` | Request Change Endpoint |
| GET | `/api/v1/projects/{project_id}/design/revisions/{diff_id}` | Get Revision Endpoint |
| POST | `/api/v1/projects/{project_id}/design/revisions/{diff_id}/decision` | Decide Revision Endpoint |
| POST | `/api/v1/projects/{project_id}/design/revisions/restore` | Restore Version Endpoint |
| POST | `/api/v1/projects/{project_id}/design/gate/submit` | Submit Gate Endpoint |
| POST | `/api/v1/projects/{project_id}/design/gate/decision` | Decide Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/design/gate` | Current Gate Endpoint |
| GET | `/api/v1/projects/{project_id}/design/gate/events` | Gate Events Endpoint |
| GET | `/api/v1/projects/{project_id}/design/readiness` | Readiness Endpoint |
| POST | `/api/v1/projects/{project_id}/design/mockups` | Generate |
| GET | `/api/v1/projects/{project_id}/design/mockups` | Current |
| GET | `/api/v1/projects/{project_id}/design/mockups/capabilities` | Capabilities |
| POST | `/api/v1/projects/{project_id}/design/mockups/jobs` | Start Job |
| GET | `/api/v1/projects/{project_id}/design/mockups/jobs/{job_id}` | Read Job |
| GET | `/api/v1/projects/{project_id}/design/mockups/document` | Document |
| POST | `/api/v1/projects/{project_id}/design/iterations/jobs` | Start Job |
| GET | `/api/v1/projects/{project_id}/design/iterations/jobs/{job_id}` | Read Job |
| GET | `/api/v1/projects/{project_id}/design/iterations` | Iterations |
| POST | `/api/v1/projects/{project_id}/design/evaluations` | Evaluate |
| GET | `/api/v1/projects/{project_id}/design/evaluations` | Runs |
| GET | `/api/v1/projects/{project_id}/design/evaluations/comparison` | Comparison |
| GET | `/api/v1/projects/{project_id}/design/evaluations/validations` | Validations |
| POST | `/api/v1/projects/{project_id}/design/evaluations/{run_id}/validations` | Record Validation |
| POST | `/api/v1/projects/{project_id}/design/regenerations` | Regenerate |
| POST | `/api/v1/projects/{project_id}/design/critiques/sources` | Upload Source |
| GET | `/api/v1/projects/{project_id}/design/critiques/sources` | Sources |
| GET | `/api/v1/projects/{project_id}/design/critiques/sources/{source_id}/shots/{code}` | Shot |
| POST | `/api/v1/projects/{project_id}/design/critiques` | Critique |
| GET | `/api/v1/projects/{project_id}/design/critiques` | Runs |
| GET | `/api/v1/projects/{project_id}/design/evaluations/{run_id}/pins` | Pins |
| GET | `/api/v1/projects/{project_id}/design/evaluations/{run_id}/document` | Document |
| GET | `/api/v1/projects/{project_id}/design/discussions` | Discussions |
| POST | `/api/v1/projects/{project_id}/design/discussions` | Start |
| POST | `/api/v1/projects/{project_id}/design/discussions/{discussion_id}/rounds` | Next Round |
| POST | `/api/v1/projects/{project_id}/design/discussions/{discussion_id}/decision` | Decide |
| GET | `/api/v1/projects/{project_id}/design/distance` | Design Distance Endpoint |
| POST | `/api/v1/projects/{project_id}/insight-applications/batch` | Apply Batch |
| POST | `/api/v1/projects/{project_id}/insight-applications` | Apply |
| GET | `/api/v1/projects/{project_id}/insight-applications` | Applications |
| GET | `/api/v1/projects/{project_id}/design/requirements-alignment` | Alignment Endpoint |
| POST | `/api/v1/projects/{project_id}/design/requirements-alignment` | Realign Endpoint |

All 46 operations require authentication.

## generation-jobs

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/generation-jobs` | Project Jobs |
| GET | `/api/v1/projects/{project_id}/generation-jobs/{job_id}` | Read Job |

Both operations require authentication.

## artifacts

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/artifacts/graph` | Current Graph Endpoint |
| GET | `/api/v1/projects/{project_id}/artifacts/graph/export` | Export Graph Endpoint |
| GET | `/api/v1/projects/{project_id}/artifacts/why/document` | Document Endpoint |
| GET | `/api/v1/projects/{project_id}/artifacts/why` | Explain Endpoint |
| GET | `/api/v1/projects/{project_id}/diagrams` | Project Diagrams Endpoint |

All 5 operations require authentication.

## validation

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/validation` | Overview |
| GET | `/api/v1/projects/{project_id}/validation/walkthrough` | Walkthrough |
| POST | `/api/v1/projects/{project_id}/validation/hypotheses` | Save |
| POST | `/api/v1/projects/{project_id}/validation/hypotheses/{hypothesis_id}/versions` | Revise |
| POST | `/api/v1/projects/{project_id}/validation/outcomes` | Record |

All 5 operations require authentication.

## activity

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/activity` | Activity |
| GET | `/api/v1/projects/{project_id}/activity/session` | Session |
| POST | `/api/v1/projects/{project_id}/activity/sessions` | Start |
| POST | `/api/v1/projects/{project_id}/activity/sessions/{session_code}/end` | End |
| POST | `/api/v1/projects/{project_id}/activity/events` | Record |

All 5 operations require authentication.

## workflow-inputs

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/workflow-inputs` | Records |
| POST | `/api/v1/projects/{project_id}/workflow-inputs/decisions` | Declare |
| GET | `/api/v1/projects/{project_id}/provided-prototypes` | Prototypes |
| POST | `/api/v1/projects/{project_id}/provided-prototypes` | Save |
| GET | `/api/v1/projects/{project_id}/provided-prototypes/current` | Current |
| GET | `/api/v1/projects/{project_id}/provided-prototypes/state` | State |
| GET | `/api/v1/projects/{project_id}/provided-prototypes/gate/current` | Gate Current |
| POST | `/api/v1/projects/{project_id}/provided-prototypes/gate/submit` | Submit |
| POST | `/api/v1/projects/{project_id}/provided-prototypes/gate/decision` | Decide |
| GET | `/api/v1/projects/{project_id}/provided-prototypes/{prototype_id}/document` | Document |

All 10 operations require authentication.

## knowledge

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/knowledge-packages` | Publish Endpoint |
| GET | `/api/v1/projects/{project_id}/knowledge-packages` | History Endpoint |
| GET | `/api/v1/projects/{project_id}/knowledge-packages/{version_number}/archive` | Archive Endpoint |
| POST | `/api/v1/project-imports` | Import Endpoint |
| GET | `/api/v1/projects/{project_id}/import` | Origin Endpoint |

All 5 operations require authentication.

## code-changes

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/alignment` | Alignment |
| POST | `/api/v1/projects/{project_id}/code-changes` | Record |
| GET | `/api/v1/projects/{project_id}/code-changes` | Changes |
| GET | `/api/v1/projects/{project_id}/code-changes/{commit}` | Change |
| POST | `/api/v1/projects/{project_id}/code-changes/{commit}/reviews` | Review |
| GET | `/api/v1/projects/{project_id}/code-changes/{commit}/reviews` | Reviews |
| POST | `/api/v1/projects/{project_id}/code-changes/{commit}/decision` | Decide |
| GET | `/api/v1/projects/{project_id}/code-tasks` | Code Tasks |
| POST | `/api/v1/projects/{project_id}/code-tasks` | Create Tasks |
| POST | `/api/v1/projects/{project_id}/code-tasks/{code}/status` | Task Status |

All 10 operations require authentication.

## knowledge-alignment

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/alignment/runs` | Run |
| GET | `/api/v1/projects/{project_id}/alignment/runs` | Runs |
| GET | `/api/v1/projects/{project_id}/alignment/runs/{run_id}` | Run Of |
| GET | `/api/v1/projects/{project_id}/alignment/proposals` | Proposals |
| POST | `/api/v1/projects/{project_id}/alignment/proposals/{code}/apply` | Apply |
| POST | `/api/v1/projects/{project_id}/alignment/proposals/{code}/skip` | Skip |

All 6 operations require authentication.

## acceptance-tests

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/acceptance-tests` | Overview |
| POST | `/api/v1/projects/{project_id}/test-plans` | Plan |
| GET | `/api/v1/projects/{project_id}/test-plans` | Plans |
| GET | `/api/v1/projects/{project_id}/test-plans/{plan_id}` | Plan Of |
| POST | `/api/v1/projects/{project_id}/test-runs` | Record |
| GET | `/api/v1/projects/{project_id}/test-runs` | Runs |
| GET | `/api/v1/projects/{project_id}/test-runs/{run_id}` | Run Of |
| POST | `/api/v1/projects/{project_id}/test-runs/{run_id}/reviews` | Review |
| GET | `/api/v1/projects/{project_id}/test-runs/{run_id}/reviews` | Reviews |

All 9 operations require authentication.

## twin-learning

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/twin-learning` | Overview |
| POST | `/api/v1/projects/{project_id}/user-twins/{twin_id}/updates` | Propose |
| GET | `/api/v1/projects/{project_id}/twin-updates/{update_id}` | Update Of |
| POST | `/api/v1/projects/{project_id}/twin-updates/{update_id}/decision` | Decide |
| POST | `/api/v1/projects/{project_id}/user-twins/{twin_id}/observations` | Learn |
| POST | `/api/v1/projects/{project_id}/user-twins/{twin_id}/observations/{code}/retire` | Retire |

All 6 operations require authentication.

## research-evidence

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/evidence` | List Evidence |
| POST | `/api/v1/projects/{project_id}/evidence` | Add Evidence |
| GET | `/api/v1/projects/{project_id}/evidence/{evidence_id}` | Get Evidence |
| POST | `/api/v1/projects/{project_id}/evidence/{evidence_id}/versions` | Revise Evidence |
| POST | `/api/v1/projects/{project_id}/evidence/{evidence_id}/retire` | Retire Evidence |
| DELETE | `/api/v1/projects/{project_id}/evidence/{evidence_id}/text` | Delete Evidence Text |
| PUT | `/api/v1/projects/{project_id}/evidence/{evidence_id}/text` | Associate Evidence Text |

All 7 operations require authentication.

## agent-team

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/team/context-alignment` | Status Endpoint |
| POST | `/api/v1/projects/{project_id}/team/context-alignment` | Realign Endpoint |

Both operations require authentication.

## model-generations

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/model-generations` | Generations |
| GET | `/api/v1/projects/{project_id}/model-generations/{generation_id}` | Generation |

Both operations require authentication.

## model-runtime

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/model-runtime/readiness` | Readiness |

This operation requires authentication.

## model-usage

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/model-usage` | Model Usage |
| GET | `/api/v1/model-runtime/budget` | Budget |

Both operations require authentication.
