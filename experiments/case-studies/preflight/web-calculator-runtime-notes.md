# Web calculator preflight after 5e0cd17

`web-calculator-runtime-5e0cd17.json` records the local read-only audit and identifies
the retained observations by file hash. No new formal project, workflow, attempt,
source revision or Gate decision was created by this audit.

The application database contains evidence supporting five Web and three JVM
Level D profiles. The running API image still exposes the old Sprint 07 catalog,
whose ten generic descriptors all report Level C. This is a stale API projection,
not loss of the persisted validation evidence.

The candidate implementation reads both verified evidence histories in a single
PostgreSQL `REPEATABLE READ, READ ONLY` transaction. `/execution-profiles` and
exact-version detail lookups retain public target IDs such as `WEB_STATIC` and
expose the corresponding typed profile (`web.static`), validation scope, runner
digests and governed API routes. The descriptor hash includes that scope. Actual
database observations confirmed eight Level D entries through the candidate API.
Each request reloads evidence; inconsistent history cannot retain a cached promotion.

These are descriptors for the typed execution APIs. The broader legacy brownfield
detectors remain Level C: JVM validation, for example, does not establish support
for arbitrary Maven or multi-module source archives. Android remains Level C.
Profile validation does not authorize a project execution: exact source validation,
runtime configuration and Gate 7 approval remain required.

The current API container has `ORCHESTWIN_TEAM_PROPOSAL_PROVIDER=FAKE_DETERMINISTIC`.
The committed proposal factories for User Modeling, Requirements, Design and
Architecture currently expose only `FAKE_DETERMINISTIC`. The team factory declares
`MODEL_ADAPTER` as a configuration option but rejects it because its adapter is not
implemented. This is separate from real Docker execution and from the final
User Twin evaluator, which has its own model runtime. This audit does not establish
whether trained twin adapters are available or whether that evaluator is ready.

Before a new calculator attempt, choose and record its generative-provider scope:
either connect the proposal stages to real model adapters, or explicitly retain
deterministic proposals as a methodological limitation. The full model workflow
cannot be claimed under the current proposal factories.

After the user's commit, deploy the corresponding API code with explicit governed
Web settings and the verified runner manifest. Recheck the deployed catalog and
the required model/evaluator services before creating the new project and frozen
formal evidence workspace. C94 must remain frozen; none of its old observations
may be relabeled as results of the new attempt.

The 782 API/sandbox/project regression tests passed. Two PostgreSQL integration
tests verified persistence across a fresh engine, unchanged evidence rows, enforced
read-only transaction settings and a consistent snapshot during a concurrent
publication. Their synthetic test records exist only in disposable schemas; the
separate candidate API audit used the real application catalog without writing it.
