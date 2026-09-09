"""Bounded, declarative browser inspections of exact immutable static revisions.

These values do not grant permission to execute. Callers must load revisions
through owner-scoped persistence and supply an independent authorization port.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID

MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
VIEWPORTS = (("narrow", 390, 844), ("wide", 1280, 800))
_SHA = re.compile(r"[0-9a-f]{64}")
_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


class StaticBrowserError(ValueError):
    """Stable error code; never expose submitted sources or credentials."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_hash(value: str) -> None:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise StaticBrowserError("SHA256_REQUIRED")


def validate_path(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise StaticBrowserError("STATIC_PATH_INVALID")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        or PureWindowsPath(value).drive
        or ":" in value
        or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
        or any(ord(char) < 32 for char in value)
        or value != value.strip()
        or path.suffix.lower() not in _TYPES
        or any(part.endswith((" ", ".")) for part in path.parts)
    ):
        raise StaticBrowserError("STATIC_PATH_INVALID")
    if any(
        part.casefold() in {"node_modules", "vendor", "credentials.json", "secrets.json"}
        for part in path.parts
    ):
        raise StaticBrowserError("STATIC_PATH_PROHIBITED")


@dataclass(frozen=True, slots=True)
class StaticFile:
    path: str
    content: bytes

    def __post_init__(self) -> None:
        validate_path(self.path)
        if not isinstance(self.content, bytes) or len(self.content) > MAX_SOURCE_BYTES:
            raise StaticBrowserError("STATIC_FILE_SIZE_INVALID")
        try:
            text = self.content.decode("utf-8")
        except UnicodeError:
            raise StaticBrowserError("STATIC_FILE_REQUIRES_UTF8") from None
        if "\x00" in text:
            raise StaticBrowserError("STATIC_FILE_NUL")

    def snapshot(self) -> dict[str, object]:
        return {
            "path": self.path,
            "content_base64": base64.b64encode(self.content).decode("ascii"),
            "size_bytes": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "media_type": _TYPES[PurePosixPath(self.path).suffix.lower()],
        }


@dataclass(frozen=True, slots=True)
class BrowserAction:
    kind: str
    selector: str
    value: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"click", "fill", "press", "expect_text"}:
            raise StaticBrowserError("BROWSER_ACTION_UNSUPPORTED")
        if not isinstance(self.selector, str) or not 1 <= len(self.selector) <= 160:
            raise StaticBrowserError("BROWSER_SELECTOR_INVALID")
        if self.kind == "click":
            if self.value is not None:
                raise StaticBrowserError("CLICK_VALUE_FORBIDDEN")
        elif not isinstance(self.value, str) or len(self.value) > 1000:
            raise StaticBrowserError("BROWSER_ACTION_VALUE_INVALID")
        if self.kind == "press" and self.value not in {
            "Enter",
            "Space",
            "Tab",
            "Escape",
            "ArrowLeft",
            "ArrowRight",
            "Home",
            "End",
        }:
            raise StaticBrowserError("BROWSER_KEY_UNSUPPORTED")

    def snapshot(self) -> dict[str, object]:
        return {"kind": self.kind, "selector": self.selector, "value": self.value}


@dataclass(frozen=True, slots=True)
class BrowserScenario:
    scenario_id: str
    route: str
    actions: tuple[BrowserAction, ...]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9-]{0,39}", self.scenario_id) is None:
            raise StaticBrowserError("SCENARIO_ID_INVALID")
        if self.route != "/":
            if not self.route.startswith("/"):
                raise StaticBrowserError("SCENARIO_ROUTE_INVALID")
            validate_path(self.route[1:])
            if not self.route.endswith(".html"):
                raise StaticBrowserError("SCENARIO_REQUIRES_HTML")
        if not isinstance(self.actions, tuple) or not 1 <= len(self.actions) <= 8:
            raise StaticBrowserError("SCENARIO_ACTION_LIMIT")
        if not any(action.kind == "expect_text" for action in self.actions):
            raise StaticBrowserError("SCENARIO_ASSERTION_REQUIRED")

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.scenario_id,
            "route": self.route,
            "actions": [action.snapshot() for action in self.actions],
        }


