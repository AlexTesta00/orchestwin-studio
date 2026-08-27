"""Typed Playwright and axe evidence for same-origin Web interface inspection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import urlsplit

from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebNormalizedFinding,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_HTTP_METHOD_PATTERN: Final = re.compile(r"^[A-Z]{3,16}$")
_MAX_ROUTE_PATH_LENGTH: Final = 512
_MAX_TEXT_LENGTH: Final = 2_048


class WebBrowserRouteStatus(StrEnum):
    """Terminal state of one bounded browser route inspection."""

    COLLECTED = "COLLECTED"
    FAILED = "FAILED"


class WebBrowserEvidenceStatus(StrEnum):
    """Aggregate browser status without converting partial evidence into success."""

    COLLECTED = "COLLECTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class WebBrowserConsoleLevel(StrEnum):
    """Console levels retained from the controlled browser harness."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class WebAccessibilityImpact(StrEnum):
    """Deterministic axe impact labels preserved without reinterpretation."""

    CRITICAL = "CRITICAL"
    SERIOUS = "SERIOUS"
    MODERATE = "MODERATE"
    MINOR = "MINOR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WebBrowserEvidencePolicy:
    """Explicit upper bounds for one browser evidence collection request."""

    maximum_routes: int = 5
    maximum_console_messages_per_route: int = 100
    maximum_failed_requests_per_route: int = 100
    maximum_accessibility_findings_per_route: int = 200

    def __post_init__(self) -> None:
        values = (
            self.maximum_routes,
            self.maximum_console_messages_per_route,
            self.maximum_failed_requests_per_route,
            self.maximum_accessibility_findings_per_route,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("browser evidence policy limits must be positive integers")
        if self.maximum_routes > 5:
            raise ValueError("browser evidence policy supports at most five routes")

    def to_snapshot(self) -> dict[str, int]:
        return {
            "maximum_routes": self.maximum_routes,
            "maximum_console_messages_per_route": (self.maximum_console_messages_per_route),
            "maximum_failed_requests_per_route": self.maximum_failed_requests_per_route,
            "maximum_accessibility_findings_per_route": (
                self.maximum_accessibility_findings_per_route
            ),
        }


DEFAULT_WEB_BROWSER_EVIDENCE_POLICY: Final = WebBrowserEvidencePolicy()


@dataclass(frozen=True, slots=True, order=True)
class WebBrowserRouteSpec:
    """One same-origin route requested from the controlled browser harness."""

    route_id: str
    path: str

    def __post_init__(self) -> None:
        _validate_identifier(self.route_id, label="browser route ID")
        _validate_same_origin_path(self.path, label="browser route path")

    def to_snapshot(self) -> dict[str, str]:
        return {"route_id": self.route_id, "path": self.path}


@dataclass(frozen=True, slots=True)
class WebBrowserEvidenceRequest:
    """Exact bounded browser task bound to source and runner identities."""

    source_revision_content_hash: str
    source_tree_hash: str
    runner_image_digest: str
    base_url: str
    routes: tuple[WebBrowserRouteSpec, ...]
    policy: WebBrowserEvidencePolicy

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_revision_content_hash, "browser source revision hash"),
            (self.source_tree_hash, "browser source tree hash"),
            (self.runner_image_digest, "browser runner image digest"),
        ):
            _validate_sha256(value, label=label)
        _validate_loopback_origin(self.base_url)
        if not self.routes:
            raise ValueError("browser evidence request requires at least one route")
        if len(self.routes) > self.policy.maximum_routes:
            raise ValueError("browser evidence request exceeds the route limit")
        if self.routes[0].path != "/":
            raise ValueError("browser evidence request must inspect the root route first")
        route_ids = tuple(route.route_id for route in self.routes)
        paths = tuple(route.path for route in self.routes)
        if len(route_ids) != len(set(route_ids)) or len(paths) != len(set(paths)):
            raise ValueError("browser evidence request routes must be unique")
        expected = _canonical_routes(self.routes)
        if self.routes != expected:
            raise ValueError("browser evidence request routes must use canonical order")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "source_revision_content_hash": self.source_revision_content_hash,
            "source_tree_hash": self.source_tree_hash,
            "runner_image_digest": self.runner_image_digest,
            "base_url": self.base_url,
            "routes": [route.to_snapshot() for route in self.routes],
            "policy": self.policy.to_snapshot(),
        }


