"""Deterministic persistence for observed formal case-study environment identities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from orchestwin.evaluation.case_environment import (
    CaseStudyContainerImage,
    CaseStudyEnvironmentIdentity,
    CaseStudyRuntimeVersion,
)


def write_case_study_environment_identity(
    path: Path,
    environment: CaseStudyEnvironmentIdentity,
    *,
    overwrite: bool = False,
) -> None:
    """Persist one observed environment identity atomically without overwriting by default."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"case-study environment identity already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        f"{json.dumps(environment.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_case_study_environment_identity(path: Path) -> CaseStudyEnvironmentIdentity:
    """Load an environment record and revalidate every pinned version and digest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaseStudyEnvironmentIdentity(
        schema_version=payload["schema_version"],
        platform_commit=payload["platform_commit"],
        execution_profile=payload["execution_profile"],
        operating_system=payload["operating_system"],
        architecture=payload["architecture"],
        python_version=payload["python_version"],
        runtime_versions=tuple(
            CaseStudyRuntimeVersion(
                component=item["component"],
                version=item["version"],
            )
            for item in payload["runtime_versions"]
        ),
        container_images=tuple(
            CaseStudyContainerImage(
                name=item["name"],
                digest=item["digest"],
            )
            for item in payload["container_images"]
        ),
        network_policy=payload["network_policy"],
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        content_hash=payload["content_hash"],
    )
