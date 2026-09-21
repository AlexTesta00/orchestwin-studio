# Phase 2 — durable proposal generation evidence

Base commit: `8bedba79a061e916b857d80bc8eec608daa8834c`.
The owner creates the phase commit. No commit or push is performed by the agent.

## Implemented boundary

The standard API runtime records model generations for team, personas, User Twins,
requirements, design and architecture. Each command has an isolated generation UUID.
The request is committed before inference, with its exact input context, output schema,
instructions, model identity, temperature, token budget and timeout. Short transactions
then retain the HTTP payload without authentication headers, original response bytes,
provider result, adapter acceptance/rejection and application disposition.

Artifact links contain the generation UUID, artifact kind, exact version UUID, version
number and content hash. Links are inserted in the artifact transaction. PostgreSQL
checks the actual artifact row and accepted output hash before allowing publication.
The User Modeling snapshot must contain exactly the generated twins linked by that
transaction. Repeated identical team output can be recorded as `MATCHED_EXISTING`.
Model-output provenance in personas, twins and design refers to the generation UUID
and canonical output hash.

Migration `0038_proposal_generation_evidence` adds append-only request, observation
and link tables. UPDATE, DELETE and TRUNCATE are rejected. Hash, ownership, event
sequence and artifact identity checks remain active during integration tests.

Authenticated owners can read:

- `GET /api/v1/projects/{project_id}/model-generations?limit=50&before={generation_id}`
- `GET /api/v1/projects/{project_id}/model-generations/{generation_id}`

The list is bounded to 100 entries and paginated by descending generation UUID.
Detail reads use one repeatable-read, read-only transaction. Raw response bytes are
base64 encoded. Owners retain access after project archival; archival prevents new
generation/publication. Fake adapters do not create model-generation evidence.

## Observed evidence

The index [phase-2-v1.json](phase-2-v1.json) records external artifact locations and SHA-256
digests. A fresh Qwen/Qwen3-4B-Instruct-2507 inference created a team proposal in a
disposable PostgreSQL database: 1,517 input tokens, 94 output tokens, 8,490 ms, temperature
0.6. Identity and model-visible message hashes match. The raw response and exact artifact
link survived disposal and recreation of the application database runtime. No output
repair or retry was used; no trained adapter was loaded.

This is an engineering probe with synthetic governance fixtures, not a formal thesis
case, calculator campaign, semantic-quality evaluation or new Level D qualification.
The application database and frozen case were not used. Probe data was exported before
the disposable database was removed.

Validation: 1,057 related regression tests; 34 final focused tests; 14 synthetic PostgreSQL
tests; one separately enabled real-inference retention probe. Ruff check and format
check pass across the repository. Migration downgrade/upgrade passes on disposable data.
CI enables the synthetic PostgreSQL suite on Linux, macOS and Windows; real inference
requires a separate explicit configuration.

## Operational limits and next phase

Apply migration 0038 before using the evidence API/model publication in a deployment.
This phase applied it only to disposable databases. Standalone adapter calls without
an application evidence scope remain engineering calls without automatic persistence.

Inference is not held inside the artifact transaction. A crash or audit-storage failure
can leave an incomplete observation history; it never justifies inventing a terminal
result. An application-disposition write can fail after an artifact transaction commits:
the exact artifact links remain authoritative and inspectable. Malformed responses
are retained; transport failures before receipt have no response body. HTTP responses
over 4 MB are rejected by the bounded transport. Credential-reflecting responses are
withheld, with their digest and withholding reason retained.

Phase 3 qualifies the deployed real-provider configuration and connectivity, including
the evaluator. Source/repair generation and a new formal calculator attempt remain
subsequent work. Deterministic governance rules and synthetic test fixtures remain valid.