@dataclass(frozen=True, slots=True, order=True)
class WebBrowserConsoleMessage:
    """One console message preserved with its browser-provided location."""

    level: WebBrowserConsoleLevel
    message: str
    location: str | None

    def __post_init__(self) -> None:
        _validate_normalized_text(self.message, label="browser console message")
        if self.location is not None:
            _validate_normalized_text(self.location, label="browser console location")

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "level": self.level.value,
            "message": self.message,
            "location": self.location,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebBrowserFailedRequest:
    """One failed local request reported by the controlled browser."""

    method: str
    path: str
    failure_text: str

    def __post_init__(self) -> None:
        if _HTTP_METHOD_PATTERN.fullmatch(self.method) is None:
            raise ValueError("browser failed-request method must be uppercase HTTP")
        _validate_same_origin_path(self.path, label="browser failed-request path")
        _validate_normalized_text(
            self.failure_text,
            label="browser failed-request message",
        )

    def to_snapshot(self) -> dict[str, str]:
        return {
            "method": self.method,
            "path": self.path,
            "failure_text": self.failure_text,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebAccessibilityFinding:
    """One axe finding retained as deterministic tool evidence."""

    rule_id: str
    impact: WebAccessibilityImpact
    description: str
    help_text: str
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.rule_id, label="accessibility rule ID")
        _validate_normalized_text(
            self.description,
            label="accessibility finding description",
        )
        _validate_normalized_text(self.help_text, label="accessibility finding help")
        _require_canonical_text(self.targets, label="accessibility finding targets")
        if not self.targets:
            raise ValueError("accessibility finding requires at least one target")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "impact": self.impact.value,
            "description": self.description,
            "help_text": self.help_text,
            "targets": list(self.targets),
        }


@dataclass(frozen=True, slots=True)
class WebBrowserRouteEvidence:
    """Screenshot, DOM, console, network, and axe evidence for one route."""

    route: WebBrowserRouteSpec
    status: WebBrowserRouteStatus
    final_path: str | None
    screenshot_ref: WebEvidenceReference | None
    dom_snapshot_ref: WebEvidenceReference | None
    raw_playwright_ref: WebEvidenceReference
    accessibility_report_ref: WebEvidenceReference | None
    console_messages: tuple[WebBrowserConsoleMessage, ...]
    failed_requests: tuple[WebBrowserFailedRequest, ...]
    accessibility_findings: tuple[WebAccessibilityFinding, ...]
    failure_code: str | None
    failure_message: str | None

    def __post_init__(self) -> None:
        if self.final_path is not None:
            _validate_same_origin_path(self.final_path, label="browser final path")
        _require_canonical_unique(
            self.console_messages,
            label="browser console messages",
        )
        _require_canonical_unique(
            self.failed_requests,
            label="browser failed requests",
        )
        _require_canonical_unique(
            self.accessibility_findings,
            label="browser accessibility findings",
        )
        if self.status is WebBrowserRouteStatus.COLLECTED:
            if (
                self.final_path is None
                or self.screenshot_ref is None
                or self.dom_snapshot_ref is None
                or self.accessibility_report_ref is None
                or self.failure_code is not None
                or self.failure_message is not None
            ):
                raise ValueError("collected browser route requires complete evidence")
        else:
            if not self.failure_code or not self.failure_message:
                raise ValueError("failed browser route requires a stable failure")
            _validate_identifier(self.failure_code, label="browser route failure code")
            _validate_normalized_text(
                self.failure_message,
                label="browser route failure message",
            )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "route": self.route.to_snapshot(),
            "status": self.status.value,
            "final_path": self.final_path,
            "screenshot_ref": (
                None if self.screenshot_ref is None else self.screenshot_ref.to_snapshot()
            ),
            "dom_snapshot_ref": (
                None if self.dom_snapshot_ref is None else self.dom_snapshot_ref.to_snapshot()
            ),
            "raw_playwright_ref": self.raw_playwright_ref.to_snapshot(),
            "accessibility_report_ref": (
                None
                if self.accessibility_report_ref is None
                else self.accessibility_report_ref.to_snapshot()
            ),
            "console_messages": [item.to_snapshot() for item in self.console_messages],
            "failed_requests": [item.to_snapshot() for item in self.failed_requests],
            "accessibility_findings": [item.to_snapshot() for item in self.accessibility_findings],
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
        }


