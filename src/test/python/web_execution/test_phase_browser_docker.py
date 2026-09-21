"""Opt-in development browser integration, separate from every formal calculator run."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import struct
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.docker_runtime import HostProcessStatus
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
)
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.phase_runtime import LocalWebPhaseRuntime
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.static_browser_jobs import VIEWPORTS, BrowserAction
from orchestwin.web_execution.workspaces import materialize_web_source_snapshot

from .test_profile_fixture_matrix import detection_snapshot

MANIFEST = os.environ.get("ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="explicit Web runner Docker integration is disabled"
)


def page(title: str, body: str, *, script: bool = False) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title>"
        "<style>body{font:18px sans-serif;color:#111;background:#fff;margin:24px}"
        "label,input,button{display:block;margin:12px 0}"
        "input,button{font:inherit;padding:8px}main{max-width:40rem}</style>"
        f"</head><body><main><h1>{title}</h1>{body}</main>"
        + ('<script src="/app.js"></script>' if script else "")
        + "</body></html>"
    )


def calculator_files() -> dict[str, str]:
    """Generate a small development fixture; never load C94 or its source/evidence."""
    return {
        "index.html": page(
            "Unit6 development calculator",
            '<form id="calculator"><label for="a">First value</label>'
            '<input id="a" name="a" type="number" step="any" required>'
            '<label for="b">Second value</label>'
            '<input id="b" name="b" type="number" step="any" required>'
            '<button id="add" type="submit">Add values</button></form>'
            '<p>Result: <output id="result" for="a b" aria-live="polite">0</output></p>',
            script=True,
        ),
        "app.js": (
            "document.querySelector('#calculator').addEventListener('submit', event => {"
            "event.preventDefault(); document.querySelector('#result').value = String("
            "Number(document.querySelector('#a').value) + Number(document.querySelector('#b').value));"
            "});"
        ),
    }


def calculator_interactions(*, wrong_assertion: bool = False):
    from orchestwin.web_execution.phase_browser_evidence import WebBrowserInteraction

    return (
        WebBrowserInteraction(
            "root",
            (
                BrowserAction("fill", "#a", "2"),
                BrowserAction("fill", "#b", "3"),
                BrowserAction("click", "#add"),
                BrowserAction("expect_text", "#result", "-1000" if wrong_assertion else "5"),
                BrowserAction("fill", "#a", "7"),
                BrowserAction("fill", "#b", "8"),
                BrowserAction("press", "#add", "Enter"),
                BrowserAction("expect_text", "#result", "15"),
            ),
        ),
    )


class TracedRuntime(LocalWebPhaseRuntime):
    """Retain the names of real owned containers for post-cleanup Docker inspection."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.observed_argv = []

    async def _call(self, argv, **kwargs):
        self.observed_argv.append(tuple(argv))
        return await super()._call(argv, **kwargs)


def materialize_fixture(tmp_path: Path, files: dict[str, str], selection):
    source_root = tmp_path / "source-objects"
    source_store = FileSystemSandboxEvidenceStore(source_root)
    entries = []
    for path, text in sorted(files.items()):
        stored = source_store.store_artifact(
            run_id=uuid4(),
            command_id="unit6.development.import",
            normalized_path=path,
            content=text.encode("utf-8"),
            media_type=mimetypes.guess_type(path)[0] or "text/plain",
        )
        entries.append(
            WebSourceFileEntry(
                path,
                stored.sha256_digest,
                stored.size_bytes,
                stored.storage_key,
                stored.media_type,
            )
        )
    provenance = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    revision = create_web_source_revision(
        revision_id=uuid4(),
        project_id=uuid4(),
        created_by_user_id=uuid4(),
        version_number=1,
        based_on=None,
        target=selection.target,
        language_configuration=selection.language_configuration,
        layout=selection.layout,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=tuple(entries),
        provenance_references=(
            WebSourceProvenanceReference(
                WebSourceProvenanceKind.SOURCE_PLAN, "unit6.development.fixture", 1, provenance
            ),
        ),
        created_at=datetime.now(UTC),
    )
    prepared = materialize_web_source_snapshot(
        revision.to_snapshot(),
        content_root=source_root,
        workspaces_root=tmp_path / "prepared",
    )
    return revision, prepared


def reference_bytes(store, reference: dict) -> bytes:
    body = store.read(reference["storage_key"])
    assert body is not None
    assert len(body) == reference["size_bytes"]
    assert hashlib.sha256(body).hexdigest() == reference["sha256_digest"]
    return body


def nested_references(value):
    if isinstance(value, dict):
        if {"storage_key", "sha256_digest", "size_bytes"} <= value.keys():
            yield value
        for child in value.values():
            yield from nested_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_references(child)


