"""Bind governed browser jobs and decode bounded, observed browser evidence."""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit
from uuid import UUID

from orchestwin.sandbox.evidence import SandboxEvidenceStore
from orchestwin.web_execution.browser_evidence import (
    WebAccessibilityFinding,
    WebAccessibilityImpact,
    WebBrowserConsoleLevel,
    WebBrowserConsoleMessage,
    WebBrowserEvidenceBundle,
    WebBrowserEvidencePolicy,
    WebBrowserEvidenceRequest,
    WebBrowserFailedRequest,
    WebBrowserRouteEvidence,
    WebBrowserRouteSpec,
    WebBrowserRouteStatus,
)
from orchestwin.web_execution.reports import WebEvidenceReference, WebNormalizedFinding
from orchestwin.web_execution.static_browser_jobs import (
    VIEWPORTS,
    BrowserAction,
    canonical_bytes,
    content_hash,
)
from orchestwin.web_execution.verified_browser_runner import artifact_bytes, read_json

MAX_BROWSER_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_BROWSER_ARTIFACT_BYTES = 2 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*")
_JOB_KEYS = {
    "schema_version",
    "operation_id",
    "execution_attempt_id",
    "harness_sha256",
    "request",
    "viewports",
    "interactions",
    "job_content_hash",
}
_SCREEN_KEYS = {
    "route_id",
    "path",
    "viewport",
    "width",
    "height",
    "final_path",
    "http_status",
    "failure_codes",
    "actions",
    "interaction_status",
    "interactive_controls",
    "status",
    "screenshot",
    "dom",
    "axe",
    "events",
}
_EVENT_KEYS = {"console_messages", "page_errors", "failed_requests", "blocked_requests", "overflow"}
_SCREEN_FAILURES = {
    "NETWORK_GUARD_FAILED",
    "CHROMIUM_SANDBOX_DISABLED",
    "NAVIGATION_FAILED",
    "DOM_CAPTURE_FAILED",
    "INTERACTION_FAILED",
    "INTERACTION_INSPECTION_FAILED",
    "INTERACTION_PLAN_REQUIRED",
    "FINAL_NAVIGATION_INVALID",
    "OUTPUT_LIMIT_EXCEEDED",
    "SCREENSHOT_CAPTURE_FAILED",
    "ACCESSIBILITY_FINDING_LIMIT_EXCEEDED",
    "AXE_EXECUTION_FAILED",
    "BROWSER_SCREEN_FAILED",
    "BROWSER_CLEANUP_FAILED",
    "EVENT_LIMIT_EXCEEDED",
    "OVERALL_TIMEOUT",
}
_ACTION_FAILURES = {
    "ACTION_FAILED",
    "TEXT_ASSERTION_FAILED",
    "TEXT_ASSERTION_READ_FAILED",
    "ASSERTION_TEXT_LIMIT",
}
_BLOCKED_KINDS = {
    "EXTERNAL_REQUEST",
    "REDIRECT",
    "UNDECLARED_NAVIGATION",
    "INVALID_URL",
    "WEB_SOCKET",
    "POPUP",
    "DOWNLOAD",
    "DIALOG",
}