@dataclass(frozen=True, slots=True)
class WebBrowserEvidenceBundle:
    """Canonical route evidence bound to one exact browser request."""

    request: WebBrowserEvidenceRequest
    routes: tuple[WebBrowserRouteEvidence, ...]

    def __post_init__(self) -> None:
        expected_specs = self.request.routes
        actual_specs = tuple(route.route for route in self.routes)
        if actual_specs != expected_specs:
            raise ValueError("browser evidence must cover every requested route in order")
        policy = self.request.policy
        for route in self.routes:
            if len(route.console_messages) > policy.maximum_console_messages_per_route:
                raise ValueError("browser evidence exceeds the console-message limit")
            if len(route.failed_requests) > policy.maximum_failed_requests_per_route:
                raise ValueError("browser evidence exceeds the failed-request limit")
            if len(route.accessibility_findings) > policy.maximum_accessibility_findings_per_route:
                raise ValueError("browser evidence exceeds the accessibility-finding limit")

    @property
    def status(self) -> WebBrowserEvidenceStatus:
        collected = sum(route.status is WebBrowserRouteStatus.COLLECTED for route in self.routes)
        if collected == len(self.routes):
            return WebBrowserEvidenceStatus.COLLECTED
        if collected:
            return WebBrowserEvidenceStatus.PARTIAL
        return WebBrowserEvidenceStatus.FAILED

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def normalized_findings(self) -> tuple[WebNormalizedFinding, ...]:
        """Expose deterministic browser findings without creating User Twin claims."""
        findings: set[WebNormalizedFinding] = set()
        for route in self.routes:
            for message in route.console_messages:
                if message.level is WebBrowserConsoleLevel.ERROR:
                    findings.add(
                        WebNormalizedFinding(
                            code="BROWSER_CONSOLE_ERROR",
                            message=message.message,
                            source_tool="playwright",
                            location=message.location or route.route.path,
                        )
                    )
            for request in route.failed_requests:
                findings.add(
                    WebNormalizedFinding(
                        code="BROWSER_REQUEST_FAILED",
                        message=(f"{request.method} {request.path} failed: {request.failure_text}"),
                        source_tool="playwright",
                        location=route.route.path,
                    )
                )
            for finding in route.accessibility_findings:
                findings.add(
                    WebNormalizedFinding(
                        code=f"AXE_{finding.rule_id.upper().replace('-', '_')}",
                        message=finding.description,
                        source_tool="axe-core",
                        location=", ".join(finding.targets),
                    )
                )
        return tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.code,
                    item.source_tool,
                    item.location or "",
                    item.message,
                ),
            )
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "request": self.request.to_snapshot(),
            "status": self.status.value,
            "routes": [route.to_snapshot() for route in self.routes],
            "normalized_findings": [
                finding.to_snapshot() for finding in self.normalized_findings()
            ],
        }


def create_web_browser_evidence_request(
    *,
    source_revision_content_hash: str,
    source_tree_hash: str,
    runner_image_digest: str,
    base_url: str,
    declared_routes: Iterable[WebBrowserRouteSpec] = (),
    policy: WebBrowserEvidencePolicy = DEFAULT_WEB_BROWSER_EVIDENCE_POLICY,
) -> WebBrowserEvidenceRequest:
    """Create a root-first request with at most four additional declared routes."""
    root = WebBrowserRouteSpec(route_id="root", path="/")
    routes = (root, *tuple(declared_routes))
    return WebBrowserEvidenceRequest(
        source_revision_content_hash=source_revision_content_hash,
        source_tree_hash=source_tree_hash,
        runner_image_digest=runner_image_digest,
        base_url=base_url,
        routes=_canonical_routes(routes),
        policy=policy,
    )


def _canonical_routes(
    routes: tuple[WebBrowserRouteSpec, ...],
) -> tuple[WebBrowserRouteSpec, ...]:
    root = tuple(route for route in routes if route.path == "/")
    others = tuple(
        sorted(
            (route for route in routes if route.path != "/"),
            key=lambda route: (route.route_id, route.path),
        )
    )
    return (*root, *others)


def _validate_loopback_origin(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("browser base URL must be one explicit loopback HTTP origin")


def _validate_same_origin_path(value: str, *, label: str) -> None:
    parsed = urlsplit(value)
    path = parsed.path
    if (
        not value
        or len(value) > _MAX_ROUTE_PATH_LENGTH
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not path.startswith("/")
        or path.startswith("//")
        or "\\" in value
        or any(part in {".", ".."} for part in PurePosixPath(path).parts)
    ):
        raise ValueError(f"{label} must be a bounded same-origin path")


def _validate_identifier(value: str, *, label: str) -> None:
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a normalized portable identifier")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()) or len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{label} must be normalized and bounded")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    for value in values:
        _validate_normalized_text(value, label=label)


def _require_canonical_unique(values: tuple[object, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
