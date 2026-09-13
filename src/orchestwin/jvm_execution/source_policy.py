"""Verified build configurations for the first governed JVM runtime.

Build DSL, launchers and dependency metadata must match the reviewed repository
catalog byte for byte. Application/test sources may change within the language
roots. This is a deliberately closed input scope, not a parser for arbitrary DSL.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from orchestwin.jvm_execution.policy import JvmToolchainDeclaration, policy_for
from orchestwin.jvm_execution.workspaces import portable_path, read_regular_file

SOURCE_POLICY_HASH = "312245b9d2e9f83d6b3a549b0c9c51afebe38eb81eec86dbb92d42c424d934f8"
SOURCE_POLICY_SCOPE = "PINNED_BUILD_CONFIGURATIONS_V1"


def read_source_objects(revision, root: Path) -> dict[str, bytes]:
    if (
        not 1 <= len(revision.files) <= 1024
        or sum(f.size_bytes for f in revision.files) > 64 * 1024 * 1024
    ):
        raise ValueError("JVM_SOURCE_BUDGET_EXCEEDED")
    result = {}
    paths = [entry.normalized_path for entry in revision.files]
    directories = {
        str(parent)
        for path in paths
        for parent in PurePosixPath(path).parents
        if str(parent) != "."
    }
    folded = {path.casefold() for path in paths}
    if (
        len(folded) != len(paths)
        or len({path.casefold() for path in directories}) != len(directories)
        or any(path.casefold() in folded for path in directories)
    ):
        raise ValueError("JVM_SOURCE_PATH_COLLISION")
    for entry in revision.files:
        portable_path(entry.normalized_path)
        digest = entry.sha256_digest
        if entry.storage_key != f"sha256/{digest[:2]}/{digest}":
            raise ValueError("JVM_SOURCE_OBJECT_KEY_INVALID")
        data = read_regular_file(
            root / entry.storage_key, maximum_bytes=min(entry.size_bytes, 16 * 1024 * 1024)
        )
        if len(data) != entry.size_bytes or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("JVM_SOURCE_OBJECT_INTEGRITY_FAILED")
        result[entry.normalized_path] = data
    return result


def verify_source_policy(revision, contents: dict[str, bytes], *, repo_root: Path):
    raw = read_regular_file(
        repo_root / "infra/jvm-runners/source-policy.json", maximum_bytes=32 * 1024
    )
    if hashlib.sha256(raw).hexdigest() != SOURCE_POLICY_HASH:
        raise ValueError("JVM_SOURCE_POLICY_INTEGRITY_FAILED")
    policy = policy_for(revision.target_selection.target)
    pinned = json.loads(raw)["profiles"][revision.target_selection.target.value]
    if not set(pinned) <= set(contents):
        raise ValueError("JVM_PINNED_BUILD_FILES_MISSING")
    language = {"JVM_JAVA": "java", "JVM_KOTLIN": "kotlin", "JVM_SCALA": "scala"}[
        revision.target_selection.target.value
    ]
    for path, content in contents.items():
        if path in pinned:
            if (
                len(content) != pinned[path]["size_bytes"]
                or hashlib.sha256(content).hexdigest() != pinned[path]["sha256"]
            ):
                raise ValueError("JVM_BUILD_CONFIGURATION_NOT_SUPPORTED")
        elif not any(
            path.startswith(f"src/{kind}/{folder}/")
            for kind in ("main", "test")
            for folder in (language, "resources")
        ):
            raise ValueError("JVM_SOURCE_PATH_OUTSIDE_RUNTIME_SCOPE")
    return JvmToolchainDeclaration(
        selection=policy.selection,
        jdk_major=policy.selection.jdk_major,
        build_tool_version=policy.build_tool_version,
        language_version=policy.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=policy.require_dependency_verification,
        repositories=policy.allowed_repositories,
        plugins=policy.allowed_plugins,
        network_disabled_after_setup=True,
    )
