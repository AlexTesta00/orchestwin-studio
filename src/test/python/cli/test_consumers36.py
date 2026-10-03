from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts.provided_prototypes import provided_prototype_from_payload
from orchestwin.cli.api import workflow_inputs
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.code_order import approved_folder
from orchestwin.cli.mcp.knowledge import FolderProblem, load
from orchestwin.cli.mcp.tools import Session, get_design
from orchestwin.cli.project import ProjectFolder
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_LIMITS,
    create_workflow_decision,
)

from ..artifacts.test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_CODES,
    LIGHT_CHOICES,
    build,
    requirement_ids,
)
from .support.folders import valid_files
from .support.terminal import link_folder
from .test_api_design import design_session


def supplied(project_id, definition=None):
    mockup = build()
    return provided_prototype_from_payload(
        {
            "title": mockup.title,
            "declared_origin": "Figma",
            "visual_choices": LIGHT_CHOICES.to_snapshot(),
            "mockup": {
                "styles": mockup.styles,
                "screens": [item.to_snapshot() for item in mockup.screens],
            },
        },
        prototype_id=ALTERNATIVE_ID,
        code="PRT-001",
        project_id=UUID(project_id),
        version_number=1,
        based_on_version_number=None,
        definition_reference=definition
        or {
            "artifact_id": "26a781d3-45fd-490c-bd2b-ff541e517e70",
            "version_number": 1,
            "content_hash": "a" * 64,
        },
        requirement_ids_by_code=requirement_ids(BASE_CODES),
        created_at=datetime(2026, 10, 3, 18, tzinfo=UTC),
    ).to_snapshot()


def seed(session):
    snapshot = supplied(session.project.id)
    decision = create_workflow_decision(
        decision_id=UUID("f62ad576-9b6c-4c06-85e1-9aee518689b0"),
        project_id=UUID(session.project.id),
        sequence=1,
        target="EVIDENCE",
        action="DECLARE_MISSING",
        reason="No interviews yet.",
        base_context={},
        recorded_at=datetime(2026, 10, 3, 18, tzinfo=UTC),
    )
    session.studio.seed_workflow_inputs(
        session.project, decisions=[decision], prototypes=[snapshot], gate={"status": "APPROVED"}
    )
    return snapshot


@pytest.mark.parametrize("language", ["it", "en"])
def test_ut_design_show_and_open_consult_supplied_prototype_without_post(tmp_path, language):
    with design_session(tmp_path) as session:
        snapshot = seed(session)
        before = session.writes()
        show = session.ut("design", "show", language=language)
        opened = session.ut("design", "open", "SCR-002", language=language)
        assert show.status == opened.status == 0
        assert "PRT-001" in show.output and "Figma" in show.output
        assert "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE" in show.output
        assert opened.opened == (session.uri("PRT-001.html"),)
        html = (session.previews / "PRT-001.html").read_text(encoding="utf-8")
        assert "Content-Security-Policy" in html and "data-entry" in html
        assert "<script" not in html
        assert session.writes() == before
        assert workflow_inputs.state(session.client(), session.project.id)["prototype"] == snapshot


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (("review",), "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE"),
        (("change", "Change title"), "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"),
        (("choose", "PRT-001"), "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"),
        (("approve",), "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"),
        (("regenerate",), "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"),
    ],
)
def test_ut_design_unsupported_consumers_refuse_before_a_post(tmp_path, arguments, code):
    with design_session(tmp_path) as session:
        seed(session)
        before = session.writes()
        result = session.ut("design", *arguments)
        assert result.status == 1
        assert code in result.errors
        assert session.writes() == before


def test_sections_read_workflow_records_and_validation_walkthrough_refuses(tmp_path):
    with design_session(tmp_path) as session:
        seed(session)
        shown = session.ut("sections", "--json")
        assert shown.status == 0
        assert (
            json.loads(shown.output)["workflow_inputs"]["decisions"][0]["reason"]
            == "No interviews yet."
        )
        read = workflow_inputs.records(session.client(), session.project.id)
        assert read["limits"] == list(PROVIDED_PROTOTYPE_LIMITS)
        walkthrough = session.ut("validation", "walkthrough", "SCN-001")
        assert walkthrough.status == 1
        assert "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE" in walkthrough.errors


def test_twin_evaluation_refuses_and_read_routes_are_owner_scoped(tmp_path):
    with design_session(tmp_path) as session:
        snapshot = seed(session)
        client = session.client()
        response = client.request("POST", f"{session.base}/design/evaluations", body={})
        assert response.status == 409
        assert response.json()["detail"]["code"] == "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE"
        foreign = "f02c461b-1875-4a8b-b9a9-9557f6367e48"
        for suffix in (
            "workflow-inputs",
            "provided-prototypes/state",
            "provided-prototypes/current",
            "provided-prototypes/gate/current",
            f"provided-prototypes/{snapshot['id']}/document",
        ):
            assert client.request("GET", f"/projects/{foreign}/{suffix}").status == 404


def local(tmp_path):
    files = valid_files()
    manifest = json.loads(files["orchestwin.json"])
    reference = manifest["stages"]["requirements"]
    snapshot = supplied(
        manifest["project"]["id"],
        {
            "artifact_id": reference["version_id"],
            "version_number": reference["version_number"],
            "content_hash": reference["content_hash"],
        },
    )
    approved = {
        "artifact_id": snapshot["id"],
        "version_number": snapshot["version_number"],
        "content_hash": snapshot["content_hash"],
        "gate_status": "APPROVED",
    }
    manifest["workflow_inputs"] = {
        "schema_version": 1,
        "decisions_document": "workflow/decisions.json",
        "prototypes_document": "design/provided-prototypes.json",
        "limits": list(PROVIDED_PROTOTYPE_LIMITS),
        "approved_prototype": approved,
    }
    files["orchestwin.json"] = json.dumps(manifest)
    files["workflow/decisions.json"] = json.dumps({"decisions": []})
    files["design/provided-prototypes.json"] = json.dumps(
        {"prototypes": [snapshot], "approved_prototype": approved}
    )
    for relative, content in files.items():
        target = tmp_path / "project" / "orchestwin" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    link_folder(tmp_path / "project", project_id=manifest["project"]["id"])
    return ProjectFolder(tmp_path / "project"), snapshot


def test_offline_ut_code_refuses_approved_supplied_prototype_and_mcp_reads_its_screens(tmp_path):
    project, snapshot = local(tmp_path)
    with pytest.raises(CliError) as caught:
        approved_folder(project)
    assert caught.value.code == "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE"
    session = Session(SimpleNamespace(), project, project.link(), "en")
    design = get_design(session, {"screen": "SCR-002"})
    assert design["source"] == "PROVIDED_PROTOTYPE"
    assert design["prototype"] == snapshot
    assert [item["code"] for item in design["screens"]] == ["SCR-002"]
    assert design["limits"] == list(PROVIDED_PROTOTYPE_LIMITS)


def test_offline_forged_approval_and_modified_record_are_rejected(tmp_path):
    project, _ = local(tmp_path)
    path = project.knowledge / "design" / "provided-prototypes.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["approved_prototype"]["content_hash"] = "b" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FolderProblem):
        load(project.knowledge).workflow_inputs()
