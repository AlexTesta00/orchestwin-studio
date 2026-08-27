"""Canonical registry for the five separate Sprint 08 Web profile implementations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.express_profile import WebNodeExpressExecutionProfile
from orchestwin.web_execution.php_profile import WebPhpExecutionProfile
from orchestwin.web_execution.profile_contracts import WebExecutionProfile
from orchestwin.web_execution.static_profile import WebStaticExecutionProfile
from orchestwin.web_execution.vue_node_profile import WebVueNodeExecutionProfile
from orchestwin.web_execution.vue_profile import WebVueExecutionProfile


@dataclass(frozen=True, slots=True)
class WebExecutionProfileRegistry:
    """Immutable one-profile-per-target Web execution registry."""

    profiles: tuple[WebExecutionProfile, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(profile, WebExecutionProfile) for profile in self.profiles):
            raise TypeError("Web execution registry accepts only profile implementations")
        ordered = tuple(sorted(self.profiles, key=_profile_sort_key))
        if self.profiles != ordered:
            raise ValueError("Web execution profiles must use canonical order")
        profile_keys = tuple(
            (profile.scope.profile_id, profile.scope.profile_version) for profile in self.profiles
        )
        targets = tuple(profile.scope.target for profile in self.profiles)
        if len(profile_keys) != len(set(profile_keys)):
            raise ValueError("Web execution registry contains a duplicate profile version")
        if len(targets) != len(set(targets)):
            raise ValueError("Web execution registry contains a duplicate target")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def find(
        self,
        profile_id: str,
        profile_version: str,
    ) -> WebExecutionProfile | None:
        return next(
            (
                profile
                for profile in self.profiles
                if profile.scope.profile_id == profile_id
                and profile.scope.profile_version == profile_version
            ),
            None,
        )

    def for_target(self, target: ExecutionTarget) -> WebExecutionProfile | None:
        return next(
            (profile for profile in self.profiles if profile.scope.target is target),
            None,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "profiles": [profile.scope.to_snapshot() for profile in self.profiles],
        }


def create_sprint08_web_profile_registry() -> WebExecutionProfileRegistry:
    """Create all five profile implementations while preserving Level C claims."""
    return create_web_execution_profile_registry(
        (
            WebNodeExpressExecutionProfile(),
            WebPhpExecutionProfile(),
            WebStaticExecutionProfile(),
            WebVueExecutionProfile(),
            WebVueNodeExecutionProfile(),
        )
    )


def create_web_execution_profile_registry(
    profiles: Iterable[WebExecutionProfile],
) -> WebExecutionProfileRegistry:
    return WebExecutionProfileRegistry(
        profiles=tuple(sorted(tuple(profiles), key=_profile_sort_key))
    )


def _profile_sort_key(profile: WebExecutionProfile) -> tuple[str, str, str]:
    return (
        profile.scope.profile_id,
        profile.scope.profile_version,
        profile.scope.content_hash,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
