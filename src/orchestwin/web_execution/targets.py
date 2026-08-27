"""Capability-honest Web target variants and Sprint 08 validation scopes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, TypeVar

from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

_T = TypeVar("_T")

_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_WEB_TARGETS: Final = frozenset(
    {
        ExecutionTarget.WEB_STATIC,
        ExecutionTarget.WEB_VUE,
        ExecutionTarget.WEB_NODE_EXPRESS,
        ExecutionTarget.WEB_PHP,
        ExecutionTarget.WEB_VUE_NODE,
    }
)


class WebImplementationLanguage(StrEnum):
    """Languages that form one explicitly supported Web configuration."""

    STATIC_ASSETS = "STATIC_ASSETS"
    JAVASCRIPT = "JAVASCRIPT"
    TYPESCRIPT = "TYPESCRIPT"
    PHP = "PHP"


class WebProjectLayout(StrEnum):
    """Directory layouts included in the Sprint 08 validation boundary."""

    SINGLE_ROOT = "SINGLE_ROOT"
    FRONTEND_BACKEND = "FRONTEND_BACKEND"


class WebPackageManager(StrEnum):
    """Dependency managers admitted by one Web validation scope."""

    NONE = "NONE"
    NPM = "NPM"
    COMPOSER = "COMPOSER"


class WebRuntimeKind(StrEnum):
    """Runtime families used by the controlled Web runners."""

    STATIC_HTTP = "STATIC_HTTP"
    NODE = "NODE"
    PHP = "PHP"


@dataclass(frozen=True, slots=True, order=True)
class WebLanguageConfiguration:
    """Exact frontend/backend language pair for one supported project shape."""

    frontend: WebImplementationLanguage | None
    backend: WebImplementationLanguage | None

    def __post_init__(self) -> None:
        """Require at least one side and reject PHP as a frontend variant."""
        if self.frontend is None and self.backend is None:
            raise ValueError("web language configuration requires a frontend or backend")
        if self.frontend is WebImplementationLanguage.PHP:
            raise ValueError("PHP is not a validated frontend language variant")
        if self.backend is WebImplementationLanguage.STATIC_ASSETS:
            raise ValueError("static assets are not a backend language variant")

    def to_snapshot(self) -> dict[str, str | None]:
        """Return stable JSON-compatible language metadata."""
        return {
            "frontend": None if self.frontend is None else self.frontend.value,
            "backend": None if self.backend is None else self.backend.value,
        }


@dataclass(frozen=True, slots=True)
class WebValidationScope:
    """Versioned claim boundary for one public Web execution target."""

    target: ExecutionTarget
    profile_id: str
    profile_version: str
    capability_status: ExecutionCapabilityStatus
    language_configurations: tuple[WebLanguageConfiguration, ...]
    layout: WebProjectLayout
    package_managers: tuple[WebPackageManager, ...]
    runtime_kind: WebRuntimeKind
    required_roots: tuple[str, ...]
    excluded_frameworks: tuple[str, ...]
    requires_browser_evidence: bool
    validation_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect canonical values and prevent unearned Level D claims."""
        if self.target not in _WEB_TARGETS:
            raise ValueError("web validation scope requires an approved Web target")
        if not self.profile_id or self.profile_id != self.profile_id.strip():
            raise ValueError("web validation scope profile ID must be normalized")
        if _VERSION_PATTERN.fullmatch(self.profile_version) is None:
            raise ValueError("web validation scope profile version must be normalized")
        _require_canonical_unique(
            self.language_configurations,
            label="web language configurations",
            key=_language_sort_key,
        )
        if not self.language_configurations:
            raise ValueError("web validation scope requires a language configuration")
        _require_canonical_unique(
            self.package_managers,
            label="web package managers",
            key=lambda value: value.value,
        )
        if not self.package_managers:
            raise ValueError("web validation scope requires a package-manager declaration")
        _require_canonical_text(self.required_roots, label="web required roots")
        _require_canonical_text(
            self.excluded_frameworks,
            label="web excluded frameworks",
        )
        if not isinstance(self.requires_browser_evidence, bool):
            raise TypeError("browser-evidence marker must be a boolean")
        _require_canonical_text(
            self.validation_evidence_refs,
            label="web validation evidence references",
        )
        if self.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
            if not self.validation_evidence_refs:
                raise ValueError("validated Web scope requires recorded evidence")
        elif self.validation_evidence_refs:
            raise ValueError("non-validated Web scope must not claim validation evidence")
        _validate_target_shape(self)

    @property
    def content_hash(self) -> str:
        """Hash the complete capability claim independently from object identity."""
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def supports(self, configuration: WebLanguageConfiguration) -> bool:
        """Return whether the exact language configuration is inside the scope."""
        return configuration in self.language_configurations

    def to_snapshot(self) -> dict[str, object]:
        """Return canonical scope metadata including its integrity hash."""
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "capability_status": self.capability_status.value,
            "language_configurations": [
                configuration.to_snapshot() for configuration in self.language_configurations
            ],
            "layout": self.layout.value,
            "package_managers": [manager.value for manager in self.package_managers],
            "runtime_kind": self.runtime_kind.value,
            "required_roots": list(self.required_roots),
            "excluded_frameworks": list(self.excluded_frameworks),
            "requires_browser_evidence": self.requires_browser_evidence,
            "validation_evidence_refs": list(self.validation_evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class WebTargetSelection:
    """Exact target, language configuration, and layout selected for a snapshot."""

    target: ExecutionTarget
    language_configuration: WebLanguageConfiguration
    layout: WebProjectLayout

    def __post_init__(self) -> None:
        if self.target not in _WEB_TARGETS:
            raise ValueError("web target selection requires an approved Web target")

    def validate_against(self, scope: WebValidationScope) -> None:
        """Raise when a selection exceeds one versioned validation boundary."""
        if self.target is not scope.target:
            raise ValueError("web target selection does not match the validation scope")
        if self.layout is not scope.layout:
            raise ValueError("web target layout is outside the validation scope")
        if not scope.supports(self.language_configuration):
            raise ValueError("web language configuration is outside the validation scope")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "language_configuration": self.language_configuration.to_snapshot(),
            "layout": self.layout.value,
        }


