"""Synthetic contract inputs only: no fixture is a claimed browser observation."""

import base64
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from orchestwin.web_execution.static_browser_executor import HARNESS_PATH
from orchestwin.web_execution.static_browser_jobs import VIEWPORTS, canonical_bytes, content_hash
from orchestwin.web_execution.static_browser_validation import FIXTURE_PATH, fixture_job
from orchestwin.web_execution.verified_browser_runner import CHECK_NAMES

ROOT = Path(__file__).resolve().parents[4]
IMAGE_ID = "sha256:" + "a" * 64


def envelope(body):
    if not isinstance(body, bytes):
        body = canonical_bytes(body)
    return {
        "encoding": "base64",
        "content": base64.b64encode(body).decode(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def png_header(width, height):
    # Synthetic header sufficient for the container-output contract unit tests.
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\0" * 13
    )


def make_observation(tmp_path):
    root = tmp_path / "repo"
    evidence = tmp_path / "evidence"
    root.mkdir(parents=True)
    evidence.mkdir()
    harness = (ROOT / HARNESS_PATH).read_bytes()
    (root / HARNESS_PATH).parent.mkdir(parents=True)
    (root / HARNESS_PATH).write_bytes(harness)
    versions = {
        "playwright": "1.62.1",
        "axe_core": "4.13.0",
        "chromium": "test-only",
        "node": "test-only",
    }
    raw = {
        "schema_version": 1,
        "status": "PASSED",
        "uid": 65532,
        "probe_kind": "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE",
        "versions": versions,
        "checks": dict.fromkeys(CHECK_NAMES, True),
        "screens": [],
    }
    files = {}
    for name, width, height in VIEWPORTS:
        screen = {
            "name": name,
            "screenshot": envelope(png_header(width, height)),
            "dom": envelope(b"<html></html>"),
            "axe": envelope({"testEngine": {"version": "4.13.0"}, "violations": []}),
        }
        raw["screens"].append(screen)
        for field, suffix in (("screenshot", "png"), ("dom", "html"), ("axe", "axe.json")):
            files[f"{name}.{suffix}"] = base64.b64decode(screen[field]["content"])
    for field, name, value in (
        ("negative_axe", "negative-control.axe.json", {"violations": [{"id": "button-name"}]}),
        ("package_lock", "package-lock.observed.json", {"unit_test_only": True}),
        ("events", "browser-events.json", []),
    ):
        raw[field] = envelope(value)
        files[name] = base64.b64decode(raw[field]["content"])
    files["BROWSER_PROBE.stdout.log"] = canonical_bytes(raw)
    parent = {"unit_test_only": True}
    parent["content_hash"] = content_hash(parent)
    files["parent-manifest.json"] = canonical_bytes(parent)
    files["seccomp.json"] = b'{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[]}'
    recipes = []
    for name in ("Dockerfile", "package.json", "probe.cjs", "fixture.html", "seccomp.json"):
        relative = f"infra/web-runners/browser-automation/{name}"
        body = files["seccomp.json"] if name == "seccomp.json" else b"trusted-test-recipe"
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(body)
        recipes.append({"path": relative, "sha256": hashlib.sha256(body).hexdigest()})
    manifest = {
        "schema_version": 1,
        "report_type": "LOCAL_BROWSER_AUTOMATION_NOT_FORMAL_EVIDENCE",
        "status": "BROWSER_AUTOMATION_PROBE_PASSED",
        "browser_automation_verified": True,
        "cleanup_confirmed": True,
        "formal_run_started": False,
        "level_d_validated": False,
        "generated_projects_authorized": False,
        "parent_content_hash": parent["content_hash"],
        "platform_commit": "b" * 40,
        "runner": {"image_id": IMAGE_ID, "image_id_kind": "LOCAL_CONFIG_DIGEST"},
        "probe": {"checks": raw["checks"], "versions": versions},
        "recipes": recipes,
        "artifacts": [],
    }
    for name, body in files.items():
        (evidence / name).write_bytes(body)
        manifest["artifacts"].append(
            {"path": name, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        )
    manifest["content_hash"] = content_hash(manifest)
    path = evidence / "manifest.json"
    path.write_bytes(canonical_bytes(manifest))
    fixture = json.loads((ROOT / FIXTURE_PATH).read_bytes())["fixtures"][0]
    job, revision, blobs = fixture_job(
        fixture,
        runner_hash=manifest["content_hash"],
        harness_hash=hashlib.sha256(harness).hexdigest(),
    )
    return root, path, job, manifest, revision, blobs


def inspection_result(job, *, fail=False):
    screens = []
    for scenario in job.scenarios:
        for name, width, height in VIEWPORTS:
            actions = []
            stopped = False
            for index, action in enumerate(scenario.actions):
                state = "NOT_RUN" if stopped else "PASSED"
                value = action.value if action.kind == "expect_text" else None
                if fail and action.kind == "expect_text" and not stopped:
                    state = "FAILED"
                    value = "different"
                    stopped = True
                actions.append(
                    {
                        "index": index,
                        "kind": action.kind,
                        "status": state,
                        "observed_text": value,
                        "failure_code": "TEXT_ASSERTION_FAILED" if state == "FAILED" else None,
                    }
                )
            screens.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "route": scenario.route,
                    "viewport": name,
                    "width": width,
                    "height": height,
                    "status": "FAILED" if fail else "PASSED",
                    "actions": actions,
                    "blocked_requests": 0,
                    "screenshot": envelope(png_header(width, height)),
                    "dom": envelope(b"<html>fixture</html>"),
                    "axe": envelope({"testEngine": {"version": "4.13.0"}, "violations": []}),
                    "events": envelope([]),
                }
            )
    return {
        "schema_version": 1,
        "job_content_hash": job.content_hash,
        "uid": 65532,
        "transport_status": "COMPLETED",
        "status": "FAILED" if fail else "PASSED",
        "chromium_sandbox_requested": True,
        "chromium_no_sandbox_flag_absent": True,
        "versions": {"playwright": "1.62.1", "axe_core": "4.13.0", "chromium": "test-only"},
        "screens": screens,
    }