class WebPhaseBrowserEvidenceError(ValueError):
    """Stable protocol error that does not disclose submitted output or host paths."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WebPhaseBrowserEvidenceError(code)


def _keys(value: object, keys: set[str], code: str) -> dict:
    _require(isinstance(value, dict) and set(value) == keys, code)
    return value


def _text(value: object, *, empty: bool = False) -> str:
    _require(isinstance(value, str) and len(value.encode("utf-8")) <= 2048, "BROWSER_TEXT_LIMIT")
    result = " ".join(value.split())
    _require(bool(result) or empty, "BROWSER_TEXT_INVALID")
    return result


def _path(value: object) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= 512, "BROWSER_ROUTE_INVALID")
    decoded = unquote(value, errors="strict")
    for candidate in (value, decoded):
        parsed = urlsplit(candidate)
        _require(
            not parsed.scheme
            and not parsed.netloc
            and not parsed.fragment
            and candidate.startswith("/")
            and not candidate.startswith("//")
            and "\\" not in candidate
            and not any(ord(char) <= 32 or ord(char) == 127 for char in candidate)
            and all(part not in {".", ".."} for part in parsed.path.split("/")),
            "BROWSER_ROUTE_INVALID",
        )
    return value


@dataclass(frozen=True, slots=True)
class WebBrowserInteraction:
    """One route's explicit pointer and keyboard operations with assertions."""

    route_id: str
    actions: tuple[BrowserAction, ...]

    def __post_init__(self) -> None:
        _require(
            isinstance(self.route_id, str)
            and len(self.route_id) <= 160
            and _IDENTIFIER.fullmatch(self.route_id) is not None,
            "BROWSER_INTERACTION_ROUTE_INVALID",
        )
        _require(
            isinstance(self.actions, tuple) and 1 <= len(self.actions) <= 8,
            "BROWSER_INTERACTION_ACTION_LIMIT",
        )
        pending = None
        checked = set()
        for action in self.actions:
            _require(isinstance(action, BrowserAction), "BROWSER_ACTION_INVALID")
            # Revalidate frozen values too: the job is an execution boundary.
            BrowserAction(action.kind, action.selector, action.value)
            _require(
                not any(ord(char) < 32 or ord(char) == 127 for char in action.selector)
                and len(action.selector.encode("utf-16-le")) <= 320
                and (
                    action.value is None
                    or (
                        "\x00" not in action.value and len(action.value.encode("utf-16-le")) <= 2000
                    )
                ),
                "BROWSER_ACTION_INVALID",
            )
            if action.kind in {"click", "press"}:
                _require(pending is None, "BROWSER_INTERACTION_ASSERTION_REQUIRED")
                if action.kind == "press":
                    _require(action.value in {"Enter", "Space"}, "BROWSER_INTERACTION_KEY_INVALID")
                pending = action.kind
            elif action.kind == "expect_text" and pending is not None:
                checked.add(pending)
                pending = None
        _require(
            pending is None and checked == {"click", "press"},
            "BROWSER_INTERACTION_ASSERTION_REQUIRED",
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "actions": [action.snapshot() for action in self.actions],
        }


def _request(snapshot: object) -> WebBrowserEvidenceRequest:
    snapshot = _keys(
        snapshot,
        {
            "source_revision_content_hash",
            "source_tree_hash",
            "runner_image_digest",
            "base_url",
            "routes",
            "policy",
            "content_hash",
        },
        "BROWSER_REQUEST_INVALID",
    )
    policy = _keys(
        snapshot["policy"],
        {
            "maximum_routes",
            "maximum_console_messages_per_route",
            "maximum_failed_requests_per_route",
            "maximum_accessibility_findings_per_route",
        },
        "BROWSER_POLICY_INVALID",
    )
    for key, maximum in (
        ("maximum_routes", 5),
        ("maximum_console_messages_per_route", 100),
        ("maximum_failed_requests_per_route", 100),
        ("maximum_accessibility_findings_per_route", 200),
    ):
        _require(type(policy[key]) is int and 1 <= policy[key] <= maximum, "BROWSER_POLICY_INVALID")
    _require(
        isinstance(snapshot["routes"], list) and 1 <= len(snapshot["routes"]) <= 5,
        "BROWSER_ROUTES_INVALID",
    )
    routes = []
    for route in snapshot["routes"]:
        _keys(route, {"route_id", "path"}, "BROWSER_ROUTE_INVALID")
        _require(
            isinstance(route["route_id"], str) and len(route["route_id"]) <= 160,
            "BROWSER_ROUTE_INVALID",
        )
        routes.append(WebBrowserRouteSpec(route["route_id"], _path(route["path"])))
    _require(routes[0].route_id == "root", "BROWSER_ROOT_ROUTE_REQUIRED")
    _require(
        isinstance(snapshot["base_url"], str)
        and re.fullmatch(
            r"http://(?:127\.0\.0\.1|localhost):[1-9][0-9]{0,4}/?", snapshot["base_url"]
        )
        is not None,
        "BROWSER_ORIGIN_INVALID",
    )
    result = WebBrowserEvidenceRequest(
        snapshot["source_revision_content_hash"],
        snapshot["source_tree_hash"],
        snapshot["runner_image_digest"],
        snapshot["base_url"],
        tuple(routes),
        WebBrowserEvidencePolicy(**policy),
    )
    _require(result.to_snapshot() == snapshot, "BROWSER_REQUEST_HASH_MISMATCH")
    return result


