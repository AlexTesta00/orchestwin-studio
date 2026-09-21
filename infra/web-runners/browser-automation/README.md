# Browser automation infrastructure probe — S12 C60–C62

This is a trusted, repository-owned **technical fixture**, not Web Calculator,
Hotel Management, Weather Comparison, a generated project, or user validation.
The script accepts no URL or arbitrary project source input. Do not substitute
case-study results with these outputs.

## Scope and files

C60 adds a separate browser automation image. It keeps the pinned base of the
existing `Dockerfile.browser` and installs Playwright **1.62.1** and axe-core
**4.13.0**. Existing Node/browser images, the old Dockerfiles, and the old
bootstrap manifest are not overwritten. The image's package installation uses
`--ignore-scripts`, no audit/fund requests, no browser downloads, and an explicit
npm registry. A real package-lock is resolved during the initial build; `npm ci`
installs that graph. The actual lock, including npm-provided integrity values,
is extracted and hashed. No package integrity or lock contents are invented.
Initial resolution is **not** claimed to be byte-reproducible across all future
builds. Freeze the observed image and its lock before subsequent formal runs;
never rerun dependency resolution separately for each formal case.

C61 launches Chromium with `chromiumSandbox: true`, verifies that its command
line contains neither `--no-sandbox` nor `--disable-namespace-sandbox`, navigates
to an in-container HTTP fixture, activates a button by pointer and keyboard,
verifies blocking of a controlled external request, and records screenshots,
DOM, raw axe reports, and browser events at two viewport sizes. A separate
negative control requires axe to detect a deliberately unnamed button. Its
finding is **not** a user finding. The package/bin inventory alone cannot pass.

C62 verifies the hash of the prior bootstrap manifest, all its referenced logs,
and its original recipes; creates only one new image and a labeled temporary
probe container; validates the returned artifact bytes and probe observations;
and records success only after container cleanup is confirmed. Local image
config IDs are never presented as registry manifest digests. No database, model,
training, API authorization, human gate or execution-profile promotion is used.

## Isolation

The probe uses Docker `--network none`, non-root UID/GID 65532, read-only root,
no host bind mounts, no published ports, no host IPC, dropped capabilities,
no-new-privileges, private shared memory, and bounded /tmp, processes, memory,
CPU, logs and runtime. The image build may access the registry/npm; that network
access is not used during the browser probe. The build context has exactly
Dockerfile, package.json, probe.cjs, fixture.html and seccomp.json, not the repo.

`seccomp.json` is an **OrchesTwin amd64-only policy derived from** the syscall
list in Microsoft Playwright's `utils/docker/seccomp_profile.json` at tag
`v1.62.1` (upstream Git blob `fddc05fb520affb145404e6f6f647ca96af8087d`).
It is not a byte-identical copy or an upstream-certified policy. Default is
ERRNO; clone/setns/unshare permit Chromium user namespaces. Modern libc helper
calls close_range, faccessat2, epoll_pwait2 and fchmodat2 are included, clone3
returns ENOSYS for the legacy-clone fallback, and chroot is permitted as a syscall
without granting the host process CAP_SYS_CHROOT. Privileged capability branches,
ptrace, mounts, io_uring and non-amd64 compatibility lists are not enabled.
Some hosts may still disallow unprivileged user namespaces. Such a failure is
recorded, not retried as root, with privileged mode or with Chromium sandbox off.
Successful launch plus argument checks is **not a complete kernel security audit**.

Sources and attribution: Microsoft Playwright, Apache-2.0:
https://github.com/microsoft/playwright/blob/v1.62.1/utils/docker/seccomp_profile.json
https://playwright.dev/docs/docker
https://playwright.dev/docs/api/class-browsertype
https://docs.npmjs.com/cli/v11/commands/npm-ci
axe-core: Deque Systems, MPL-2.0; licenses remain in the installed npm packages.

## Run after committing verified code

From the repository root (Python virtual environment active):

```powershell
python -B scripts/sprint12_verify_browser_automation.py --repo-root . --parent-manifest "C:\Users\alext\orchestwin-runner-evidence\runner-20260908-194927-1502f4a1\manifest.json" --output-root "$HOME\orchestwin-runner-evidence\browser-NEW-UNIQUE-NAME" --build-browser-runner
```

The output directory must not exist and must be outside the repository. The
parent directory's complete logs must remain beside its manifest. Do not delete
or recreate PostgreSQL or any earlier evidence. The command does not commit or
push. Build/probe steps print progress labels; complete logs stay in output.

A passing result has `status=BROWSER_AUTOMATION_PROBE_PASSED`,
`browser_automation_verified=true`, `cleanup_confirmed=true`, and
`formal_run_started=false`, `level_d_validated=false`,
`generated_projects_authorized=false`.
Axe violation counts on the fixture are observations, not a WCAG compliance claim.
Checksums provide integrity/lineage, not third-party attestation.

## Verification and handoff

Run the Python parser/orchestration tests and Node envelope tests before a commit.
Run the non-integration suite; do not run destructive PostgreSQL integration tests
against the working database. No migration is introduced.

After local success, record the actual new Git hash and the new manifest path
in project handoff state. Do not mark Sprint 12 complete or fabricate hashes here.
The next runtime work still includes connecting phase execution and browser
collection to the authorized API, real model providers, graph advancement,
repair and finalization. This probe does not do those things.
