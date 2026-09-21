"""Strict browser protocol tests; generated envelopes are transport fixtures only."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import struct
import zlib
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.web_execution.browser_evidence import (
    WebBrowserEvidencePolicy,
    WebBrowserEvidenceStatus,
    WebBrowserRouteSpec,
    create_web_browser_evidence_request,
)
from orchestwin.web_execution.phase_browser_evidence import (
    WebBrowserInteraction,
    WebPhaseBrowserEvidenceError,
    create_browser_job,
    decode_browser_evidence,
)
from orchestwin.web_execution.static_browser_jobs import (
    BrowserAction,
    canonical_bytes,
    content_hash,
)

ATTEMPT = UUID("12345678-1234-4123-8123-123456789abc")
POLICY = WebBrowserEvidencePolicy()


def request(*routes, policy=POLICY):
    return create_web_browser_evidence_request(
        source_revision_content_hash="a" * 64,
        source_tree_hash="b" * 64,
        runner_image_digest="c" * 64,
        base_url="http://127.0.0.1:4173",
        declared_routes=routes,
        policy=policy,
    )


def actions():
    return (
        BrowserAction("click", "button"),
        BrowserAction("expect_text", "output", "1"),
        BrowserAction("press", "button", "Enter"),
        BrowserAction("expect_text", "output", "2"),
    )


def job(*routes, interactions=(), policy=POLICY):
    return create_browser_job(
        request(*routes, policy=policy),
        execution_attempt_id=ATTEMPT,
        operation_id="d" * 32,
        harness_sha256="e" * 64,
        interactions=interactions,
    )


def envelope(data):
    return {
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def png(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * (height * (width * 3 + 1))))
        + chunk(b"IEND", b"")
    )


def events():
    return {
        "console_messages": [],
        "page_errors": [],
        "failed_requests": [],
        "blocked_requests": [],
        "overflow": False,
    }


def report(value):
    result = {
        "schema_version": 1,
        **{
            key: value[key]
            for key in (
                "job_content_hash",
                "operation_id",
                "execution_attempt_id",
                "harness_sha256",
            )
        },
        "request_content_hash": value["request"]["content_hash"],
        "uid": 65532,
        "versions": {"playwright": "1.62.1", "axe_core": "4.13.0", "chromium": "148.0.7778.96"},
        "chromium_sandbox_requested": True,
        "chromium_no_sandbox_flag_absent": True,
        "transport_status": "COMPLETED",
        "screens": [],
    }
    plans = {item["route_id"]: item["actions"] for item in value["interactions"]}
    for route in value["request"]["routes"]:
        for viewport in value["viewports"]:
            plan = plans.get(route["route_id"], [])
            result["screens"].append(
                {
                    **route,
                    "viewport": viewport["name"],
                    "width": viewport["width"],
                    "height": viewport["height"],
                    "final_path": route["path"],
                    "http_status": 200,
                    "status": "COLLECTED",
                    "interactive_controls": 1 if plan else 0,
                    "interaction_status": "PASSED" if plan else "NOT_APPLICABLE",
                    "failure_codes": [],
                    "actions": [
                        {
                            "index": index,
                            "kind": action["kind"],
                            "status": "PASSED",
                            "observed_text": action["value"]
                            if action["kind"] == "expect_text"
                            else None,
                            "failure_code": None,
                        }
                        for index, action in enumerate(plan)
                    ],
                    "screenshot": envelope(png(viewport["width"], viewport["height"])),
                    "dom": envelope(b"<!doctype html><html><body>fixture</body></html>"),
                    "axe": envelope(
                        canonical_bytes(
                            {
                                "testEngine": {"name": "axe-core", "version": "4.13.0"},
                                "violations": [],
                            }
                        )
                    ),
                    "events": envelope(canonical_bytes(events())),
                }
            )
    return result


def decode(tmp_path, value, output):
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    result = decode_browser_evidence(
        canonical_bytes(output), job=value, store=store, run_id=ATTEMPT
    )
    return result, store


def test_job_canonically_binds_request_attempt_harness_and_interaction_plan():
    value = job(interactions=(WebBrowserInteraction("root", actions()),))
    assert value["request"] == request().to_snapshot()
    assert value["execution_attempt_id"] == str(ATTEMPT)
    assert value["job_content_hash"] == content_hash(
        {key: item for key, item in value.items() if key != "job_content_hash"}
    )
    assert value["viewports"] == [
        {"name": "narrow", "width": 390, "height": 844},
        {"name": "wide", "width": 1280, "height": 800},
    ]
    assert value != job()


@pytest.mark.parametrize(
    "plan",
    [
        actions()[:2],
        (actions()[0], *actions()[2:]),
        (BrowserAction("press", "button", "Tab"), *actions()[1:]),
        actions() * 3,
    ],
)
def test_interactions_require_pointer_and_keyboard_with_independent_assertions(plan):
    with pytest.raises(WebPhaseBrowserEvidenceError):
        job(interactions=(WebBrowserInteraction("root", plan),))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda: job(interactions=(WebBrowserInteraction("other", actions()),)),
        lambda: job(interactions=(WebBrowserInteraction("root", actions()),) * 2),
        lambda: create_browser_job(
            request(),
            execution_attempt_id=ATTEMPT,
            operation_id="unsafe/path",
            harness_sha256="e" * 64,
        ),
        lambda: job(
            policy=replace(WebBrowserEvidencePolicy(), maximum_console_messages_per_route=1.5)
        ),
        lambda: job(
            policy=replace(WebBrowserEvidencePolicy(), maximum_console_messages_per_route=101)
        ),
    ],
)
def test_invalid_job_parameters_fail_closed(mutate):
    with pytest.raises(WebPhaseBrowserEvidenceError):
        mutate()


def test_complete_grid_stores_every_original_artifact_and_uses_wide_primary(tmp_path):
    value = job(WebBrowserRouteSpec("details", "/details"))
    output = report(value)
    result, store = decode(tmp_path, value, output)
    assert result.failed is False
    assert result.bundle.status is WebBrowserEvidenceStatus.COLLECTED
    assert len(result.metadata["screens"]) == 4
    for screen, metadata in zip(output["screens"], result.metadata["screens"], strict=True):
        assert metadata["route_id"] == screen["route_id"]
        for name in ("screenshot", "dom", "axe", "events"):
            ref = metadata["artifacts"][name]
            assert store.read(ref["storage_key"]) == base64.b64decode(screen[name]["content"])
    for route in result.bundle.routes:
        views = [
            item for item in result.metadata["screens"] if item["route_id"] == route.route.route_id
        ]
        assert route.screenshot_ref.to_snapshot() == views[1]["artifacts"]["screenshot"]
        raw = json.loads(store.read(route.raw_playwright_ref.storage_key))
        assert raw["screens"] == views
    assert store.read(result.metadata["job_ref"]["storage_key"]) == canonical_bytes(value)
    assert (
        json.loads(store.read(result.metadata["bundle_ref"]["storage_key"]))
        == result.bundle.to_snapshot()
    )
    # Identical DOM bytes remain attributable to each route and viewport.
    assert (
        len(
            [
                item
                for item in result.metadata["generated_artifacts"]
                if item["path"].endswith(".html")
            ]
        )
        == 4
    )


@pytest.mark.parametrize("kind", ["console", "pageerror", "request", "blocked", "axe", "overflow"])
def test_complete_collection_never_means_pass_with_observed_errors(tmp_path, kind):
    value = job()
    output = report(value)
    event = events()
    if kind == "console":
        event["console_messages"] = [
            {"level": "ERROR", "message": "application failed", "location": None}
        ]
    elif kind == "pageerror":
        event["page_errors"] = ["uncaught error"]
    elif kind == "request":
        event["failed_requests"] = [
            {"method": "GET", "path": "/api", "failure_text": "connection reset"}
        ]
    elif kind == "blocked":
        event["blocked_requests"] = [
            {"kind": "EXTERNAL_REQUEST", "target": "https://example.test/"}
        ]
    elif kind == "overflow":
        event["overflow"] = True
        output["screens"][0]["failure_codes"] = ["EVENT_LIMIT_EXCEEDED"]
    else:
        output["screens"][0]["axe"] = envelope(
            canonical_bytes(
                {
                    "testEngine": {"version": "4.13.0"},
                    "violations": [
                        {
                            "id": "button-name",
                            "impact": "serious",
                            "description": "Buttons require names",
                            "help": "Name the button",
                            "nodes": [{"target": ["button"]}],
                        }
                    ],
                }
            )
        )
    output["screens"][0]["events"] = envelope(canonical_bytes(event))
    result, _ = decode(tmp_path, value, output)
    assert result.failed is True
    assert result.bundle.status is WebBrowserEvidenceStatus.COLLECTED
    assert result.findings


def test_failed_actions_preserve_observed_prefix_and_not_run_tail(tmp_path):
    value = job(interactions=(WebBrowserInteraction("root", actions()),))
    output = report(value)
    screen = output["screens"][0]
    screen["actions"][1].update(
        status="FAILED", observed_text="wrong", failure_code="TEXT_ASSERTION_FAILED"
    )
    for action in screen["actions"][2:]:
        action.update(status="NOT_RUN", observed_text=None, failure_code=None)
    screen.update(interaction_status="FAILED", failure_codes=["INTERACTION_FAILED"])
    result, _ = decode(tmp_path, value, output)
    assert result.failed is True
    assert result.metadata["screens"][0]["actions"] == screen["actions"]


def test_failed_route_keeps_partial_artifacts_and_raw_manifest(tmp_path):
    value = job(WebBrowserRouteSpec("details", "/details"))
    output = report(value)
    for screen in output["screens"][2:]:
        screen.update(
            status="FAILED",
            screenshot=None,
            dom=None,
            axe=None,
            final_path=None,
            http_status=None,
            interactive_controls=None,
            interaction_status="FAILED",
            failure_codes=["NAVIGATION_FAILED"],
        )
    result, store = decode(tmp_path, value, output)
    assert result.failed is True
    assert result.bundle.status is WebBrowserEvidenceStatus.PARTIAL
    assert result.bundle.routes[1].screenshot_ref is None
    assert store.read(result.bundle.routes[1].raw_playwright_ref.storage_key)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda output: output.update(job_content_hash="0" * 64),
        lambda output: output.update(request_content_hash="0" * 64),
        lambda output: output.update(uid=True),
        lambda output: output.update(extra=True),
        lambda output: output["versions"].update(playwright="1.0.0"),
        lambda output: output["screens"].pop(),
        lambda output: output["screens"].reverse(),
        lambda output: output["screens"][0].update(interactive_controls=1),
        lambda output: output["screens"][0].update(screenshot=None),
        lambda output: output["screens"][0].update(final_path="https://example.test/"),
        lambda output: output["screens"][0]["screenshot"].update(sha256="f" * 64),
    ],
)
def test_malformed_or_forged_reports_fail_closed(tmp_path, mutate):
    value = job()
    output = report(value)
    mutate(output)
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


@pytest.mark.parametrize(
    "make_png",
    [
        lambda: png(1, 1),
        lambda: png(390, 844)[:-12],
        lambda: png(390, 844) + b"trailing",
        lambda: b"\x89PNG\r\n\x1a\n" + b"\0" * 30,
    ],
)
def test_png_integrity_requires_complete_real_image_not_only_a_header(tmp_path, make_png):
    value = job()
    output = report(value)
    output["screens"][0]["screenshot"] = envelope(make_png())
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}', b"{", b"NaN", b"\xff"])
def test_invalid_json_rejects_without_inventing_evidence(tmp_path, raw):
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode_browser_evidence(
            raw, job=job(), store=FileSystemSandboxEvidenceStore(tmp_path), run_id=ATTEMPT
        )


def test_policy_applies_to_combined_viewport_observations(tmp_path):
    value = job(policy=replace(WebBrowserEvidencePolicy(), maximum_console_messages_per_route=1))
    output = report(value)
    for index, screen in enumerate(output["screens"]):
        event = events()
        event["console_messages"] = [
            {"level": "INFO", "message": f"message {index}", "location": None}
        ]
        screen["events"] = envelope(canonical_bytes(event))
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


def test_passed_assertion_must_match_observed_text(tmp_path):
    value = job(interactions=(WebBrowserInteraction("root", actions()),))
    output = report(value)
    output["screens"][0]["actions"][1]["observed_text"] = "not expected"
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


def test_decoder_revalidates_job_hash_after_creation(tmp_path):
    value = job()
    output = report(value)
    changed = copy.deepcopy(value)
    changed["request"]["source_tree_hash"] = "f" * 64
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, changed, output)


def test_navigation_failure_retains_complete_captures_without_forged_route_success(tmp_path):
    value = job()
    output = report(value)
    output["screens"][0].update(
        final_path=None,
        http_status=None,
        interaction_status="FAILED",
        failure_codes=["FINAL_NAVIGATION_INVALID", "NAVIGATION_FAILED"],
    )
    result, store = decode(tmp_path, value, output)
    assert result.failed is True
    assert result.bundle.status is WebBrowserEvidenceStatus.FAILED
    assert result.metadata["screens"][0]["status"] == "COLLECTED"
    assert store.read(result.metadata["screens"][0]["artifacts"]["screenshot"]["storage_key"])


def test_console_same_message_keeps_both_missing_and_observed_locations(tmp_path):
    value = job()
    output = report(value)
    for index, screen in enumerate(output["screens"]):
        event = events()
        event["console_messages"] = [
            {
                "level": "INFO",
                "message": "same message",
                "location": None if index == 0 else "http://127.0.0.1:4173/:1:1",
            }
        ]
        screen["events"] = envelope(canonical_bytes(event))
    result, _ = decode(tmp_path, value, output)
    assert result.failed is False
    assert tuple(item.location for item in result.bundle.routes[0].console_messages) == (
        None,
        "http://127.0.0.1:4173/:1:1",
    )


def test_unverified_sandbox_is_failed_evidence_with_available_captures(tmp_path):
    value = job()
    output = report(value)
    output["chromium_no_sandbox_flag_absent"] = False
    result, _ = decode(tmp_path, value, output)
    assert result.failed is True
    assert any(item.code == "BROWSER_SANDBOX_UNVERIFIED" for item in result.findings)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda output: output["screens"][0].update(failure_codes=["INVENTED_CODE"]),
        lambda output: output["screens"][0].update(actions=[{"index": 0}]),
        lambda output: output["screens"][0].update(
            events=envelope(canonical_bytes({**events(), "page_errors": ["é" * 2048]}))
        ),
    ],
)
def test_protocol_bounds_and_enumerations_are_exact(tmp_path, mutate):
    value = job()
    output = report(value)
    mutate(output)
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


def test_assertion_text_uses_harness_character_limit_without_byte_truncation(tmp_path):
    plan = list(actions())
    plan[1] = BrowserAction("expect_text", "output", "漢" * 1000)
    value = job(interactions=(WebBrowserInteraction("root", tuple(plan)),))
    result, _ = decode(tmp_path, value, report(value))
    assert result.failed is False
    assert result.metadata["screens"][0]["actions"][1]["observed_text"] == "漢" * 1000


def test_root_plus_four_routes_produces_all_ten_distinct_viewport_records(tmp_path):
    value = job(*(WebBrowserRouteSpec(f"page-{index}", f"/page-{index}") for index in range(4)))
    result, _ = decode(tmp_path, value, report(value))
    assert result.failed is False
    assert len(result.bundle.routes) == 5
    assert len(result.metadata["screens"]) == 10
    assert (
        len(
            [
                item
                for item in result.metadata["generated_artifacts"]
                if item["path"].endswith(".png")
            ]
        )
        == 10
    )


def test_unknown_critical_png_chunk_is_not_a_valid_screenshot(tmp_path):
    value = job()
    output = report(value)
    original = png(390, 844)
    unknown = struct.pack(">I", 0) + b"FAKE" + struct.pack(">I", zlib.crc32(b"FAKE"))
    output["screens"][0]["screenshot"] = envelope(original[:-12] + unknown + original[-12:])
    with pytest.raises(WebPhaseBrowserEvidenceError):
        decode(tmp_path, value, output)


def test_uninspectable_surface_keeps_captures_but_cannot_pass_even_with_actions(tmp_path):
    value = job(interactions=(WebBrowserInteraction("root", actions()),))
    output = report(value)
    output["screens"][0].update(
        interactive_controls=None,
        interaction_status="FAILED",
        failure_codes=["INTERACTION_INSPECTION_FAILED"],
    )
    result, store = decode(tmp_path, value, output)
    assert result.failed is True
    assert result.bundle.status is WebBrowserEvidenceStatus.COLLECTED
    assert any(item.code == "INTERACTION_INSPECTION_FAILED" for item in result.findings)
    assert all(item["status"] == "PASSED" for item in result.metadata["screens"][0]["actions"])
    assert store.read(result.metadata["screens"][0]["artifacts"]["dom"]["storage_key"])