def response(value=b"", *, code=0):
    if not isinstance(value, bytes):
        value = canonical_bytes(value)
    return SimpleNamespace(status="COMPLETED", exit_code=code, stdout=value, stderr=b"")


class DockerTransport:
    def __init__(self, root, job, *, fail=None, assertions_fail=False):
        self.root = root
        self.job = job
        self.fail = fail
        self.assertions_fail = assertions_fail
        self.calls = []
        self.operation = None

    async def __call__(self, argv, *, timeout=30, stdin_bytes=None):
        self.calls.append((argv, stdin_bytes))
        if argv[0] == "git":
            if "rev-parse" in argv:
                return response(b"c" * 40)
            if "show" in argv:
                return response((self.root / HARNESS_PATH).read_bytes())
            return response()
        if argv[:3] == ("docker", "context", "show"):
            return response(b"desktop-linux")
        if argv[:3] == ("docker", "context", "inspect"):
            return response(
                [{"Endpoints": {"docker": {"Host": "npipe:////./pipe/dockerDesktopLinuxEngine"}}}]
            )
        if "image" in argv:
            return response([{"Id": IMAGE_ID, "Os": "linux", "Architecture": "amd64"}])
        if "create" in argv:
            self.operation = argv[argv.index("--label") + 1].split("=")[1]
            return response(b"container-id")
        if "start" in argv:
            assert stdin_bytes == self.job.wire_bytes()
            if self.fail == "start":
                return response(b"{}", code=1)
            return response(inspection_result(self.job, fail=self.assertions_fail))
        if "container" in argv:
            return response(
                [{"Config": {"Labels": {"org.orchestwin.static-browser": self.operation}}}]
            )
        if "rm" in argv:
            return response(code=1 if self.fail == "cleanup" else 0)
        raise AssertionError(f"Unexpected command family: {argv[:4]}")
