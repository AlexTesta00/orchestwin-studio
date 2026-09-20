# Static browser executor — C64–C67

This is a reusable execution component, not another fixed page embedded in a
Docker image. `job_from_revision` consumes a `WebSourceRevision.to_snapshot()`
obtained through owner-scoped persistence and content-addressed source bytes.
The compiler verifies ownership fields, revision/tree hashes and blob addresses.
It does **not** replace the database access-control check.

The job contains complete static files and bounded declarative scenarios:
`click`, `fill`, `press`, `expect_text`. Every scenario includes an assertion and
runs at 390×844 and 1280×800. Up to 100 UTF-8 HTML/CSS/JavaScript/JSON/SVG files,
1 MiB in total, and two scenarios with at most eight actions each are admitted.
No submitted file is imported or executed as Node.js code. The Node HTTP server
serves only an in-memory map of the submitted files; JavaScript runs in Chromium.

## Image and process boundary

The successful C63 browser manifest and every listed artifact are hash-verified.
Its recorded local image ID is inspected and used directly; registry digests are
not fabricated. Missing images, changed recipes or corrupt evidence block the
operation. No image is built or pulled by this component.

The trusted harness goes in Docker argv, under a conservative Windows command
line bound. The source/job payload goes through bounded stdin (4 MiB maximum).
There are no host bind mounts, Docker-socket mounts, external URL parameters,
package installations, shell commands or editable launch flags. The container
uses the recorded seccomp profile, non-root uid 65532, no external network,
read-only root filesystem, dropped capabilities, no-new-privileges and bounded
resources. Chromium keeps its sandbox requested and its launch flags checked.
No independent kernel sandbox audit is claimed.

## Authority and application integration

`execute_static_browser_job` has no default authority. Its caller must supply an
independent resolver that returns a receipt for the exact job hash. This callable
is an internal trusted port, not a user-supplied JSON authorization token.
The receipt binds source, scenarios, harness and observed runner identity.

This batch DOES NOT implement the persisted Gate 7 resolver or mount a new owner
execution endpoint in FastAPI. A caller cannot consider the compiler's owner
field comparison to be a database authorization check. Those application
connections remain necessary before executing generated projects formally.
No existing Gate 7 flow or profile capability marker is weakened or promoted.

The only public command added here accepts the committed technical fixture set:

```powershell
python scripts/sprint12_validate_static_browser_executor.py --repo-root . --runner-manifest <C63-manifest.json> --output-root <new-external-directory> --validate-static-executor
```

It restricts PROFILE_VALIDATION authorization to the exact jobs compiled from
that set. There are two different positive projects (form interaction and keyboard
panel) and one intentionally incorrect text assertion. All use the same executor.
No Calculator/Hotel/Weather generation branch is introduced.

## Outcome semantics

`status: COMPLETED` means the browser job produced complete verified evidence and
its own container was removed. It does NOT mean every assertion passed.
`assertion_status` remains `PASSED` or `FAILED`; failed actions are not skipped or
turned green. After the first failed action, later actions are `NOT_RUN`.

Axe results are preserved separately from functional assertions. Zero automated
findings is not a complete accessibility certification. A negative fixture is
accepted as a valid negative control only when the intended text assertion fails,
not because of a page error, blocked dependency or an infrastructure failure.

Every job preserves source/job input, raw stdout/stderr, screenshots, DOM, full
axe reports, browser events, hashes and timestamps. Inputs may contain client
source code: keep real-project evidence private. No assertion about users, User
Twins or formal case completion is made by these technical fixtures.

Filesystem evidence is not a SQL transaction. This component does not write a
`WebExecutionAttempt` or advance the workflow. Those bindings, full phase/profile
validation, repair, real model providers and final export remain separate work.

## Primary references

- Docker start: https://docs.docker.com/reference/cli/docker/container/start/
- Docker run controls: https://docs.docker.com/reference/cli/docker/container/run/
- Playwright browser contexts: https://playwright.dev/docs/api/class-browsercontext
- Playwright accessibility testing limits: https://playwright.dev/docs/accessibility-testing