_STATIC_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=WebImplementationLanguage.STATIC_ASSETS,
    backend=None,
)
_VUE_JAVASCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=WebImplementationLanguage.JAVASCRIPT,
    backend=None,
)
_VUE_TYPESCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=WebImplementationLanguage.TYPESCRIPT,
    backend=None,
)
_EXPRESS_JAVASCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=None,
    backend=WebImplementationLanguage.JAVASCRIPT,
)
_EXPRESS_TYPESCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=None,
    backend=WebImplementationLanguage.TYPESCRIPT,
)
_PHP_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=None,
    backend=WebImplementationLanguage.PHP,
)
_COMPOSED_JAVASCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=WebImplementationLanguage.JAVASCRIPT,
    backend=WebImplementationLanguage.JAVASCRIPT,
)
_COMPOSED_TYPESCRIPT_CONFIGURATION: Final = WebLanguageConfiguration(
    frontend=WebImplementationLanguage.TYPESCRIPT,
    backend=WebImplementationLanguage.TYPESCRIPT,
)

_COMMON_EXCLUSIONS: Final = (
    "angular",
    "bun",
    "fastify",
    "koa",
    "laravel",
    "nestjs",
    "nextjs",
    "nuxt",
    "pnpm",
    "react",
    "symfony",
    "wordpress",
    "yarn",
)


