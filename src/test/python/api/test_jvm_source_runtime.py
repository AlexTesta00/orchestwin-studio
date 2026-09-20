"""Initial sources require current Architecture approval and verified binary launchers."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from orchestwin.api import jvm_source_runtime as sut
from orchestwin.api.jvm_execution import (
    JvmSourcePlanFileCommand,
    JvmSourceProvenanceCommand,
    JvmSourceRevisionCreateCommand,
)
from orchestwin.jvm_execution.validation_fixtures import fixture_bytes
from src.test.python.jvm_execution.api_support import ROOT, TARGETS


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    "scenario",
    [
        "valid",
        "pending",
        "foreign",
        "wrong_mode",
        "missing_architecture",
        "stale_gate",
        "stale_provenance",
        "existing_source",
        "changed_recipe",
    ],
)
def test_sources_require_architecture_and_assemble_verified_recipe(
    tmp_path, monkeypatch, target, scenario
):
    owner, project, architecture_id = uuid4(), uuid4(), uuid4()
    architecture = SimpleNamespace(id=architecture_id, version_number=1, content_hash="a" * 64)
    gate = SimpleNamespace(
        artifact=sut.GateArtifactReference(
            project, sut.HumanGateType.ARCHITECTURE, architecture_id, 1, "a" * 64
        ),
        status=sut.HumanGateStatus.PENDING_APPROVAL
        if scenario == "pending"
        else sut.HumanGateStatus.APPROVED,
    )
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    session.scalar = AsyncMock(
        return_value=None
        if scenario == "foreign"
        else SimpleNamespace(
            mode="BROWNFIELD_ANALYSIS" if scenario == "wrong_mode" else "GREENFIELD_GENERATION"
        )
    )
    if scenario == "stale_gate":
        gate.artifact = replace(gate.artifact, content_hash="b" * 64)
    revisions = SimpleNamespace(
        current=AsyncMock(return_value=object() if scenario == "existing_source" else None),
        append=AsyncMock(return_value=SimpleNamespace(status=SimpleNamespace(value="APPENDED"))),
    )
    monkeypatch.setattr(
        sut,
        "SqlAlchemyArchitecturePackageRepository",
        lambda *args, **kwargs: SimpleNamespace(
            get_current_owned_for_update=AsyncMock(
                return_value=None if scenario == "missing_architecture" else architecture
            )
        ),
    )
    monkeypatch.setattr(
        sut,
        "SqlAlchemyHumanGateRepository",
        lambda *args, **kwargs: SimpleNamespace(
            get_latest_owned_for_update=AsyncMock(return_value=gate)
        ),
    )
    monkeypatch.setattr(
        sut, "SqlAlchemyJvmSourceRevisionRepository", lambda *args, **kwargs: revisions
    )
    files = fixture_bytes(ROOT, target)
    command = JvmSourceRevisionCreateCommand(
        target,
        "Create reviewed source.",
        tuple(
            JvmSourcePlanFileCommand(path, data.decode(), "text/plain")
            for path, data in files.items()
            if path.startswith("src/")
        ),
        (
            JvmSourceProvenanceCommand(
                sut.JvmSourceProvenanceKind.ARCHITECTURE,
                f"architecture:{architecture_id}",
                1,
                "b" * 64 if scenario == "stale_provenance" else "a" * 64,
            ),
        ),
    )
    if scenario == "changed_recipe":
        name = "build.sbt" if target.value == "JVM_SCALA" else "build.gradle.kts"
        command = replace(
            command,
            files=(
                *command.files,
                JvmSourcePlanFileCommand(name, "unreviewed build logic", "text/plain"),
            ),
        )
    service = sut.SqlAlchemyJvmSourceApiService(
        lambda: session, content_root=tmp_path / "objects", repo_root=ROOT
    )
    result = asyncio.run(
        service.create_source_revision(owner_user_id=owner, project_id=project, command=command)
    )
    if scenario == "valid":
        assert result.status.value == "SOURCE_REVISION_CREATED"
        revision = revisions.append.await_args.args[0]
        assert revision.origin.value == "GENERATED_PLAN"
        assert sut.read_source_objects(revision, service.root) == files
    else:
        expected = {
            "pending": "APPROVAL_REQUIRED",
            "foreign": "NOT_FOUND",
            "wrong_mode": "CONFLICT",
            "missing_architecture": "APPROVAL_REQUIRED",
            "stale_gate": "APPROVAL_REQUIRED",
            "stale_provenance": "CONFLICT",
            "existing_source": "CONFLICT",
            "changed_recipe": "INVALID",
        }
        assert result.status.value == expected[scenario]
        revisions.append.assert_not_awaited()
        assert not (tmp_path / "objects").exists()