def create_browser_job(
    request: WebBrowserEvidenceRequest,
    *,
    execution_attempt_id: UUID,
    operation_id: str,
    harness_sha256: str,
    interactions: tuple[WebBrowserInteraction, ...] = (),
) -> dict[str, object]:
    """Create a canonical source-, runner-, request- and attempt-bound browser job."""
    try:
        _require(isinstance(request, WebBrowserEvidenceRequest), "BROWSER_REQUEST_INVALID")
        _request(request.to_snapshot())
        _require(isinstance(execution_attempt_id, UUID), "BROWSER_ATTEMPT_INVALID")
        _require(
            isinstance(operation_id, str)
            and re.fullmatch(r"[0-9a-f]{32}", operation_id) is not None,
            "BROWSER_OPERATION_INVALID",
        )
        _require(
            isinstance(harness_sha256, str) and _SHA.fullmatch(harness_sha256) is not None,
            "BROWSER_HARNESS_HASH_INVALID",
        )
        _require(
            isinstance(interactions, tuple) and len(interactions) <= len(request.routes),
            "BROWSER_INTERACTIONS_INVALID",
        )
        by_route = {}
        for item in interactions:
            _require(isinstance(item, WebBrowserInteraction), "BROWSER_INTERACTIONS_INVALID")
            WebBrowserInteraction(item.route_id, item.actions)
            _require(
                item.route_id not in by_route
                and item.route_id in {route.route_id for route in request.routes},
                "BROWSER_INTERACTION_ROUTE_INVALID",
            )
            by_route[item.route_id] = item
        result = {
            "schema_version": 1,
            "operation_id": operation_id,
            "execution_attempt_id": str(execution_attempt_id),
            "request": request.to_snapshot(),
            "harness_sha256": harness_sha256,
            "viewports": [
                {"name": name, "width": width, "height": height}
                for name, width, height in VIEWPORTS
            ],
            "interactions": [
                by_route[route.route_id].to_snapshot()
                for route in request.routes
                if route.route_id in by_route
            ],
        }
        result["job_content_hash"] = content_hash(result)
        _require(len(canonical_bytes(result)) <= 65536, "BROWSER_JOB_INPUT_LIMIT")
        return result
    except WebPhaseBrowserEvidenceError:
        raise
    except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
        raise WebPhaseBrowserEvidenceError("BROWSER_JOB_INVALID") from None


def _validate_job(job: object) -> tuple[WebBrowserEvidenceRequest, dict[str, list]]:
    _keys(job, _JOB_KEYS, "BROWSER_JOB_INVALID")
    _require(
        type(job["schema_version"]) is int and job["schema_version"] == 1,
        "BROWSER_JOB_VERSION_INVALID",
    )
    request = _request(job["request"])
    _require(isinstance(job["interactions"], list), "BROWSER_INTERACTIONS_INVALID")
    interactions = []
    for item in job["interactions"]:
        _keys(item, {"route_id", "actions"}, "BROWSER_INTERACTIONS_INVALID")
        _require(isinstance(item["actions"], list), "BROWSER_INTERACTIONS_INVALID")
        for action in item["actions"]:
            _keys(action, {"kind", "selector", "value"}, "BROWSER_ACTION_INVALID")
        interactions.append(
            WebBrowserInteraction(
                item["route_id"], tuple(BrowserAction(**action) for action in item["actions"])
            )
        )
    expected = create_browser_job(
        request,
        execution_attempt_id=UUID(job["execution_attempt_id"]),
        operation_id=job["operation_id"],
        harness_sha256=job["harness_sha256"],
        interactions=tuple(interactions),
    )
    _require(expected == job, "BROWSER_JOB_HASH_MISMATCH")
    return request, {item["route_id"]: item["actions"] for item in job["interactions"]}


@dataclass(frozen=True, slots=True)
class DecodedWebBrowserEvidence:
    """Collection completeness and observed failures are deliberately separate."""

    bundle: WebBrowserEvidenceBundle
    artifact_refs: tuple[WebEvidenceReference, ...]
    findings: tuple[WebNormalizedFinding, ...]
    failed: bool
    metadata: dict[str, object]


