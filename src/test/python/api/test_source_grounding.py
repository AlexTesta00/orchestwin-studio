"""Repairs retrieve the original source's architecture, never an unrelated latest version."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from orchestwin.api import source_generation as source
from src.test.python.integration.test_model_source_generation_postgres import artifacts


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "architecture",
        "requirements",
        "design",
        "architecture_hash",
        "requirements_hash",
        "design_hash",
        "ambiguous",
        "reference",
    ],
)
def test_repair_grounding_verifies_owned_exact_references(monkeypatch, failure):
    requirements, design, architecture = artifacts()
    owner, project, session = architecture.created_by_user_id, architecture.project_id, object()
    repositories = {}
    for name, repository, version in (
        ("architecture", "SqlAlchemyArchitecturePackageRepository", architecture),
        ("requirements", "SqlAlchemyRequirementsSpecificationRepository", requirements),
        ("design", "SqlAlchemyDesignPackageRepository", design),
    ):
        returned = (
            None
            if failure == name
            else SimpleNamespace(version_number=version.version_number, content_hash="f" * 64)
            if failure == name + "_hash"
            else version
        )
        instance = SimpleNamespace(get=AsyncMock(return_value=returned))
        repositories[name] = instance

        def factory(supplied_session, *, owner_user_id, instance=instance):
            assert supplied_session is session and owner_user_id == owner
            return instance

        monkeypatch.setattr(source, repository, factory)
    reference = SimpleNamespace(
        kind=SimpleNamespace(value="ARCHITECTURE"),
        reference_id=("unrelated:" if failure == "reference" else "architecture:")
        + str(architecture.id),
        version_number=architecture.version_number,
        content_hash=architecture.content_hash,
    )
    base = SimpleNamespace(provenance_references=[reference] * (2 if failure == "ambiguous" else 1))
    call = source._repair_grounding(session, owner_user_id=owner, project_id=project, base=base)
    if failure:
        with pytest.raises(HTTPException) as raised:
            asyncio.run(call)
        assert raised.value.status_code == 409
        return
    result = asyncio.run(call)
    assert result["status"] == "EXACT_SOURCE_ARCHITECTURE"
    for name, version in (
        ("requirements", requirements),
        ("design", design),
        ("architecture", architecture),
    ):
        repositories[name].get.assert_awaited_once_with(project_id=project, version_id=version.id)
        assert result[name]["reference"]["content_hash"] == version.content_hash
    assert result["requirements"]["content"] == requirements.to_snapshot()["specification"]


def test_imported_source_without_architecture_does_not_invent_approved_context():
    result = asyncio.run(
        source._repair_grounding(
            object(),
            owner_user_id="unused",
            project_id="unused",
            base=SimpleNamespace(provenance_references=[]),
        )
    )
    assert result == {"status": "SOURCE_ONLY_NO_ARCHITECTURE_REFERENCE"}
