from __future__ import annotations

import asyncio
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.agents.team_gate import agent_team_artifact_reference
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.artifacts.design_package_export import (
    DESIGN_PACKAGE_INDEX,
    DESIGN_PACKAGE_MANIFEST,
    DesignPackageExportError,
    DesignPackageExportService,
    DesignPackageSources,
    build_design_package,
    design_package_files,
)
from orchestwin.projects.brief_gate import project_brief_artifact_reference
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.twins.test_user_modeling_gate import snapshot_version
from src.test.python.workflow.test_governed_project_setup import build_ready_project

from .design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    design_package,
    design_version,
    requirements_version,
)

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)
EXPECTED_ENTRIES = (
    DESIGN_PACKAGE_INDEX,
    "brief/brief.json",
    "brief/brief.md",
    "design/critiques.md",
    "design/design.json",
    "design/design.md",
    "design/mockups.md",
    DESIGN_PACKAGE_MANIFEST,
    "requirements/requirements.json",
    "requirements/requirements.md",
    "team/team.json",
    "team/team.md",
    "twins/twins.json",
    "twins/twins.md",
)


def approved_gate(version, gate_type: HumanGateType, reference, base: int) -> HumanGate:
    draft = create_human_gate(
        gate_id=UUID(int=base),
        project_id=version.project_id,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=reference,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=1),
        event_id=UUID(int=base + 1),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=2),
        event_id=UUID(int=base + 2),
    )
    return approved.gate


def sources() -> DesignPackageSources:
    scenario = build_ready_project()
    modeling = snapshot_version()
    requirements = requirements_version()
    design = design_version()
    return DesignPackageSources(
        project_id=PROJECT_ID,
        brief=scenario.brief_version,
        brief_gate=approved_gate(
            scenario.brief_version,
            HumanGateType.PROJECT_BRIEF,
            project_brief_artifact_reference(scenario.brief_version),
            1000,
        ),
        team=scenario.team_version,
        team_gate=approved_gate(
            scenario.team_version,
            HumanGateType.AGENT_TEAM,
            agent_team_artifact_reference(scenario.team_version),
            2000,
        ),
        modeling=modeling,
        modeling_gate=approved_gate(
            modeling,
            HumanGateType.USER_MODELING,
            user_modeling_artifact_reference(modeling),
            3000,
        ),
        requirements=requirements,
        requirements_gate=approved_gate(
            requirements,
            HumanGateType.REQUIREMENTS,
            requirements_artifact_reference(requirements),
            4000,
        ),
        design=design,
        design_gate=approved_gate(
            design, HumanGateType.DESIGN, design_artifact_reference(design), 5000
        ),
    )


def test_package_holds_every_approved_stage_as_markdown_and_exact_json() -> None:
    package = sources()

    archive = build_design_package(package)

    assert archive.file_name == f"orchestwin-{PROJECT_ID}-design-package.zip"
    assert archive.entries == EXPECTED_ENTRIES
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert tuple(bundle.namelist()) == EXPECTED_ENTRIES
        files = {name: bundle.read(name).decode("utf-8") for name in bundle.namelist()}
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in bundle.infolist())
    manifest = json.loads(files[DESIGN_PACKAGE_MANIFEST])
    assert manifest["project_id"] == str(PROJECT_ID)
    assert manifest["stages"]["design"]["version_number"] == package.design.version_number
    assert manifest["stages"]["design"]["content_hash"] == package.design.content_hash
    assert manifest["stages"]["brief"]["gate"]["status"] == "APPROVED"
    assert set(manifest["files"]) == set(EXPECTED_ENTRIES) - {
        DESIGN_PACKAGE_INDEX,
        DESIGN_PACKAGE_MANIFEST,
    }
    assert json.loads(files["brief/brief.json"])["brief"] == package.brief.brief.to_snapshot()
    assert json.loads(files["team/team.json"])["proposal"] == package.team.proposal.to_snapshot()
    assert (
        json.loads(files["twins/twins.json"])["snapshot"] == package.modeling.snapshot.to_snapshot()
    )
    assert (
        json.loads(files["requirements/requirements.json"])["specification"]
        == package.requirements.specification.to_snapshot()
    )
    assert (
        json.loads(files["design/design.json"])["package"] == package.design.package.to_snapshot()
    )
    assert package.brief.brief.to_snapshot()["fields"]["name"] in files["brief/brief.md"]
    assert "Workflow orchestrator" in files["team/team.md"]
    assert "Receptionist Twin" in files["twins/twins.md"]
    assert "REQ-001" in files["requirements/requirements.md"]
    assert "Guided reservation flow" in files["design/design.md"]
    assert "CRQ-001" in files["design/critiques.md"]
    assert "SCR-001" in files["design/mockups.md"]
    assert package.design.content_hash in files[DESIGN_PACKAGE_INDEX]
    assert "not provided" not in files["design/mockups.md"].split("## Transitions")[0]


