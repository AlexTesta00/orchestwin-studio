# Governed Web Level D validation campaign

This command collects observed execution evidence for the five Web profiles and
their eight supported language configurations. Source fixtures, passing unit
tests, runner builds, and a dependency-network bootstrap are prerequisites;
none of them grants Level D on its own. The frozen C94 attempt is not an input
to this campaign and must not be resumed or rewritten.

The campaign uses the actual execution engine, PostgreSQL operation history,
Gate 7 decisions, browser evidence, and immutable repair revisions. It creates
24 dedicated projects: valid, independent repeated, and deliberately defective
sources for each configuration. Completing their repair journeys produces 32
execution attempts and eight repair operations.

## Prerequisites

1. The owner has committed the implementation. Keep that checkout clean and at
   the same commit throughout the campaign. The loaded Python package must come
   from this checkout; use its editable installation and virtual environment.
2. Build and probe all three pinned runners using
   `scripts/sprint12_bootstrap_web_runners.py --repo-root <absolute-repo>
   --output-root <new-external-directory> --build-runners`. The output is a local
   runner identity receipt. It does not claim registry digest identity or D.
3. Provision the [restricted dependency network](../dependency-network/README.md)
   and retain its manifest and logs. Use its `controlled_network` object in the
   campaign configuration. Keep the proxy running until execution is complete.
4. Select an explicitly authorized, migrated PostgreSQL database and an existing
   active owner UUID in that database. Set `ORCHESTWIN_DATABASE_URL` explicitly
   in the command environment. The command does not read the application's
   `.env`. Do not select the frozen C94 database or fabricate a validation owner.
5. The CI/CD workflow for the exact campaign commit must complete successfully
   before publication. The harvester retrieves provider observations itself;
   a manually authored successful CI JSON is not accepted. `GITHUB_TOKEN` is
   optional for GitHub API access and must remain outside configuration files.

## Configuration

Create the operator JSON outside the repository. It has exactly these nine
fields; replace illustrative paths and the network placeholders with actual
values from the bootstrap. All paths must be absolute, without symlinks or
junctions. Workspaces, source storage, evidence storage, and the campaign
directory must be separate, non-overlapping directories outside the checkout.

```json
{
  "repo_root": "C:/work/orchestwin-studio",
  "runner_manifest": "C:/evidence/runners/manifest.json",
  "workspaces_root": "C:/evidence/web-workspaces",
  "source_root": "C:/evidence/web-sources",
  "evidence_root": "C:/evidence/web-artifacts",
  "docker_context": "desktop-linux",
  "controlled_network": {
    "name": "COPY_FROM_NETWORK_MANIFEST",
    "network_id": "COPY_FROM_NETWORK_MANIFEST",
    "policy_hash": "COPY_FROM_NETWORK_MANIFEST",
    "proxy_host": "COPY_FROM_NETWORK_MANIFEST",
    "proxy_port": 3128
  },
  "resources": {
    "cpu_count": 2.0,
    "memory_mib": 2048,
    "pids_limit": 256,
    "writable_tmpfs_mib": 512
  },
  "github_repository": "AlexTesta00/orchestwin-studio"
}
```

The configuration and database identity are bound to the immutable campaign
plan. A different configuration requires a new campaign. Credentials are not
included in the plan's database identity.

## Prepare, review, and advance

Run from the approved repository with the explicit database environment set.
The following PowerShell arguments are illustrative:

```powershell
$campaignArgs = @('--config', 'C:/evidence/web-config.json', '--campaign-dir', 'C:/evidence/web-campaign')
.venv/Scripts/python.exe scripts/validate_web_level_d.py prepare @campaignArgs --owner-id <active-owner-uuid>
.venv/Scripts/python.exe scripts/validate_web_level_d.py review @campaignArgs
```

`prepare` persists the plan, seeds dedicated deterministic fixtures, and prepares
24 execution proposals. It does not execute them. `review` writes an immutable
snapshot containing source revisions, operation payloads, hashes, and gates.
The owner reviews that concrete snapshot before supplying decisions.

An approval file is a JSON array of already prepared operations, each containing
exactly `operation_id`, `content_hash`, and `event_sequence`. Copy their current
values from the reviewed operation and gate history. Do not approve future
operations or generate blanket approvals. The command rejects foreign,
duplicate, stale, or incorrectly bound decisions.

```powershell
.venv/Scripts/python.exe scripts/validate_web_level_d.py advance @campaignArgs --decisions C:/evidence/approved-executions.json
.venv/Scripts/python.exe scripts/validate_web_level_d.py review @campaignArgs
```

Each advance executes at most one existing approved operation per project.
After the initial executions, eight defective fixtures must exhibit their
specific `LEVEL_D_NEGATIVE_CONTROL` failure. Their one-file repair proposals
require a separate owner review and approval. Applying those repairs creates
eight new source revisions and prepares full reruns, which require another
separate approval. Thus a complete campaign has three decision rounds:
24 initial executions, eight repairs, and eight reruns.

The CLI can resume from its persisted plan and PostgreSQL history. A process
termination releases its OS lock. An operation left `RUNNING` or with an
unresolved recording failure requires investigation; do not blindly replay it.
A dirty checkout or changed commit taints the campaign and prevents publication.

## Harvest and publish

```powershell
.venv/Scripts/python.exe scripts/validate_web_level_d.py harvest @campaignArgs
```

This reads the actual 32 attempts and eight repairs, verifies artifacts and
approval lineage, runs the required fixture contract tests, and retrieves fresh
CI observations for the exact commit. It retains immutable collection receipts.
Expected negative failures must have their precise marker and phase; setup
errors, missing artifacts, failed repairs, and unsuccessful positive cases do
not satisfy the validation matrix.

Only after reviewing a complete eligible collection, publish explicitly:

```powershell
.venv/Scripts/python.exe scripts/validate_web_level_d.py harvest @campaignArgs --publish
```

Publication revalidates the collection and appends its evidence atomically in
PostgreSQL. It requires all five Web profiles to be eligible. A conflicting or
incomplete collection cannot partially promote the catalog; republishing the
same batch is idempotent. Inspect the returned manifest and actual promotion
decisions rather than inferring readiness from the number of files.

This is profile validation, not a formal user study or the calculator attempt.
The three JVM profiles also require their own evidence-backed D before starting
a new complete-engine formal calculator run. C94 remains frozen.
