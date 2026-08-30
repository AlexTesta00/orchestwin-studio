"""Canonical registry for the three separate Sprint 09 JVM profiles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from orchestwin.jvm_execution.java_profile import JavaJvmExecutionProfile
from orchestwin.jvm_execution.kotlin_profile import KotlinJvmExecutionProfile
from orchestwin.jvm_execution.profile_contracts import JvmExecutionProfile
from orchestwin.jvm_execution.scala_profile import ScalaJvmExecutionProfile
from orchestwin.jvm_execution.validation_evidence import (
    JvmProfilePromotionDecision,
    JvmProfileValidationEvidenceCatalog,
    evaluate_jvm_profile_promotion,
    promote_jvm_profile_if_eligible,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget


@dataclass(frozen=True, slots=True)
class JvmExecutionProfileRegistry:
    """Immutable one-profile-per-target JVM execution registry."""

    profiles: tuple[JvmExecutionProfile, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(profile, JvmExecutionProfile) for profile in self.profiles):
            raise TypeError("JVM execution registry accepts only execution profiles")
        ordered = tuple(sorted(self.profiles, key=_profile_sort_key))
        if self.profiles != ordered:
            raise ValueError("JVM execution profiles must use canonical order")
        profile_keys = tuple(
            (profile.scope.profile_id, profile.scope.profile_version) for profile in self.profiles
        )
        targets = tuple(profile.scope.target for profile in self.profiles)
        if len(profile_keys) != len(set(profile_keys)):
            raise ValueError("JVM execution registry contains a duplicate profile version")
        if len(targets) != len(set(targets)):
            raise ValueError("JVM execution registry contains a duplicate target")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def find(
        self,
        profile_id: str,
        profile_version: str,
    ) -> JvmExecutionProfile | None:
        return next(
            (
                profile
                for profile in self.profiles
                if profile.scope.profile_id == profile_id
                and profile.scope.profile_version == profile_version
            ),
            None,
        )

    def for_target(self, target: ExecutionTarget) -> JvmExecutionProfile | None:
        return next(
            (profile for profile in self.profiles if profile.scope.target is target),
            None,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {"profiles": [profile.scope.to_snapshot() for profile in self.profiles]}


def create_sprint09_jvm_profile_registry(
    *,
    evidence_catalog: JvmProfileValidationEvidenceCatalog | None = None,
) -> JvmExecutionProfileRegistry:
    """Create three profiles and promote only versions with complete evidence."""
    profiles: tuple[JvmExecutionProfile, ...] = (
        JavaJvmExecutionProfile(),
        KotlinJvmExecutionProfile(),
        ScalaJvmExecutionProfile(),
    )
    if evidence_catalog is not None:
        profiles = tuple(
            promote_jvm_profile_if_eligible(profile, catalog=evidence_catalog)
            for profile in profiles
        )
    return create_jvm_execution_profile_registry(profiles)


def evaluate_sprint09_jvm_profile_promotions(
    evidence_catalog: JvmProfileValidationEvidenceCatalog,
) -> tuple[JvmProfilePromotionDecision, ...]:
    """Return one inspectable evidence decision for every public JVM target."""
    registry = create_sprint09_jvm_profile_registry()
    return tuple(
        sorted(
            (
                evaluate_jvm_profile_promotion(profile.scope, catalog=evidence_catalog)
                for profile in registry.profiles
            ),
            key=lambda decision: (decision.profile_id, decision.profile_version),
        )
    )


def create_jvm_execution_profile_registry(
    profiles: Iterable[JvmExecutionProfile],
) -> JvmExecutionProfileRegistry:
    return JvmExecutionProfileRegistry(
        profiles=tuple(sorted(tuple(profiles), key=_profile_sort_key))
    )


def _profile_sort_key(profile: JvmExecutionProfile) -> tuple[str, str, str]:
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