@dataclass(frozen=True, slots=True)
class StaticBrowserJob:
    project_id: UUID
    owner_user_id: UUID
    revision_id: UUID
    revision_content_hash: str
    source_tree_hash: str
    runner_manifest_content_hash: str
    harness_sha256: str
    files: tuple[StaticFile, ...]
    scenarios: tuple[BrowserScenario, ...]

    def __post_init__(self) -> None:
        for value in (self.project_id, self.owner_user_id, self.revision_id):
            if not isinstance(value, UUID):
                raise StaticBrowserError("SOURCE_IDENTITY_INVALID")
        for value in (
            self.revision_content_hash,
            self.source_tree_hash,
            self.runner_manifest_content_hash,
            self.harness_sha256,
        ):
            require_hash(value)
        if not isinstance(self.files, tuple) or not 1 <= len(self.files) <= 100:
            raise StaticBrowserError("STATIC_FILE_COUNT_INVALID")
        paths = [file.path for file in self.files]
        if paths != sorted(paths, key=lambda item: (item.casefold(), item)):
            raise StaticBrowserError("STATIC_FILES_NOT_CANONICAL")
        if len({path.casefold() for path in paths}) != len(paths) or "index.html" not in paths:
            raise StaticBrowserError("STATIC_FILES_DUPLICATED_OR_ROOT_MISSING")
        if sum(len(file.content) for file in self.files) > MAX_SOURCE_BYTES:
            raise StaticBrowserError("STATIC_SOURCE_LIMIT")
        tree = {
            "files": [
                {
                    "normalized_path": file.path,
                    "sha256_digest": hashlib.sha256(file.content).hexdigest(),
                    "size_bytes": len(file.content),
                }
                for file in self.files
            ]
        }
        if content_hash(tree) != self.source_tree_hash:
            raise StaticBrowserError("SOURCE_TREE_HASH_MISMATCH")
        if not isinstance(self.scenarios, tuple) or not 1 <= len(self.scenarios) <= 2:
            raise StaticBrowserError("SCENARIO_COUNT_INVALID")
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise StaticBrowserError("SCENARIO_ID_DUPLICATED")
        if any(
            ("index.html" if item.route == "/" else item.route[1:]) not in paths
            for item in self.scenarios
        ):
            raise StaticBrowserError("SCENARIO_FILE_MISSING")

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "source": {
                "project_id": str(self.project_id),
                "owner_user_id": str(self.owner_user_id),
                "revision_id": str(self.revision_id),
                "content_hash": self.revision_content_hash,
                "source_tree_hash": self.source_tree_hash,
            },
            "runner_manifest_content_hash": self.runner_manifest_content_hash,
            "harness_sha256": self.harness_sha256,
            "files": [item.snapshot() for item in self.files],
            "scenarios": [item.snapshot() for item in self.scenarios],
            "viewports": [
                {"name": name, "width": width, "height": height}
                for name, width, height in VIEWPORTS
            ],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.snapshot())

    def wire_bytes(self) -> bytes:
        data = canonical_bytes({**self.snapshot(), "job_content_hash": self.content_hash})
        if len(data) > MAX_INPUT_BYTES:
            raise StaticBrowserError("JOB_INPUT_LIMIT")
        return data


def job_from_revision(
    revision: Mapping[str, object],
    *,
    owner_user_id: UUID,
    project_id: UUID,
    read_content: Callable[[str], bytes | None],
    scenarios: tuple[BrowserScenario, ...],
    runner_manifest_content_hash: str,
    harness_sha256: str,
) -> StaticBrowserJob:
    """Bind actual immutable source metadata and bytes; not a database authorization check.

    The caller must obtain this snapshot from owner-scoped persistence first.
    No untrusted filename is passed to the content store: only SHA-256 addresses.
    """
    if revision.get("project_id") != str(project_id) or (
        revision.get("created_by_user_id") != str(owner_user_id)
    ):
        raise StaticBrowserError("SOURCE_OWNER_SCOPE_MISMATCH")
    selection = revision.get("target_selection")
    if selection != {
        "target": "WEB_STATIC",
        "layout": "SINGLE_ROOT",
        "language_configuration": {"frontend": "STATIC_ASSETS", "backend": None},
    }:
        raise StaticBrowserError("STATIC_EXECUTOR_TARGET_UNSUPPORTED")
    projection = {
        key: value
        for key, value in revision.items()
        if key not in {"content_hash", "source_tree_hash"}
    }
    if content_hash(projection) != revision.get("content_hash"):
        raise StaticBrowserError("SOURCE_REVISION_HASH_MISMATCH")
    entries = revision.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise StaticBrowserError("SOURCE_ENTRIES_INVALID")
    files = []
    for item in entries:
        if not isinstance(item, dict):
            raise StaticBrowserError("SOURCE_ENTRY_INVALID")
        digest = item.get("sha256_digest")
        require_hash(digest)
        if item.get("storage_key") != f"sha256/{digest[:2]}/{digest}":
            raise StaticBrowserError("SOURCE_ADDRESS_INVALID")
        validate_path(item.get("normalized_path"))
        if (
            type(item.get("size_bytes")) is not int
            or not 0 <= item["size_bytes"] <= MAX_SOURCE_BYTES
        ):
            raise StaticBrowserError("SOURCE_ENTRY_SIZE_INVALID")
        data = read_content(item["storage_key"])
        if (
            not isinstance(data, bytes)
            or len(data) != item["size_bytes"]
            or (hashlib.sha256(data).hexdigest() != digest)
        ):
            raise StaticBrowserError("SOURCE_BLOB_MISMATCH")
        files.append(StaticFile(item["normalized_path"], data))
    return StaticBrowserJob(
        project_id,
        owner_user_id,
        UUID(str(revision["id"])),
        str(revision["content_hash"]),
        str(revision["source_tree_hash"]),
        runner_manifest_content_hash,
        harness_sha256,
        tuple(files),
        scenarios,
    )
