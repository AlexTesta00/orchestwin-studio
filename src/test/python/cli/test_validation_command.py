from __future__ import annotations

import json

import pytest

from orchestwin.cli import folder
from orchestwin.cli.mcp.knowledge import load
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.validation import validation_overview
from src.test.python.cli.support.fake_studio import FakeStudio, _Call, _Refusal, route_table
from src.test.python.cli.support.terminal import run_ut, store_session
from src.test.python.cli.support.transports import API, NoNetwork, ScriptedTransport
from src.test.python.cli.test_mcp_tools import build, run
from src.test.python.cli.test_why_command import project_with_files
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT
from src.test.python.knowledge.validation_fixtures import validation_sources


@pytest.mark.parametrize("language", ["it", "en"])
@pytest.mark.parametrize("retired", [False, True])
def test_validation_reads_exact_records_offline_without_login_network_or_writing(
    tmp_path, language, retired
):
    sources = validation_sources(human=True, retired=retired, version=2)
    package = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    project = project_with_files(tmp_path, package.files)
    before = folder.read_files(project.knowledge)
    expected = load(project.knowledge).validation(project_id=str(sources.project_id))
    result = run_ut(
        ["--lang", language, "validation", "--offline", "--json"], tmp_path, transport=NoNetwork()
    )
    assert result.status == 0, result.errors
    assert json.loads(result.output) == expected
    assert expected["hypotheses"][0]["state"] == ("TO_VERIFY" if retired else "CONFIRMED")
    assert expected["outcomes"][0]["effective_status"] == ("RETIRED" if retired else "ACTIVE")
    assert folder.read_files(project.knowledge) == before


def test_validation_online_and_walkthrough_use_only_get(tmp_path):
    project = project_with_files(tmp_path)
    store_session(tmp_path)
    knowledge = load(project.knowledge)
    answer = knowledge.validation()
    walkthrough = knowledge.walkthrough("SCN-001")
    transport = ScriptedTransport().expect(
        "GET", f"{API}/projects/{project.link().project_id}/validation", body=answer
    )
    result = run_ut(["validation", "--json"], tmp_path, transport=transport)
    assert result.status == 0, result.errors
    assert json.loads(result.output) == answer
    transport.assert_done()

    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{project.link().project_id}/validation/walkthrough?scenario_key=SCN-001",
        body=walkthrough,
    )
    result = run_ut(
        ["validation", "walkthrough", "SCN-001", "--json"], tmp_path, transport=transport
    )
    assert result.status == 0, result.errors
    assert json.loads(result.output) == walkthrough
    transport.assert_done()


@pytest.mark.parametrize("language", ["it", "en"])
def test_default_validation_shows_candidate_count_with_titles_only_on_request(tmp_path, language):
    project = project_with_files(tmp_path)
    expected = load(project.knowledge).validation()
    title = expected["candidates"][0]["title"]
    default = run_ut(
        ["--lang", language, "validation", "--offline"], tmp_path, transport=NoNetwork()
    )
    details = run_ut(
        ["--lang", language, "validation", "--offline", "--all"], tmp_path, transport=NoNetwork()
    )
    assert default.status == details.status == 0
    assert str(expected["candidate_count"]) in default.output
    assert "--all" in default.output
    assert title not in default.output
    assert title in details.output


def test_walkthrough_offline_preserves_source_steps_and_declares_missing_step_anchor(tmp_path):
    project = project_with_files(tmp_path)
    expected = load(project.knowledge).walkthrough("SCN-001")
    result = run_ut(
        ["validation", "walkthrough", "SCN-001", "--offline", "--json"],
        tmp_path,
        transport=NoNetwork(),
    )
    assert result.status == 0, result.errors
    assert json.loads(result.output) == expected
    assert len(expected["steps"]) == 4
    assert all(
        step["anchors"] == [] and step["gaps"][0]["code"] == "STEP_ANCHOR_NOT_ATTESTED"
        for step in expected["steps"]
    )


@pytest.mark.parametrize("status", [403, 404, 409])
def test_validation_does_not_fall_back_after_authorization_or_context_failure(tmp_path, status):
    project = project_with_files(tmp_path)
    store_session(tmp_path)
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{project.link().project_id}/validation",
        status=status,
        body={"detail": {"code": "VALIDATION_CONTEXT_CHANGED"}},
    )
    result = run_ut(["validation", "--json"], tmp_path, transport=transport)
    assert result.status != 0
    assert result.output == ""
    assert "Dossier" not in result.errors
    transport.assert_done()


