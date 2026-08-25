"""Immutable execution-profile registry with exact version lookup."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from orchestwin.sandbox.execution_profiles import (
    ExecutionProfile,
    ExecutionProfileReference,
    ExecutionTarget,
)


@dataclass(frozen=True, slots=True)
class ExecutionProfileRegistry:
    """Canonical collection of independently versioned execution profiles."""

    profiles: tuple[ExecutionProfile, ...]

    def __post_init__(self) -> None:
        """Reject invalid implementations, duplicate versions, and unstable ordering."""
        if any(not isinstance(profile, ExecutionProfile) for profile in self.profiles):
            raise TypeError("execution profile registry accepts only profile implementations")

        ordered = tuple(sorted(self.profiles, key=_profile_sort_key))
        if self.profiles != ordered:
            raise ValueError("execution profile registry must use canonical profile ordering")

        keys = tuple(_profile_key(profile) for profile in self.profiles)
        if len(keys) != len(set(keys)):
            raise ValueError("execution profile registry contains a duplicate profile version")

    @property
    def content_hash(self) -> str:
        """Return a digest covering every registered profile metadata version."""
        return hashlib.sha256(_canonical_json_bytes(self.to_snapshot())).hexdigest()

    @property
    def references(self) -> tuple[ExecutionProfileReference, ...]:
        """Return exact profile references in registry order."""
        return tuple(profile.metadata.reference for profile in self.profiles)

    def find(
        self,
        profile_id: str,
        profile_version: str,
    ) -> ExecutionProfile | None:
        """Resolve one exact profile ID and version without latest-version ambiguity."""
        return next(
            (
                profile
                for profile in self.profiles
                if profile.metadata.profile_id == profile_id
                and profile.metadata.version == profile_version
            ),
            None,
        )

    def find_reference(
        self,
        reference: ExecutionProfileReference,
    ) -> ExecutionProfile | None:
        """Resolve only when ID, version, and metadata hash all still match."""
        profile = self.find(reference.profile_id, reference.profile_version)
        if profile is None or profile.metadata.content_hash != reference.content_hash:
            return None
        return profile

    def versions_for(self, profile_id: str) -> tuple[ExecutionProfile, ...]:
        """Return all known versions for one stable profile ID."""
        return tuple(
            profile for profile in self.profiles if profile.metadata.profile_id == profile_id
        )

    def profiles_for_target(
        self,
        target: ExecutionTarget,
    ) -> tuple[ExecutionProfile, ...]:
        """Return profiles that explicitly advertise one target family."""
        return tuple(
            profile for profile in self.profiles if target in profile.metadata.supported_targets
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic registry metadata without implementation internals."""
        return {
            "profiles": [profile.metadata.to_snapshot() for profile in self.profiles],
        }


def create_execution_profile_registry(
    profiles: Iterable[ExecutionProfile],
) -> ExecutionProfileRegistry:
    """Canonicalize an iterable while preserving duplicate-detection semantics."""
    return ExecutionProfileRegistry(
        profiles=tuple(sorted(tuple(profiles), key=_profile_sort_key)),
    )


def _profile_key(profile: ExecutionProfile) -> tuple[str, str]:
    """Return the stable identity key for one profile implementation."""
    return (
        profile.metadata.profile_id,
        profile.metadata.version,
    )


def _profile_sort_key(profile: ExecutionProfile) -> tuple[str, str, str]:
    """Order profiles by public identity and exact metadata digest."""
    return (
        profile.metadata.profile_id,
        profile.metadata.version,
        profile.metadata.content_hash,
    )


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    """Serialize registry metadata deterministically."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