def _png(data: bytes, width: int, height: int) -> None:
    """Check the complete PNG structure and bounded pixel stream, not just IHDR."""
    _require(data.startswith(b"\x89PNG\r\n\x1a\n"), "BROWSER_PNG_INVALID")
    offset = 8
    kinds = []
    pixels = bytearray()
    stride = 0
    while offset < len(data):
        _require(offset + 12 <= len(data), "BROWSER_PNG_TRUNCATED")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        _require(end <= len(data), "BROWSER_PNG_TRUNCATED")
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : end - 4]
        crc = struct.unpack(">I", data[end - 4 : end])[0]
        _require(
            re.fullmatch(rb"[A-Za-z]{2}[A-Z][A-Za-z]", kind) is not None
            and (kind[0] >= ord("a") or kind in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}),
            "BROWSER_PNG_CHUNK_INVALID",
        )
        _require(zlib.crc32(kind + body) == crc, "BROWSER_PNG_CRC_INVALID")
        if not kinds:
            _require(kind == b"IHDR" and length == 13, "BROWSER_PNG_HEADER_INVALID")
            w, h, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            _require(
                (w, h) == (width, height)
                and color in channels
                and depth in depths[color]
                and compression == filtering == interlace == 0,
                "BROWSER_PNG_DIMENSIONS_INVALID",
            )
            stride = (width * channels[color] * depth + 7) // 8 + 1
        elif kind == b"IHDR":
            raise WebPhaseBrowserEvidenceError("BROWSER_PNG_HEADER_INVALID")
        if kind == b"IDAT":
            _require(
                b"IDAT" not in kinds or kinds[-1] == b"IDAT", "BROWSER_PNG_CHUNK_ORDER_INVALID"
            )
            pixels.extend(body)
        if kind == b"PLTE":
            _require(
                b"PLTE" not in kinds
                and b"IDAT" not in kinds
                and 0 < length <= 768
                and length % 3 == 0,
                "BROWSER_PNG_PALETTE_INVALID",
            )
        if kind == b"IEND":
            _require(length == 0 and end == len(data), "BROWSER_PNG_TRAILING_DATA")
        kinds.append(kind)
        offset = end
    _require(kinds and kinds[-1] == b"IEND" and b"IDAT" in kinds, "BROWSER_PNG_INCOMPLETE")
    _require(color != 3 or b"PLTE" in kinds, "BROWSER_PNG_PALETTE_INVALID")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(pixels, stride * height + 1)
    _require(
        len(raw) == stride * height
        and decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and all(raw[index] <= 4 for index in range(0, len(raw), stride)),
        "BROWSER_PNG_PIXELS_INVALID",
    )


def _codes(value: object) -> list[str]:
    _require(
        isinstance(value, list)
        and len(value) <= 32
        and all(isinstance(code, str) and code in _SCREEN_FAILURES for code in value),
        "BROWSER_FAILURE_CODES_INVALID",
    )
    _require(value == sorted(set(value)), "BROWSER_FAILURE_CODES_INVALID")
    return value