@pytest.mark.parametrize(
    "arguments",
    [
        ["validation", "save"],
        ["validation", "outcomes"],
        ["validation", "walkthrough"],
        ["validation", "--alternative", "anything"],
    ],
)
def test_validation_has_no_creation_or_outcome_registration_command(tmp_path, arguments):
    project_with_files(tmp_path)
    result = run_ut(arguments, tmp_path, transport=NoNetwork())
    assert result.status == 2


def test_mcp_appends_two_readonly_tools_without_changing_the_first_thirteen(tmp_path):
    project = project_with_files(tmp_path)
    tools, bundle = build(tmp_path)
    definitions = tools.definitions()
    assert [item["name"] for item in definitions[11:]] == [
        "get_evidence",
        "get_why",
        "get_validation",
        "get_scenario_walkthrough",
    ]
    assert all(item["annotations"]["readOnlyHint"] is True for item in definitions[13:])
    assert run(tools, "get_validation") == load(project.knowledge).validation()
    assert run(tools, "get_scenario_walkthrough", scenario_key="SCN-001") == load(
        project.knowledge
    ).walkthrough("SCN-001")
    assert bundle.errors == ""


def test_fake_studio_exposes_only_the_two_new_read_routes_and_uses_the_common_builder():
    paths = [(method, path) for method, path in route_table() if "/validation" in path]
    assert len(paths) == 2
    assert all(method == "GET" for method, _ in paths)
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", "Test-password-not-real!")
    project = studio.seed_project(
        owner="owner@example.com", name="Synthetic fixture", through="design"
    )
    call = _Call(
        "GET",
        "/projects/x/validation",
        project.account,
        {"project_id": project.id},
        {},
        {},
        b"",
        False,
    )
    expected = validation_overview(document=studio._why_document(project, validation_context=True))
    assert studio._route_validation(call).body == expected
    call.params["project_id"] = "00000000-0000-4000-8000-000000000099"
    with pytest.raises(_Refusal):
        studio._route_validation(call)
    assert project.usage == []


def test_fake_dossier_includes_existing_synthetic_feedback_and_its_owner_decisions(tmp_path):
    from uuid import UUID

    from orchestwin.artifacts.design_finding_validations import create_finding_validation
    from src.test.python.cli.test_api_design import choose, design_session
    from src.test.python.cli.test_design_command import ready

    with design_session(tmp_path) as session:
        ready(session)
        choose(session, "DES-001")
        reviewed = session.ut("design", "review", answers=["y"])
        assert reviewed.status == 0, reviewed.errors
        run = session.project.runs[0]
        response = run["responses"][0]
        decision = create_finding_validation(
            evaluation_run_id=UUID(run["id"]),
            twin_id=UUID(response["twin_id"]),
            finding_id=response["findings"][0]["finding_id"],
            sequence_number=1,
            project_id=UUID(session.project.id),
            owner_user_id=UUID(session.project.account.id),
            decision="OWNER_DISMISSED",
            note="Fabricated owner decision; not a session with people.",
            decided_at=PUBLISHED_AT,
        )
        session.project.finding_decisions.append(decision.to_snapshot())
        approved = session.ut("design", "approve")
        assert approved.status == 0, approved.errors
        published = session.ut("package", "publish")
        assert published.status == 0, published.errors
        knowledge = load(session.folder / "orchestwin")
        reviews = knowledge.read("twins/feedback/reviews.json")
        assert reviews["runs"] == [item for item in reversed(session.project.runs)]
        assert reviews["decisions"] == session.project.finding_decisions
        assert knowledge.validation()["candidate_count"] >= len(
            [node for node in knowledge.why()["nodes"] if node["kind"] == "SYNTHETIC_FINDING"]
        )


@pytest.mark.parametrize(
    "references, valid",
    [
        ({"REQ-001": "35000000-0000-4000-8000-000000000001"}, True),
        ({"REQ-001": "not-a-uuid"}, False),
        ({"unknown": "35000000-0000-4000-8000-000000000001"}, False),
    ],
)
def test_offline_verification_enforces_the_published_mockup_reference_map(references, valid):
    from orchestwin.cli.mcp.verification import schema_valid
    from orchestwin.knowledge.schema import knowledge_schemas

    schema = knowledge_schemas(design_additions=True)["design"]
    rule = schema["$defs"]["BoundGeneratedMockup"]["properties"]["requirement_ids_by_code"]
    assert schema_valid(references, rule, schema) is valid
