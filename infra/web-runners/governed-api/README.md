# Governed Web API adapter (Unit 7)

The default application runtime now composes production services for Web
execution, history/reports, browser evidence, and repairs. These services use
the persisted owner-scoped source revisions and attempts, the verified profile
catalog, the real phase executors, and the existing human-gate domain.

## Configuration

Apply migration `0035_web_governed_operations` to the intended database before
using the operation API. Execution is disabled by default. Enabling it requires
explicit `ORCHESTWIN_GOVERNED_WEB_` settings:

| Suffix | Value |
| --- | --- |
| `ENABLED` | `true` |
| `REPO_ROOT` | Absolute checkout containing the verified runner recipes and browser harness |
| `RUNNER_MANIFEST` | Absolute path to a verified Unit 4 bootstrap manifest |
| `WORKSPACES_ROOT` | Absolute private directory for disposable execution workspaces |
| `DOCKER_CONTEXT` | Docker context containing those exact local images; default `desktop-linux` |
| `CONTROLLED_NETWORK` | JSON configuration for an operator-provisioned restricted dependency network, when required by the execution plan |

The controlled network object contains `name`, immutable `network_id`,
`policy_hash`, `proxy_host`, and `proxy_port`. The executor verifies the Docker
network and policy before use. Profiles requiring dependency installation
cannot prepare an execution without this configuration.

Source objects use the application's existing
`brownfield_workspace_root/web-source-objects` store. Evidence uses
`sandbox_evidence_storage_root`. Source, evidence, and execution workspace roots
must be separate. Application composition creates no files or containers.

## Owner workflow

1. Send the execution body to
   `POST /projects/{project_id}/web-execution-plans`, with no `authorization_id`.
   The service resolves the current persisted source, reads and verifies its
   bytes, detects the project, checks locks and profile compatibility, and
   loads the verified runner identities. It returns an immutable operation
   snapshot and a pending Gate 7. No execution has started.
2. Review that snapshot. It binds source, contract, profile/version, policy,
   runner and bootstrap identities, resources, browser harness/seccomp hashes,
   routes/actions, and the previous attempt. Decide through
   `POST /projects/{project_id}/web-operations/{operation_id}/gate`, supplying
   `expected_content_hash`, `expected_gate_event_sequence`, `action`, and an
   optional `reason`.
3. Send the same execution body to
   `POST /projects/{project_id}/web-executions`, setting `authorization_id` to
   the approved **operation ID**. The service resolves and compares the inputs
   again, verifies the exact persisted approval, and commits a single claim
   before creating workspaces or containers. The attempt ID equals that
   operation ID.
4. Read project history from `/projects/{project_id}/web-executions` and the
   attempt, report, and browser evidence from `/web-executions/{execution_id}`,
   its `/report`, and its `/browser-evidence` resources. Browser reads verify
   persisted content hashes and bindings, including partial evidence on failure.
5. Propose a repair through
   `POST /web-executions/{execution_id}/repair-proposals`, binding the current
   source hash and an actual failure signature. Review and approve its Gate 7
   through the same operation API. Apply through
   `/web-executions/{execution_id}/repair-proposals/{proposal_id}/apply`, with
   the base revision hash, `proposal_content_hash`, and approved **gate ID** as
   `approval_id`. Application appends an immutable source revision atomically
   with the operation outcome; it does not execute code.
6. Prepare and approve a new execution for that revision with `REPAIR_RERUN`
   and the returned required phases. Every API run uses a fresh workspace, so
   the reviewed plan explicitly expands the requested rerun into all phases.

Routes are local and bounded. Interactive pages also require explicit
`browser_interactions` with pointer and keyboard actions and assertions, as
described in the [browser phase documentation](../phase-browser/README.md).

The project lock and a unique running-operation constraint prevent concurrent
claims. Repeating a completed start returns its persisted attempt without
executing again. Cancellation and persistence failures reconcile against the
actual stored attempt: a recorded failed report is still a completed recording
operation. If database state cannot be verified, the claim remains `RUNNING`
and is not retried automatically. A process termination that prevents
reconciliation requires operator investigation; no automatic crash recovery
or background execution queue is introduced here.

## Verification and scope

The API and domain tests cover exact approval bindings, foreign-owner access,
stale source/attempt rejection, immutable repair content, cancellation,
idempotency, and evidence integrity. The opt-in integration test
`src/test/python/integration/test_governed_web_api_runtime.py` exercises real
PostgreSQL and Docker: a deterministic console failure, persisted claim,
duplicate-start rejection, service restart, approved repair, and a successful
rerun. Set `ORCHESTWIN_DATABASE_URL` to a fresh dedicated database migrated to
head and `ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST` to the verified manifest.
The test reads only those explicit environment settings, never the application
`.env`, and uses UUID-scoped test owners/projects without truncating tables.
It also uses a single-connection pool to exercise preparation and replay without
nested connection acquisition. The separate
`src/test/python/integration/test_web_operation_postgres.py` suite requires
`ORCHESTWIN_WEB_OPERATION_TEST_DATABASE_URL`; its adversarial SQL probes always
roll back and verify immutable inputs, terminal state, concurrent claims, and
repeated independently approved operations.

This adapter does not promote a profile to Level D. `OWNER_PROJECT` execution
remains blocked for profiles without verified Level D evidence.
`PROFILE_VALIDATION` accepts persisted deterministic fixtures and their governed
repair lineage, with an exact owner decision; changing a request's purpose
cannot turn an ordinary owner project into a validation fixture. Development
test artifacts are not empirical user evidence or a formal calculator run.
The C94 attempt remains frozen. Complete profile validation and promotion
belong to the subsequent unit.