def _actions(screen: dict, plan: list) -> None:
    records = screen["actions"]
    _require(
        isinstance(records, list) and len(records) == len(plan), "BROWSER_ACTION_RESULTS_INVALID"
    )
    failed = False
    for index, (record, action) in enumerate(zip(records, plan, strict=True)):
        _keys(
            record,
            {"index", "kind", "status", "observed_text", "failure_code"},
            "BROWSER_ACTION_RESULT_INVALID",
        )
        _require(
            type(record["index"]) is int
            and record["index"] == index
            and record["kind"] == action["kind"],
            "BROWSER_ACTION_BINDING_MISMATCH",
        )
        status = record["status"]
        _require(status in {"PASSED", "FAILED", "NOT_RUN"}, "BROWSER_ACTION_STATUS_INVALID")
        if record["observed_text"] is not None:
            _require(
                isinstance(record["observed_text"], str)
                and len(record["observed_text"].encode("utf-16-le")) <= 2000,
                "BROWSER_ASSERTION_TEXT_LIMIT",
            )
            _require(action["kind"] == "expect_text", "BROWSER_ACTION_OBSERVATION_INVALID")
        if status == "PASSED":
            _require(not failed and record["failure_code"] is None, "BROWSER_ACTION_FALSE_PASS")
            if action["kind"] == "expect_text":
                _require(
                    record["observed_text"] == action["value"], "BROWSER_ACTION_FALSE_ASSERTION"
                )
        else:
            if status == "NOT_RUN":
                _require(
                    record["observed_text"] is None
                    and record["failure_code"] is None
                    and (failed or bool(screen["failure_codes"])),
                    "BROWSER_ACTION_FALSE_NOT_RUN",
                )
            else:
                _require(
                    not failed and record["failure_code"] in _ACTION_FAILURES,
                    "BROWSER_ACTION_PREFIX_INVALID",
                )
                _require(
                    (action["kind"] == "expect_text")
                    == (record["failure_code"] != "ACTION_FAILED"),
                    "BROWSER_ACTION_FAILURE_INVALID",
                )
            failed = True
    controls = screen["interactive_controls"]
    _require(
        controls is None or (type(controls) is int and 0 <= controls <= 100000),
        "BROWSER_INTERACTIVE_CONTROLS_INVALID",
    )
    status = screen["interaction_status"]
    if status == "NOT_APPLICABLE":
        _require(not plan and controls == 0, "BROWSER_INTERACTION_FALSE_NOT_APPLICABLE")
    elif status == "PASSED":
        _require(bool(plan) and not failed, "BROWSER_INTERACTION_FALSE_PASS")
    else:
        _require(
            status == "FAILED" and bool(screen["failure_codes"]),
            "BROWSER_INTERACTION_FAILURE_INVALID",
        )


def _events(data: bytes, policy: WebBrowserEvidencePolicy):
    value = _keys(read_json(data), _EVENT_KEYS, "BROWSER_EVENTS_INVALID")
    limits = {
        "console_messages": policy.maximum_console_messages_per_route,
        "failed_requests": policy.maximum_failed_requests_per_route,
        "page_errors": 100,
        "blocked_requests": 100,
    }
    for key, maximum in limits.items():
        _require(isinstance(value[key], list) and len(value[key]) <= maximum, "BROWSER_EVENT_LIMIT")
    _require(type(value["overflow"]) is bool, "BROWSER_OVERFLOW_INVALID")
    console = []
    requests = []
    findings = []
    for item in value["console_messages"]:
        _keys(item, {"level", "message", "location"}, "BROWSER_CONSOLE_INVALID")
        console.append(
            WebBrowserConsoleMessage(
                WebBrowserConsoleLevel(item["level"]),
                _text(item["message"]),
                None if item["location"] is None else _text(item["location"]),
            )
        )
    for item in value["failed_requests"]:
        _keys(item, {"method", "path", "failure_text"}, "BROWSER_FAILED_REQUEST_INVALID")
        requests.append(
            WebBrowserFailedRequest(
                item["method"], _path(item["path"]), _text(item["failure_text"])
            )
        )
    for message in value["page_errors"]:
        findings.append(WebNormalizedFinding("BROWSER_PAGE_ERROR", _text(message), "playwright"))
    for item in value["blocked_requests"]:
        _keys(item, {"kind", "target"}, "BROWSER_BLOCKED_REQUEST_INVALID")
        _require(
            isinstance(item["kind"], str) and item["kind"] in _BLOCKED_KINDS,
            "BROWSER_BLOCKED_REQUEST_INVALID",
        )
        findings.append(
            WebNormalizedFinding(
                "BROWSER_REQUEST_BLOCKED", _text(item["kind"]), "playwright", _text(item["target"])
            )
        )
    if value["overflow"]:
        findings.append(
            WebNormalizedFinding(
                "BROWSER_EVIDENCE_OVERFLOW",
                "Browser event evidence exceeded its explicit bound.",
                "playwright",
            )
        )
    return value, console, requests, findings