def create_sprint08_web_validation_scopes() -> Mapping[ExecutionTarget, WebValidationScope]:
    """Return the five owner-approved targets, initially honest Level C claims."""
    scopes = {
        ExecutionTarget.WEB_STATIC: WebValidationScope(
            target=ExecutionTarget.WEB_STATIC,
            profile_id="web.static",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language_configurations=(_STATIC_CONFIGURATION,),
            layout=WebProjectLayout.SINGLE_ROOT,
            package_managers=(WebPackageManager.NONE,),
            runtime_kind=WebRuntimeKind.STATIC_HTTP,
            required_roots=(".",),
            excluded_frameworks=_COMMON_EXCLUSIONS,
            requires_browser_evidence=True,
        ),
        ExecutionTarget.WEB_VUE: WebValidationScope(
            target=ExecutionTarget.WEB_VUE,
            profile_id="web.vue",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language_configurations=tuple(
                sorted(
                    (_VUE_JAVASCRIPT_CONFIGURATION, _VUE_TYPESCRIPT_CONFIGURATION),
                    key=_language_sort_key,
                )
            ),
            layout=WebProjectLayout.SINGLE_ROOT,
            package_managers=(WebPackageManager.NPM,),
            runtime_kind=WebRuntimeKind.NODE,
            required_roots=(".",),
            excluded_frameworks=_COMMON_EXCLUSIONS,
            requires_browser_evidence=True,
        ),
        ExecutionTarget.WEB_NODE_EXPRESS: WebValidationScope(
            target=ExecutionTarget.WEB_NODE_EXPRESS,
            profile_id="web.node-express",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language_configurations=tuple(
                sorted(
                    (_EXPRESS_JAVASCRIPT_CONFIGURATION, _EXPRESS_TYPESCRIPT_CONFIGURATION),
                    key=_language_sort_key,
                )
            ),
            layout=WebProjectLayout.SINGLE_ROOT,
            package_managers=(WebPackageManager.NPM,),
            runtime_kind=WebRuntimeKind.NODE,
            required_roots=(".",),
            excluded_frameworks=_COMMON_EXCLUSIONS,
            requires_browser_evidence=False,
        ),
        ExecutionTarget.WEB_PHP: WebValidationScope(
            target=ExecutionTarget.WEB_PHP,
            profile_id="web.php",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language_configurations=(_PHP_CONFIGURATION,),
            layout=WebProjectLayout.SINGLE_ROOT,
            package_managers=(WebPackageManager.COMPOSER,),
            runtime_kind=WebRuntimeKind.PHP,
            required_roots=("public",),
            excluded_frameworks=_COMMON_EXCLUSIONS,
            requires_browser_evidence=True,
        ),
        ExecutionTarget.WEB_VUE_NODE: WebValidationScope(
            target=ExecutionTarget.WEB_VUE_NODE,
            profile_id="web.vue-node",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language_configurations=tuple(
                sorted(
                    (
                        _COMPOSED_JAVASCRIPT_CONFIGURATION,
                        _COMPOSED_TYPESCRIPT_CONFIGURATION,
                    ),
                    key=_language_sort_key,
                )
            ),
            layout=WebProjectLayout.FRONTEND_BACKEND,
            package_managers=(WebPackageManager.NPM,),
            runtime_kind=WebRuntimeKind.NODE,
            required_roots=("backend", "frontend"),
            excluded_frameworks=_COMMON_EXCLUSIONS,
            requires_browser_evidence=True,
        ),
    }
    return MappingProxyType(scopes)


def web_scope_for(target: ExecutionTarget) -> WebValidationScope:
    """Resolve one Sprint 08 scope without silently accepting another target."""
    try:
        return create_sprint08_web_validation_scopes()[target]
    except KeyError as error:
        raise ValueError("target has no Sprint 08 Web validation scope") from error


def is_sprint08_web_target(target: ExecutionTarget) -> bool:
    """Return whether the target belongs to the approved Web family set."""
    return target in _WEB_TARGETS


def _validate_target_shape(scope: WebValidationScope) -> None:
    expected_layout = (
        WebProjectLayout.FRONTEND_BACKEND
        if scope.target is ExecutionTarget.WEB_VUE_NODE
        else WebProjectLayout.SINGLE_ROOT
    )
    if scope.layout is not expected_layout:
        raise ValueError("web validation scope layout does not match its target")
    if scope.target is ExecutionTarget.WEB_NODE_EXPRESS and scope.requires_browser_evidence:
        raise ValueError("API-only Express scope must not require browser evidence")
    if scope.target is not ExecutionTarget.WEB_NODE_EXPRESS and not scope.requires_browser_evidence:
        raise ValueError("user-interface Web scope requires browser evidence")
    for configuration in scope.language_configurations:
        if scope.target is ExecutionTarget.WEB_STATIC and configuration != _STATIC_CONFIGURATION:
            raise ValueError("static Web scope only supports static assets")
        if scope.target is ExecutionTarget.WEB_VUE and configuration.backend is not None:
            raise ValueError("Vue-only scope must not define a backend language")
        if scope.target is ExecutionTarget.WEB_NODE_EXPRESS and configuration.frontend is not None:
            raise ValueError("Express-only scope must not define a frontend language")
        if scope.target is ExecutionTarget.WEB_PHP and configuration != _PHP_CONFIGURATION:
            raise ValueError("PHP scope only supports the framework-free PHP configuration")
        if (
            scope.target is ExecutionTarget.WEB_VUE_NODE
            and configuration.frontend is not configuration.backend
        ):
            raise ValueError("composed Web scope only validates matching JS/JS or TS/TS")


def _language_sort_key(configuration: WebLanguageConfiguration) -> tuple[str, str]:
    return (
        "" if configuration.frontend is None else configuration.frontend.value,
        "" if configuration.backend is None else configuration.backend.value,
    )


def _require_canonical_unique[T](
    values: tuple[_T, ...],
    *,
    label: str,
    key: Callable[[_T], object],
) -> None:
    ordered = tuple(sorted(values, key=key))
    if values != ordered or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"{label} must contain normalized values")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