def test_package_bytes_are_reproducible() -> None:
    first = build_design_package(sources())
    second = build_design_package(sources())

    assert first.content == second.content
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64


def test_package_without_prototype_says_so_instead_of_failing() -> None:
    package = replace(
        sources(), design=design_version(package=design_package(include_prototype=False))
    )

    files = design_package_files(package)

    assert "No declarative prototype was recorded" in files["design/mockups.md"]
    assert files["design/mockups.md"].startswith("# Mockups of the selected alternative")


class FakeQuery:
    def __init__(self, value) -> None:
        self.value = value
        self.calls: list[dict[str, UUID]] = []

    async def current_brief(self, **scope):
        self.calls.append(scope)
        return self.value

    async def current(self, **scope):
        self.calls.append(scope)
        return self.value

    async def current_snapshot(self, **scope):
        self.calls.append(scope)
        return self.value

    async def current_gate(self, **scope):
        self.calls.append(scope)
        return self.value


def service(package: DesignPackageSources, **overrides) -> DesignPackageExportService:
    values = {
        "brief": package.brief,
        "brief_gate": package.brief_gate,
        "team": package.team,
        "team_gate": package.team_gate,
        "modeling": package.modeling,
        "modeling_gate": package.modeling_gate,
        "requirements": package.requirements,
        "requirements_gate": package.requirements_gate,
        "design": package.design,
        "design_gate": package.design_gate,
    }
    values.update(overrides)
    return DesignPackageExportService(
        project_service=FakeQuery(values["brief"]),
        brief_gate_service=FakeQuery(values["brief_gate"]),
        team_proposal_service=FakeQuery(values["team"]),
        agent_team_service=FakeQuery(values["team_gate"]),
        user_modeling_services=SimpleNamespace(
            queries=FakeQuery(values["modeling"]), gates=FakeQuery(values["modeling_gate"])
        ),
        requirements_query_service=FakeQuery(values["requirements"]),
        requirements_gate_service=FakeQuery(values["requirements_gate"]),
        design_query_service=FakeQuery(values["design"]),
        design_gate_service=FakeQuery(values["design_gate"]),
    )


def test_service_exports_the_archive_of_the_owner_scoped_project() -> None:
    package = sources()
    exporter = service(package)

    archive = asyncio.run(exporter.export(owner_user_id=OWNER_ID, project_id=PROJECT_ID))

    assert archive.content == build_design_package(package).content
    assert exporter.project_service.calls == [{"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}]
    assert exporter.design_gate_service.calls == [
        {"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    ]


@pytest.mark.parametrize(
    "override,code",
    [
        ({"brief": None}, "PROJECT_NOT_FOUND"),
        ({"brief_gate": None}, "BRIEF_APPROVAL_REQUIRED"),
        ({"team": None}, "TEAM_APPROVAL_REQUIRED"),
        ({"team_gate": None}, "TEAM_APPROVAL_REQUIRED"),
        ({"modeling_gate": None}, "USER_MODELING_APPROVAL_REQUIRED"),
        ({"requirements": None}, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design_gate": None}, "DESIGN_APPROVAL_REQUIRED"),
    ],
)
def test_service_reports_the_first_missing_approval(override, code) -> None:
    exporter = service(sources(), **override)

    with pytest.raises(DesignPackageExportError) as failure:
        asyncio.run(exporter.export(owner_user_id=OWNER_ID, project_id=PROJECT_ID))

    assert failure.value.code == code


def test_service_rejects_a_gate_that_approves_another_version() -> None:
    package = sources()
    stale_reference = replace(design_artifact_reference(package.design), content_hash="0" * 64)
    stale = approved_gate(package.design, HumanGateType.DESIGN, stale_reference, 6000)
    exporter = service(package, design_gate=stale)

    with pytest.raises(DesignPackageExportError) as failure:
        asyncio.run(exporter.export(owner_user_id=OWNER_ID, project_id=PROJECT_ID))

    assert failure.value.code == "DESIGN_APPROVAL_REQUIRED"