def _axe(data: bytes, policy: WebBrowserEvidencePolicy) -> list[WebAccessibilityFinding]:
    value = read_json(data)
    _require(
        isinstance(value, dict)
        and isinstance(value.get("testEngine"), dict)
        and value["testEngine"].get("version") == "4.13.0"
        and isinstance(value.get("violations"), list),
        "BROWSER_AXE_INVALID",
    )
    _require(
        len(value["violations"]) <= policy.maximum_accessibility_findings_per_route,
        "BROWSER_AXE_LIMIT",
    )
    findings = []
    for item in value["violations"]:
        _require(
            isinstance(item, dict)
            and isinstance(item.get("nodes"), list)
            and 1 <= len(item["nodes"]) <= 1000,
            "BROWSER_AXE_FINDING_INVALID",
        )
        targets = []
        for node in item["nodes"]:
            _require(
                isinstance(node, dict)
                and isinstance(node.get("target"), list)
                and 1 <= len(node["target"]) <= 100,
                "BROWSER_AXE_TARGET_INVALID",
            )
            for target in node["target"]:
                if isinstance(target, list):
                    _require(
                        1 <= len(target) <= 100 and all(isinstance(part, str) for part in target),
                        "BROWSER_AXE_TARGET_INVALID",
                    )
                    target = canonical_bytes(target).decode("utf-8")
                targets.append(_text(target))
        impact = item.get("impact")
        _require(
            impact is None or impact in {"critical", "serious", "moderate", "minor"},
            "BROWSER_AXE_IMPACT_INVALID",
        )
        findings.append(
            WebAccessibilityFinding(
                item["id"],
                WebAccessibilityImpact("UNKNOWN" if impact is None else impact.upper()),
                _text(item["description"]),
                _text(item["help"]),
                tuple(sorted(set(targets))),
            )
        )
    return findings


class _Artifacts:
    def __init__(self, store: SandboxEvidenceStore, run_id: UUID, operation_id: str):
        self.store, self.run_id, self.operation_id = store, run_id, operation_id
        self.refs: set[WebEvidenceReference] = set()
        self.inventory: list[dict] = []

    def put(
        self, path: str, content: bytes, media_type: str = "application/json"
    ) -> WebEvidenceReference:
        artifact = self.store.store_artifact(
            run_id=self.run_id,
            command_id=f"browser-{self.operation_id}",
            normalized_path=f"browser/{self.operation_id}/{path}",
            content=content,
            media_type=media_type,
        )
        ref = WebEvidenceReference(
            artifact.storage_key, artifact.sha256_digest, artifact.size_bytes, artifact.media_type
        )
        _require(
            ref.sha256_digest == hashlib.sha256(content).hexdigest()
            and ref.size_bytes == len(content)
            and ref.media_type == media_type,
            "BROWSER_STORED_ARTIFACT_MISMATCH",
        )
        self.refs.add(ref)
        self.inventory.append(
            {"path": f"browser/{self.operation_id}/{path}", "ref": ref.to_snapshot()}
        )
        return ref


def decode_browser_evidence(
    raw: bytes, *, job: dict, store: SandboxEvidenceStore, run_id: UUID
) -> DecodedWebBrowserEvidence:
    """Decode exact harness bytes without manufacturing success or absent artifacts."""
    try:
        return _decode(raw, job=job, store=store, run_id=run_id)
    except WebPhaseBrowserEvidenceError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
        struct.error,
        zlib.error,
    ):
        raise WebPhaseBrowserEvidenceError("BROWSER_EVIDENCE_INVALID") from None


