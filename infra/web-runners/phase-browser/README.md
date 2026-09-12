# Governed Web browser phase (Unit 6)

This harness connects the browser phase to the application started by the
governed Web phase executor. It does not start its own application or mount
project sources. The browser joins the running server's verified, immutable
container network namespace, which has no external network. Docker uses the
verified bootstrap browser image, UID 65532, Chromium sandbox, the existing
browser seccomp policy, read-only root, and bounded resources and output.

`GovernedWebBrowserExecutor` requires a browser runner identity loaded with
`load_phase_runner_identity(..., kind="BROWSER")`. Supply it as
`GovernedWebPhaseExecutor(..., browser_executor=browser)`. When composing the
workflow service, pass that phase executor as both `phase_lifecycle` and
`phase_attempt_binding`, so the authorized attempt ID is allocated and bound
before any phase starts and resource cleanup completes before persistence.
Direct development tests call `bind_attempt(UUID)` before the first phase.
Missing or mismatched attempt, contract, source, bootstrap, or runner bindings
block browser execution.

The canonical stdin job binds the exact request, source revision/tree, browser
image, attempt ID, operation ID, harness hash, routes, viewports, and explicit
interaction plans. The harness visits root plus at most four declared local
routes, in request order, at 390x844 and 1280x800. Same-origin assets are allowed;
external requests, undeclared navigation, popups, downloads, service workers,
and WebSockets produce failures. Every route/viewport uses a fresh context.

Interactive pages require explicit `WebBrowserInteraction` plans with pointer
and keyboard activation and assertions after both. A page with observed
controls cannot claim interaction coverage without a plan. A noninteractive
document records `NOT_APPLICABLE`. The independent development calculator
fixture exercises addition through click and Enter, with different operands.
Controls in open shadow roots are counted recursively. Frames, closed shadow
roots, and other surfaces whose controls cannot be inspected produce an explicit
interaction inspection failure; they cannot claim noninteractive coverage.

Screenshot PNGs, DOM, axe results, console/page/network events, action outcomes,
and raw process streams are stored by content hash. A manifest retains the
route/viewport mapping, including partial evidence on failure. DOM and axe run
in an isolated browser world. The decoder checks bindings, exact viewport
coverage, byte hashes, sizes, and PNG structure. A `COLLECTED` bundle describes
completeness only: console errors, failed requests, accessibility violations,
failed assertions, missing evidence, timeout, or resource failures cannot make
the browser phase pass. Process exit codes are accepted only after terminal
Docker state verification. Unconfirmed browser cleanup also fails finalization.

Run the deterministic harness tests with:

```powershell
node --test infra/web-runners/phase-browser/inspect.test.cjs
```

The Python browser tests live under `src/test/python/web_execution/` with names
`test_phase_browser_*.py`. Real Docker tests are opt-in through
`ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST`, pointing to an existing verified
Unit 4 bootstrap manifest. They use fresh development sources, private evidence
stores, and disposable containers. Use a fresh pytest `--basetemp` for each run.

This unit does not promote any profile to Level D, produce empirical user
validation, or resume the frozen C94 calculator attempt. Production API wiring
and the complete profile validation/promotion harness remain subsequent units.
