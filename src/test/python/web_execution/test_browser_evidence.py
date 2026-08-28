"""Tests for bounded Playwright and axe evidence collection contracts."""

from __future__ import annotations

import pytest

from orchestwin.web_execution.browser_evidence import (
    WebAccessibilityFinding,
    WebAccessibilityImpact,
    WebBrowserConsoleLevel,
    WebBrowserConsoleMessage,
    WebBrowserEvidenceBundle,
    WebBrowserEvidencePolicy,
    WebBrowserEvidenceStatus,
    WebBrowserFailedRequest,
    WebBrowserRouteEvidence,
    WebBrowserRouteSpec,
    WebBrowserRouteStatus,
    create_web_browser_evidence_request,
)
from orchestwin.web_execution.reports import WebEvidenceReference


def evidence(key: str, character: str, media_type: str) -> WebEvidenceReference:
    return WebEvidenceReference(
        storage_key=key,
        sha256_digest=character * 64,
        size_bytes=16,
        media_type=media_type,
    )


def request(*routes: WebBrowserRouteSpec):
    return create_web_browser_evidence_request(
        source_revision_content_hash="a" * 64,
        source_tree_hash="b" * 64,
        runner_image_digest="c" * 64,
        base_url="http://127.0.0.1:4173",
        declared_routes=routes,
    )


def collected(route: WebBrowserRouteSpec) -> WebBrowserRouteEvidence:
    return WebBrowserRouteEvidence(
        route=route,
        status=WebBrowserRouteStatus.COLLECTED,
        final_path=route.path,
        screenshot_ref=evidence(
            f"browser/{route.route_id}.png",
            "d",
            "image/png",
        ),
        dom_snapshot_ref=evidence(
            f"browser/{route.route_id}.html",
            "e",
            "text/html",
        ),
        raw_playwright_ref=evidence(
            f"browser/{route.route_id}.playwright.json",
            "f",
            "application/json",
        ),
        accessibility_report_ref=evidence(
            f"browser/{route.route_id}.axe.json",
            "1",
            "application/json",
        ),
        console_messages=(
            WebBrowserConsoleMessage(
                level=WebBrowserConsoleLevel.ERROR,
                message="Unhandled application error.",
                location="src/main.ts:10",
            ),
        ),
        failed_requests=(
            WebBrowserFailedRequest(
                method="GET",
                path="/api/rooms",
                failure_text="Connection refused.",
            ),
        ),
        accessibility_findings=(
            WebAccessibilityFinding(
                rule_id="button-name",
                impact=WebAccessibilityImpact.SERIOUS,
                description="Buttons must have discernible text.",
                help_text="Add an accessible name.",
                targets=("button.save",),
            ),
        ),
        failure_code=None,
        failure_message=None,
    )


def failed(route: WebBrowserRouteSpec) -> WebBrowserRouteEvidence:
    return WebBrowserRouteEvidence(
        route=route,
        status=WebBrowserRouteStatus.FAILED,
        final_path=None,
        screenshot_ref=None,
        dom_snapshot_ref=None,
        raw_playwright_ref=evidence(
            f"browser/{route.route_id}.playwright.json",
            "2",
            "application/json",
        ),
        accessibility_report_ref=None,
        console_messages=(),
        failed_requests=(),
        accessibility_findings=(),
        failure_code="NAVIGATION_TIMEOUT",
        failure_message="Navigation did not complete within the route timeout.",
    )


def test_request_is_root_first_and_rejects_external_navigation() -> None:
    details = WebBrowserRouteSpec(route_id="details", path="/rooms/42")
    overview = WebBrowserRouteSpec(route_id="overview", path="/rooms")

    result = request(overview, details)

    assert tuple(route.route_id for route in result.routes) == (
        "root",
        "details",
        "overview",
    )
    with pytest.raises(ValueError, match="loopback"):
        create_web_browser_evidence_request(
            source_revision_content_hash="a" * 64,
            source_tree_hash="b" * 64,
            runner_image_digest="c" * 64,
            base_url="https://example.com",
        )
    with pytest.raises(ValueError, match="same-origin"):
        WebBrowserRouteSpec(route_id="external", path="https://example.com/")


def test_request_enforces_root_plus_four_declared_routes() -> None:
    routes = tuple(
        WebBrowserRouteSpec(route_id=f"route-{index}", path=f"/route-{index}")
        for index in range(1, 6)
    )

    with pytest.raises(ValueError, match="route limit"):
        request(*routes)


def test_complete_bundle_preserves_raw_evidence_and_deterministic_findings() -> None:
    browser_request = request()
    bundle = WebBrowserEvidenceBundle(
        request=browser_request,
        routes=(collected(browser_request.routes[0]),),
    )

    assert bundle.status is WebBrowserEvidenceStatus.COLLECTED
    assert bundle.routes[0].screenshot_ref is not None
    assert bundle.routes[0].dom_snapshot_ref is not None
    assert bundle.routes[0].raw_playwright_ref.media_type == "application/json"
    assert {finding.source_tool for finding in bundle.normalized_findings()} == {
        "axe-core",
        "playwright",
    }
    assert {finding.code for finding in bundle.normalized_findings()} == {
        "AXE_BUTTON_NAME",
        "BROWSER_CONSOLE_ERROR",
        "BROWSER_REQUEST_FAILED",
    }
    assert len(bundle.content_hash) == 64


def test_failed_route_produces_partial_status_without_discarding_raw_report() -> None:
    browser_request = request(WebBrowserRouteSpec(route_id="settings", path="/settings"))
    bundle = WebBrowserEvidenceBundle(
        request=browser_request,
        routes=(
            collected(browser_request.routes[0]),
            failed(browser_request.routes[1]),
        ),
    )

    assert bundle.status is WebBrowserEvidenceStatus.PARTIAL
    assert bundle.routes[1].raw_playwright_ref.storage_key.endswith("settings.playwright.json")


def test_bundle_rejects_evidence_that_exceeds_declared_limits() -> None:
    browser_request = create_web_browser_evidence_request(
        source_revision_content_hash="a" * 64,
        source_tree_hash="b" * 64,
        runner_image_digest="c" * 64,
        base_url="http://localhost:4173",
        policy=WebBrowserEvidencePolicy(
            maximum_routes=1,
            maximum_console_messages_per_route=1,
            maximum_failed_requests_per_route=1,
            maximum_accessibility_findings_per_route=1,
        ),
    )
    route = collected(browser_request.routes[0])
    too_many = WebBrowserRouteEvidence(
        route=route.route,
        status=route.status,
        final_path=route.final_path,
        screenshot_ref=route.screenshot_ref,
        dom_snapshot_ref=route.dom_snapshot_ref,
        raw_playwright_ref=route.raw_playwright_ref,
        accessibility_report_ref=route.accessibility_report_ref,
        console_messages=(
            WebBrowserConsoleMessage(
                level=WebBrowserConsoleLevel.ERROR,
                message="First error.",
                location=None,
            ),
            WebBrowserConsoleMessage(
                level=WebBrowserConsoleLevel.ERROR,
                message="Second error.",
                location=None,
            ),
        ),
        failed_requests=route.failed_requests,
        accessibility_findings=route.accessibility_findings,
        failure_code=None,
        failure_message=None,
    )

    with pytest.raises(ValueError, match="console-message limit"):
        WebBrowserEvidenceBundle(request=browser_request, routes=(too_many,))