def _decode(
    raw: bytes, *, job: dict, store: SandboxEvidenceStore, run_id: UUID
) -> DecodedWebBrowserEvidence:
    _require(
        isinstance(raw, bytes) and 0 < len(raw) <= MAX_BROWSER_OUTPUT_BYTES, "BROWSER_OUTPUT_LIMIT"
    )
    _require(isinstance(run_id, UUID), "BROWSER_RUN_ID_INVALID")
    request, plans = _validate_job(job)
    output = _keys(
        read_json(raw),
        {
            "schema_version",
            "job_content_hash",
            "request_content_hash",
            "operation_id",
            "execution_attempt_id",
            "harness_sha256",
            "uid",
            "versions",
            "chromium_sandbox_requested",
            "chromium_no_sandbox_flag_absent",
            "transport_status",
            "screens",
        },
        "BROWSER_OUTPUT_INVALID",
    )
    _require(
        type(output["schema_version"]) is int
        and output["schema_version"] == 1
        and type(output["uid"]) is int
        and output["uid"] == 65532
        and output["chromium_sandbox_requested"] is True
        and type(output["chromium_no_sandbox_flag_absent"]) is bool
        and output["transport_status"] == "COMPLETED",
        "BROWSER_EXECUTION_OBSERVATION_INVALID",
    )
    for key in ("job_content_hash", "operation_id", "execution_attempt_id", "harness_sha256"):
        _require(output[key] == job[key], "BROWSER_OUTPUT_BINDING_MISMATCH")
    _require(
        output["request_content_hash"] == request.content_hash, "BROWSER_OUTPUT_BINDING_MISMATCH"
    )
    versions = _keys(
        output["versions"], {"playwright", "axe_core", "chromium"}, "BROWSER_VERSIONS_INVALID"
    )
    _require(
        versions["playwright"] == "1.62.1"
        and versions["axe_core"] == "4.13.0"
        and isinstance(versions["chromium"], str)
        and re.fullmatch(r"\d{1,4}(?:\.\d{1,6}){3}", versions["chromium"]) is not None,
        "BROWSER_VERSIONS_INVALID",
    )
    _require(
        isinstance(output["screens"], list)
        and len(output["screens"]) == len(request.routes) * len(VIEWPORTS),
        "BROWSER_GRID_INVALID",
    )
    artifacts = _Artifacts(store, run_id, job["operation_id"])
    job_ref = artifacts.put("job.json", canonical_bytes(job))
    report_ref = artifacts.put("raw-report.json", raw)
    route_results = []
    screen_metadata = []
    extra_findings = []
    failed = False
    if not output["chromium_no_sandbox_flag_absent"]:
        extra_findings.append(
            WebNormalizedFinding(
                "BROWSER_SANDBOX_UNVERIFIED",
                "The browser sandbox observation was not verified for every screen.",
                "playwright",
            )
        )
    for route_index, route in enumerate(request.routes):
        route_views = []
        console, requests, accessibility = [], [], []
        route_failed = False
        route_codes = set()
        for viewport_index, (viewport, width, height) in enumerate(VIEWPORTS):
            screen = _keys(
                output["screens"][route_index * len(VIEWPORTS) + viewport_index],
                _SCREEN_KEYS,
                "BROWSER_SCREEN_INVALID",
            )
            _require(
                (screen["route_id"], screen["path"], screen["viewport"])
                == (route.route_id, route.path, viewport)
                and type(screen["width"]) is int
                and type(screen["height"]) is int
                and (screen["width"], screen["height"]) == (width, height),
                "BROWSER_GRID_BINDING_MISMATCH",
            )
            codes = _codes(screen["failure_codes"])
            route_codes.update(codes)
            _actions(screen, plans.get(route.route_id, []))
            if screen["final_path"] is not None:
                _path(screen["final_path"])
                _require(
                    screen["final_path"] in {item.path for item in request.routes},
                    "BROWSER_FINAL_ROUTE_UNDECLARED",
                )
            status = screen["http_status"]
            _require(
                status is None or (type(status) is int and 100 <= status <= 599),
                "BROWSER_HTTP_STATUS_INVALID",
            )
            complete = all(screen[key] is not None for key in ("screenshot", "dom", "axe"))
            _require(
                screen["status"] == ("COLLECTED" if complete else "FAILED"),
                "BROWSER_COLLECTION_STATUS_INVALID",
            )
            if not complete or screen["final_path"] is None or status is None:
                _require(bool(codes), "BROWSER_COLLECTION_FAILURE_MISSING")
                route_failed = True
            view_refs = {}
            for key, extension, media_type in (
                ("screenshot", "png", "image/png"),
                ("dom", "html", "text/html"),
                ("axe", "axe.json", "application/json"),
                ("events", "events.json", "application/json"),
            ):
                if screen[key] is None:
                    _require(key != "events", "BROWSER_EVENTS_MISSING")
                    view_refs[key] = None
                    continue
                data = artifact_bytes(screen[key], maximum=MAX_BROWSER_ARTIFACT_BYTES)
                if key == "screenshot":
                    _png(data, width, height)
                elif key == "dom":
                    _require(
                        "<html" in data.decode("utf-8").lower() and b"\x00" not in data,
                        "BROWSER_DOM_INVALID",
                    )
                elif key == "axe":
                    accessibility.extend(_axe(data, request.policy))
                else:
                    event, observed_console, observed_requests, observed_findings = _events(
                        data, request.policy
                    )
                    console.extend(observed_console)
                    requests.extend(observed_requests)
                    extra_findings.extend(observed_findings)
                ref = artifacts.put(f"{route.route_id}.{viewport}.{extension}", data, media_type)
                view_refs[key] = ref.to_snapshot()
            for code in codes:
                extra_findings.append(
                    WebNormalizedFinding(
                        code, "Browser automation reported a failure.", "playwright", route.path
                    )
                )
            failed |= bool(codes) or screen["interaction_status"] == "FAILED" or status != 200
            if status is not None and status != 200:
                extra_findings.append(
                    WebNormalizedFinding(
                        "BROWSER_HTTP_STATUS_FAILED",
                        f"Browser navigation observed HTTP status {status}.",
                        "playwright",
                        route.path,
                    )
                )
            metadata = {
                key: screen[key]
                for key in screen
                if key not in {"screenshot", "dom", "axe", "events"}
            }
            metadata.update(artifacts=view_refs, overflow=event["overflow"])
            route_views.append(metadata)
            screen_metadata.append(metadata)
        # Limits apply to every raw observation across both viewports, before deduplication.
        _require(
            len(console) <= request.policy.maximum_console_messages_per_route
            and len(requests) <= request.policy.maximum_failed_requests_per_route
            and len(accessibility) <= request.policy.maximum_accessibility_findings_per_route,
            "BROWSER_ROUTE_POLICY_LIMIT",
        )
        route_raw_ref = artifacts.put(
            f"{route.route_id}.playwright.json",
            canonical_bytes(
                {
                    "request_content_hash": request.content_hash,
                    "job_content_hash": job["job_content_hash"],
                    "route": route.to_snapshot(),
                    "screens": route_views,
                }
            ),
        )
        wide = route_views[-1]

        def primary(name, wide=wide):
            value = wide["artifacts"][name]
            return None if value is None else WebEvidenceReference(**value)

        route_results.append(
            WebBrowserRouteEvidence(
                route,
                WebBrowserRouteStatus.FAILED if route_failed else WebBrowserRouteStatus.COLLECTED,
                wide["final_path"],
                primary("screenshot"),
                primary("dom"),
                route_raw_ref,
                primary("axe"),
                tuple(
                    sorted(
                        set(console),
                        key=lambda item: (item.level, item.message, item.location or ""),
                    )
                ),
                tuple(sorted(set(requests))),
                tuple(sorted(set(accessibility))),
                sorted(route_codes)[0] if route_failed else None,
                "Browser route evidence collection was incomplete." if route_failed else None,
            )
        )
    bundle = WebBrowserEvidenceBundle(request, tuple(route_results))
    findings = tuple(
        sorted(
            set((*bundle.normalized_findings(), *extra_findings)),
            key=lambda item: (item.code, item.source_tool, item.location or "", item.message),
        )
    )
    failed |= bool(findings) or any(
        item.status is WebBrowserRouteStatus.FAILED for item in route_results
    )
    bundle_ref = artifacts.put("bundle.json", canonical_bytes(bundle.to_snapshot()))
    metadata = {
        "job_ref": job_ref.to_snapshot(),
        "raw_report_ref": report_ref.to_snapshot(),
        "bundle_ref": bundle_ref.to_snapshot(),
        "versions": versions,
        "screens": screen_metadata,
        "chromium_sandbox_requested": output["chromium_sandbox_requested"],
        "chromium_no_sandbox_flag_absent": output["chromium_no_sandbox_flag_absent"],
        "generated_artifacts": sorted(artifacts.inventory, key=lambda item: item["path"]),
        "request_content_hash": request.content_hash,
        "job_content_hash": job["job_content_hash"],
    }
    return DecodedWebBrowserEvidence(
        bundle, tuple(sorted(artifacts.refs)), findings, failed, metadata
    )