def stored_documents(results, store):
    """Verify every public reference, including evidence referenced by manifests."""
    pending = [
        reference.to_snapshot()
        for result in results
        for reference in (*result.stdout_refs, *result.stderr_refs, *result.artifact_refs)
    ]
    seen = set()
    documents = []
    while pending:
        reference = pending.pop()
        body = reference_bytes(store, reference)
        if reference["storage_key"] in seen:
            continue
        seen.add(reference["storage_key"])
        try:
            document = json.loads(body)
        except (ValueError, UnicodeError):
            continue
        documents.append(document)
        pending.extend(nested_references(document))
    return documents


async def execute_fixture(tmp_path: Path, files: dict[str, str], *, routes=(), interactions=()):
    from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor

    repository = Path(__file__).parents[4]
    manifest_path = Path(MANIFEST)
    bootstrap = json.loads(manifest_path.read_bytes())
    node = load_phase_runner_identity(manifest_path, repo_root=repository, kind="NODE")
    browser = load_phase_runner_identity(manifest_path, repo_root=repository, kind="BROWSER")
    snapshot = detection_snapshot(files)
    detected = detect_web_project(snapshot).selected
    assert detected is not None
    selection = detected.selection
    locks = validate_web_dependency_locks(snapshot, selection=selection)
    revision, prepared = materialize_fixture(tmp_path, files, selection)
    profile = create_sprint08_web_profile_registry().find("web.static", "1.0.0")
    assert profile is not None
    contract = profile.create_contract(
        snapshot,
        selection=selection,
        lock_report=locks,
        source_revision_content_hash=revision.content_hash,
        source_tree_hash=revision.source_tree_hash,
        runners=WebProfileRunnerSet(
            node.image_id.removeprefix("sha256:"), browser.image_id.removeprefix("sha256:")
        ),
        declared_routes=routes,
    )
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    browser_executor = GovernedWebBrowserExecutor(
        runner_identity=browser,
        repo_root=repository,
        evidence_store=store,
        interactions=interactions,
    )
    executor = GovernedWebPhaseExecutor(
        contract=contract,
        prepared_workspace=prepared,
        snapshot=snapshot,
        lock_report=locks,
        runner_identity=node,
        execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        workspaces_root=tmp_path / "mutable",
        evidence_store=store,
        docker_context=bootstrap["environment"]["docker_context"],
        runtime_factory=TracedRuntime,
        browser_executor=browser_executor,
    )
    attempt_id = uuid4()
    executor.bind_attempt(attempt_id)
    results = []
    final = None
    try:
        for phase in contract.execution_plan.phases:
            result = await executor.execute(phase, contract=contract)
            results.append(result)
            if result.is_failure:
                break
    finally:
        try:
            final = await executor.finalize()
            if final is not None and final not in results:
                results.append(final)
        finally:
            payload = {
                "purpose": "UNIT6_DEVELOPMENT_BROWSER_INTEGRATION",
                "formal_run_started": False,
                "level_d_validated": False,
                "execution_attempt_id": str(attempt_id),
                "source_revision": revision.to_snapshot(),
                "contract_hash": contract.content_hash,
                "bootstrap_manifest_hash": browser.bootstrap_manifest_hash,
                "phase_results": [result.to_snapshot() for result in results],
            }
            (tmp_path / "development-browser-results.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
    assert final is not None and final.status.value == "PASSED", (
        None if final is None else final.to_snapshot()
    )
    assert executor.workspace is not None and not executor.workspace.path.exists()
    for path, content in files.items():
        assert (prepared.path / path).read_bytes() == content.encode("utf-8")
    documents = stored_documents(results, store)
    final_manifests = [
        document
        for document in documents
        if isinstance(document, dict)
        and document.get("phase") == "COLLECT_ARTIFACTS"
        and "observations" in document
    ]
    assert len(final_manifests) == 1
    assert final_manifests[0]["observations"]["cleanup_confirmed"] is True
    browser_results = [
        result for result in results if result.phase is WebExecutionPhase.BROWSER_EVIDENCE
    ]
    assert len(browser_results) == 1, [result.to_snapshot() for result in results]
    manifests = [
        document
        for document in documents
        if isinstance(document, dict)
        and document.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE"
    ]
    assert len(manifests) == 1
    observed = manifests[0]
    assert observed["execution_attempt_id"] == str(attempt_id)
    assert observed["cleanup_confirmed"] is True
    names = sorted(
        {
            argv[argv.index("--name") + 1]
            for argv in executor.runtime.observed_argv
            if "--name" in argv
        }
    )
    assert len(names) >= 2  # Static smoke server and run server.
    created = next(item for item in observed["operations"] if item["label"] == "CREATE")
    sidecar_id = reference_bytes(store, created["stdout_ref"]).decode("ascii").strip()
    assert len(sidecar_id) == 64 and set(sidecar_id) <= set("0123456789abcdef")
    absent = await executor.runtime._call(
        (*executor.runtime.docker, "inspect", *names, sidecar_id), timeout_seconds=5
    )
    assert absent.status is HostProcessStatus.COMPLETED and absent.exit_code != 0
    assert json.loads(absent.stdout) == [], "An owned browser/server container survived cleanup"
    bundle = observed["bundle"]
    assert bundle["request"] == contract.browser_evidence_request.to_snapshot()
    assert bundle["request"]["source_revision_content_hash"] == revision.content_hash
    assert bundle["request"]["source_tree_hash"] == revision.source_tree_hash
    operation = next(item for item in observed["operations"] if item["label"] == "EXECUTE")
    raw = json.loads(reference_bytes(store, operation["stdout_ref"]))
    return browser_results[0], observed, raw, store


def assert_screens_and_evidence(manifest, raw, store, *, route_ids):
    bundle = manifest["bundle"]
    assert tuple(row["route"]["route_id"] for row in bundle["routes"]) == route_ids
    assert len(raw["screens"]) == len(route_ids) * len(VIEWPORTS)
    assert {
        (screen["route_id"], screen["viewport"], screen["width"], screen["height"])
        for screen in raw["screens"]
    } == {
        (route_id, viewport, width, height)
        for route_id in route_ids
        for viewport, width, height in VIEWPORTS
    }
    assert all(screen["status"] == "COLLECTED" for screen in raw["screens"])
    persisted = {reference["sha256_digest"]: reference for reference in nested_references(manifest)}
    for screen in raw["screens"]:
        for name in ("screenshot", "dom", "axe", "events"):
            artifact = screen[name]
            assert artifact["encoding"] == "base64"
            content = base64.b64decode(artifact["content"], validate=True)
            assert len(content) == artifact["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
            assert artifact["sha256"] in persisted
            assert reference_bytes(store, persisted[artifact["sha256"]]) == content
            if name == "screenshot":
                assert content.startswith(b"\x89PNG\r\n\x1a\n")
                assert struct.unpack(">II", content[16:24]) == (screen["width"], screen["height"])
    dimensions = set()
    for route in bundle["routes"]:
        assert route["raw_playwright_ref"] is not None
        assert route["screenshot_ref"] is not None
        assert route["dom_snapshot_ref"] is not None
        assert route["accessibility_report_ref"] is not None
        assert route["accessibility_findings"] == []
        dom = reference_bytes(store, route["dom_snapshot_ref"])
        assert b"Unit6" in dom
    for reference in nested_references(bundle):
        body = reference_bytes(store, reference)
        if reference.get("media_type") == "image/png":
            assert body.startswith(b"\x89PNG\r\n\x1a\n")
            dimensions.add(struct.unpack(">II", body[16:24]))
    # Each route retains its required viewport set in raw evidence as well.
    assert dimensions <= {(width, height) for _, width, height in VIEWPORTS}


def test_real_static_browser_collects_declared_routes_and_both_viewports(tmp_path: Path):
    async def scenario():
        files = {
            "index.html": page("Unit6 static root", "<p>Development fixture root.</p>"),
            "details.html": page("Unit6 static details", "<p>Declared local route.</p>"),
        }
        result, observed, raw, store = await execute_fixture(
            tmp_path, files, routes=(WebBrowserRouteSpec("details", "/details.html"),)
        )
        assert result.status.value == "PASSED", result.to_snapshot()
        assert observed["bundle"]["status"] == "COLLECTED"
        assert_screens_and_evidence(observed, raw, store, route_ids=("root", "details"))

    asyncio.run(scenario())


def test_real_development_calculator_proves_pointer_and_keyboard_activation(tmp_path: Path):
    async def scenario():
        interactions = calculator_interactions()
        result, observed, raw, store = await execute_fixture(
            tmp_path, calculator_files(), interactions=interactions
        )
        assert result.status.value == "PASSED", result.to_snapshot()
        assert observed["bundle"]["status"] == "COLLECTED"
        assert_screens_and_evidence(observed, raw, store, route_ids=("root",))
        for screen in raw["screens"]:
            assert len(screen["actions"]) == 8
            assert all(action["status"] == "PASSED" for action in screen["actions"])
            assert [action["kind"] for action in screen["actions"]] == [
                action.kind for action in interactions[0].actions
            ]
            assert screen["actions"][3]["observed_text"] == "5"
            assert screen["actions"][7]["observed_text"] == "15"
            assert screen["interaction_status"] == "PASSED"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "console-error",
        "page-error",
        "axe",
        "local-request",
        "external-request",
        "bad-route",
        "assertion",
        "shadow-controls",
        "iframe-controls",
        "closed-shadow-controls",
    ],
)
def test_real_browser_failures_preserve_evidence_and_cleanup(tmp_path: Path, case: str):
    async def scenario():
        files = {
            "index.html": page(
                "Unit6 negative development fixture", "<p>Observed failure.</p>", script=True
            )
        }
        scripts = {
            "console-error": "console.error('Unit6 deliberate console error');",
            "page-error": "setTimeout(() => { throw new Error('Unit6 deliberate page error'); }, 0);",
            "axe": "",
            "local-request": "fetch('/missing.json').catch(() => {});",
            "external-request": "fetch('https://example.invalid/unit6-blocked').catch(() => {});",
            "bad-route": "",
            "assertion": "",
            "shadow-controls": (
                "const host = document.createElement('div'); document.querySelector('main').append(host);"
                "host.attachShadow({mode:'open'}).innerHTML='<button>Observed shadow control</button>';"
            ),
            "iframe-controls": (
                "const frame = document.createElement('iframe'); frame.title='Development controls';"
                "frame.srcdoc='<button>Observed frame control</button>';"
                "document.querySelector('main').append(frame);"
            ),
            "closed-shadow-controls": (
                "const host = document.createElement('div'); document.querySelector('main').append(host);"
                "host.attachShadow({mode:'closed'}).innerHTML='<button>Observed closed shadow control</button>';"
            ),
        }
        files["app.js"] = scripts[case]
        routes = ()
        interactions = ()
        if case == "axe":
            files["index.html"] = page(
                "Unit6 accessibility negative control",
                '<img src="/mark.svg" width="32" height="32"><p>Missing alternative text.</p>',
            )
            files["mark.svg"] = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="black"/></svg>'
            )
        elif case == "bad-route":
            routes = (WebBrowserRouteSpec("missing", "/missing.html"),)
        elif case == "assertion":
            files = calculator_files()
            interactions = calculator_interactions(wrong_assertion=True)
        result, observed, raw, store = await execute_fixture(
            tmp_path, files, routes=routes, interactions=interactions
        )
        assert result.status.value == "FAILED", result.to_snapshot()
        assert raw["screens"], "Failure must preserve the actual browser observation"
        for route in observed["bundle"]["routes"]:
            assert reference_bytes(store, route["raw_playwright_ref"])
        if case != "bad-route":
            assert observed["bundle"]["status"] == "COLLECTED"
            assert any(
                route["screenshot_ref"] is not None for route in observed["bundle"]["routes"]
            )
        events = [
            json.loads(base64.b64decode(screen["events"]["content"], validate=True))
            for screen in raw["screens"]
        ]
        if case == "console-error":
            assert all(
                any(
                    message["level"] == "ERROR"
                    and "Unit6 deliberate console error" in message["message"]
                    for message in event["console_messages"]
                )
                for event in events
            )
        elif case == "page-error":
            assert all("Unit6 deliberate page error" in event["page_errors"] for event in events)
        elif case == "axe":
            for screen in raw["screens"]:
                axe = json.loads(base64.b64decode(screen["axe"]["content"], validate=True))
                assert any(finding["id"] == "image-alt" for finding in axe["violations"])
        elif case == "local-request":
            assert all(
                any(
                    request["path"] == "/missing.json"
                    and request["failure_text"] == "HTTP_STATUS_404"
                    for request in event["failed_requests"]
                )
                for event in events
            )
        elif case == "external-request":
            assert all(
                any(
                    request["kind"] == "EXTERNAL_REQUEST"
                    and request["target"] == "https://example.invalid/unit6-blocked"
                    for request in event["blocked_requests"]
                )
                for event in events
            )
        elif case == "bad-route":
            missing = [screen for screen in raw["screens"] if screen["route_id"] == "missing"]
            assert len(missing) == len(VIEWPORTS)
            assert all(
                screen["path"] == "/missing.html" and screen["http_status"] == 404
                for screen in missing
            )
        if case == "assertion":
            assert all(screen["actions"][3]["status"] == "FAILED" for screen in raw["screens"])
            assert all(screen["actions"][3]["observed_text"] == "5" for screen in raw["screens"])
        if case in {"shadow-controls", "iframe-controls", "closed-shadow-controls"}:
            assert all(screen["interaction_status"] == "FAILED" for screen in raw["screens"])
            expected = (
                "INTERACTION_PLAN_REQUIRED"
                if case == "shadow-controls"
                else "INTERACTION_INSPECTION_FAILED"
            )
            assert all(expected in screen["failure_codes"] for screen in raw["screens"])

    asyncio.run(scenario())
