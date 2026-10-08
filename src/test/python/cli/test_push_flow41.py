from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import modeling as modeling_api
from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.api import team as team_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import push as push_flow
from orchestwin.cli.flows.push import FileChange

from .support.folders import ARCHIVE_PROJECT_ID, partial_archive, valid_archive, valid_files
from .support.terminal import (
    command_context,
    environment,
    link_folder,
    run_ut,
    store_session,
)
from .support.transports import NoNetwork, ScriptedTransport

API = "/api/v1"
BASE = f"{API}/projects/{ARCHIVE_PROJECT_ID}"
WIDE = {"COLUMNS": "400"}
REQUIREMENTS = "requirements/requirements.json"
VERSION_ID = "00000000-0000-4000-8000-00000000b001"
DIFF_ID = "00000000-0000-4000-8000-00000000b002"
TWIN_ID = "00000000-0000-4000-8000-00000000b003"
PERSONA_ID = "00000000-0000-4000-8000-00000000b004"


def context_of(tmp_path: Path):
    return command_context(environment(tmp_path, transport=NoNetwork(), variables=WIDE))


def archive_reply(transport: ScriptedTransport, number: int, content: bytes) -> None:
    transport.expect(
        "GET",
        f"{BASE}/knowledge-packages/{number}/archive",
        body=content,
        headers={"X-Content-SHA256": hashlib.sha256(content).hexdigest()},
    )


def linked(tmp_path: Path, archive: bytes) -> Path:
    project = link_folder(tmp_path / "project", project_id=ARCHIVE_PROJECT_ID)
    knowledge.unpack(archive, project.knowledge)
    store_session(tmp_path)
    return project.knowledge


def observation(key: str, items: list[str]) -> dict[str, object]:
    return {
        "observation_key": key,
        "value": {"kind": "ITEMS", "text": None, "items": items, "reason": None},
        "epistemic_status": "MODEL_INFERRED",
        "confidence": 0.6,
        "provenance": [{"source_kind": "PROJECT_BRIEF", "source_id": "brief"}],
        "human_validation": "REQUIRED",
        "rationale": "From the brief.",
    }


def twin(name: str, goals: list[str], extra: list[dict[str, object]] | None = None) -> dict:
    return {
        "twin_id": TWIN_ID,
        "id": VERSION_ID,
        "profile": {
            "name": name,
            "persona_reference": {"persona_id": PERSONA_ID},
            "observations": [observation("user_twin.goals", goals), *(extra or [])],
        },
    }


def test_the_comparison_classifies_every_file() -> None:
    base = {
        "orchestwin.json": "{}\n",
        "brief/brief.md": "# Brief\n",
        "brief/brief.json": '{"brief": {}}\n',
        "design/design.json": '{"package": {}}\n',
        "state/state.md": "line one\nline two\n",
        "twins/twins.md": "# Twins\n",
    }
    here = {
        "orchestwin.json": '{"changed": true}\n',
        "brief/brief.md": "# Brief\r\n",
        "brief/brief.json": '{"brief": {"fields": {}}}\n',
        "state/state.md": "line one\nline three\n",
        "twins/twins.md": "# Twins\n",
        "notes.txt": "mine\n",
        "team/team.json": '{"proposal": {}}\n',
    }

    found = push_flow.compared(base, here)

    assert found == [
        FileChange("brief/brief.json", "changed", "pushable"),
        FileChange("design/design.json", "deleted", "pushable"),
        FileChange("notes.txt", "added", "unknown"),
        FileChange("state/state.md", "changed", "derived"),
        FileChange("team/team.json", "added", "pushable"),
    ]
    assert [item.stage for item in found] == ["brief", "design", None, None, "team"]


def test_the_differences_name_the_entries_by_code_or_by_field() -> None:
    old = {
        "requirements": [
            {"code": "REQ-001", "statement": "Enter the amount"},
            {"code": "REQ-002", "statement": "Choose the tip"},
        ],
        "risks": [{"code": "RSK-001"}, {"code": "RSK-002"}],
        "scenarios": [{"code": "SCN-001"}, {"code": "SCN-002"}],
        "open_questions": ["Who pays?"],
        "schema_version": 2,
        "members": [{"agent_id": "UX_UI_DESIGNER"}],
    }
    new = {
        "requirements": [
            {"code": "REQ-001", "statement": "Enter the amount of the bill"},
            {"code": "REQ-002", "statement": "Choose the tip"},
            {"code": "REQ-003", "statement": "Split the bill"},
        ],
        "risks": [{"code": "RSK-001"}],
        "scenarios": [{"code": "SCN-002"}, {"code": "SCN-001"}],
        "open_questions": ["Who pays?", "In cash?"],
        "schema_version": 2,
        "members": [{"agent_id": "UX_UI_DESIGNER"}, {"agent_id": "SECURITY_REVIEWER"}],
        "needs": [],
    }

    assert push_flow.differences(new, old) == [
        ("~", "requirements REQ-001"),
        ("+", "requirements REQ-003"),
        ("-", "risks RSK-002"),
        ("~", "scenarios"),
        ("~", "open_questions"),
        ("+", "members SECURITY_REVIEWER"),
        ("+", "needs"),
    ]
    assert push_flow.differences({"a": 1}, None) == [("+", "a")]
    assert push_flow.differences({}, {"a": 1}) == [("-", "a")]
    assert push_flow.identified([{"id": "x"}, {"id": "x"}]) is None
    assert push_flow.identified("text") is None
    assert push_flow.identified([]) == {}


def test_the_brief_body_keeps_the_known_fields_and_frees_the_filled_unknowns() -> None:
    content = {
        "schema_version": 1,
        "fields": {
            "name": "Calcolo mancia",
            "goals": ["Split the bill"],
            "budget": None,
            "audience": "Friends",
            "colour": "green",
        },
        "unknown_fields": ["budget", "goals", "nothing"],
    }

    body, ignored = push_flow.brief_body(content)

    assert set(body) == {*push_flow.brief_api.FIELDS, "unknown_fields"}
    assert body["name"] == "Calcolo mancia"
    assert body["goals"] == ["Split the bill"]
    assert body["problem"] is None
    assert body["unknown_fields"] == ["budget"]
    assert ignored == ["audience", "colour"]
    assert push_flow.brief_view(content)["unknown_fields"] == ["budget", "goals", "nothing"]


def test_the_specification_of_the_folder_becomes_the_request_of_the_studio() -> None:
    reference = {"kind": "PROJECT_BRIEF", "artifact_id": "a", "version_number": 1}
    specification = {
        "schema_version": 2,
        "project_id": ARCHIVE_PROJECT_ID,
        "context": {
            "project_brief": reference,
            "agent_team": {**reference, "kind": "AGENT_TEAM"},
            "user_modeling": {**reference, "kind": "USER_MODELING"},
            "catalog": {"version": 3, "content_hash": "c" * 64},
        },
        "requirements": [{"code": "REQ-001"}],
    }

    body = push_flow.api_specification(specification)

    assert body == {
        "schema_version": 2,
        "project_id": ARCHIVE_PROJECT_ID,
        "requirements": [{"code": "REQ-001"}],
        "project_brief_reference": reference,
        "agent_team_reference": {**reference, "kind": "AGENT_TEAM"},
        "user_modeling_reference": {**reference, "kind": "USER_MODELING"},
        "catalog_version": 3,
        "catalog_content_hash": "c" * 64,
    }
    assert push_flow.api_specification({"requirements": []}) == {"requirements": []}


def test_the_design_keeps_the_grounding_of_the_studio() -> None:
    package = {"grounding": {"old": True}, "alternatives": [1]}

    assert push_flow.grounded(package, {"package": {"grounding": {"new": True}}}) == {
        "grounding": {"new": True},
        "alternatives": [1],
    }
    assert push_flow.grounded(package, {"package": {}}) == package


def test_a_twin_change_gives_replacements_and_the_fields_left_out(tmp_path: Path) -> None:
    context = context_of(tmp_path)
    before = {"twin_versions": [twin("Mario", ["Pay"])], "persona_versions": []}
    extra = observation("persona.goals", ["Unknown"])
    edited = twin("Mario Rossi", ["Pay", "Split"], [extra])
    after = {"twin_versions": [edited], "persona_versions": [{"x": 1}]}

    changes = push_flow.twin_changes(context, after, before)
    added = push_flow.twin_changes(context, after, None)
    goals = edited["profile"]["observations"][0]
    expected = {"field": "goals", **{key: goals[key] for key in modeling_api.REPLACEMENT_KEYS}}

    assert [(item.twin_id, item.name, item.ignored) for item in changes] == [
        (TWIN_ID, "Mario", ("Name", "Goals")),
        ("", "User Twin", ("Persona versions",)),
    ]
    assert changes[0].replacements == (expected,)
    assert [(item.name, item.added) for item in added] == [("Mario Rossi", True)]
    assert push_flow.owner_profiles(after) == [
        {"persona_id": PERSONA_ID, "name": "Mario Rossi", "observations": [expected]}
    ]


def test_the_members_of_the_team_are_ordered_like_the_catalog() -> None:
    content = {
        "members": [
            {"agent_id": "UX_UI_DESIGNER"},
            {"agent_id": "WORKFLOW_ORCHESTRATOR"},
            {"name": "no agent"},
            "noise",
        ]
    }

    assert push_flow.member_agents(content) == ["WORKFLOW_ORCHESTRATOR", "UX_UI_DESIGNER"]
    assert push_flow.member_agents({"members": "none"}) == []


def test_a_document_that_is_not_json_or_lacks_its_key_is_refused() -> None:
    for text in (None, "{not json", '{"specification": []}', "[]"):
        with pytest.raises(CliError) as caught:
            push_flow.content_of("requirements", REQUIREMENTS, text)
        assert caught.value.code == "PUSH_DOCUMENT_INVALID"
        assert caught.value.status == 2
        assert dict(caught.value.values) == {"path": REQUIREMENTS, "key": "specification"}
    assert push_flow.content_of("team", "team/team.json", '{"proposal": {"a": 1}}') == {"a": 1}


def test_an_unreadable_step_document_stops_the_push_before_any_request(tmp_path: Path) -> None:
    archive = valid_archive()
    folder = linked(tmp_path, archive)
    (folder / "requirements" / "requirements.json").write_bytes(b"{not json\n")
    transport = ScriptedTransport()
    transport.expect(
        "GET", f"{BASE}/knowledge-packages?limit=1", body={"versions": [{"version_number": 1}]}
    )
    archive_reply(transport, 1, archive)

    run = run_ut(["push"], tmp_path, transport=transport, variables=WIDE)

    assert run.status == 2
    assert run.errors == (
        f"The document {REQUIREMENTS} cannot be read as a step document: it must be valid JSON "
        'and hold "specification". Fix it, or download it again with `ut package pull`.\n'
    )
    transport.assert_done()


def test_a_definition_missing_in_the_studio_goes_through_the_owner_route(tmp_path: Path) -> None:
    first = partial_archive(through="twins")
    second = valid_archive(version_number=2)
    folder = linked(tmp_path, first)
    target = folder / "requirements" / "requirements.json"
    target.parent.mkdir()
    target.write_bytes(valid_files()[REQUIREMENTS].encode("utf-8"))
    version = {"id": VERSION_ID, "version_number": 1, "content_hash": "d" * 64}
    transport = ScriptedTransport()
    transport.expect(
        "GET", f"{BASE}/knowledge-packages?limit=1", body={"versions": [{"version_number": 1}]}
    )
    archive_reply(transport, 1, first)
    transport.expect(
        "GET",
        f"{BASE}/requirements/current",
        status=404,
        body={"detail": {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"}},
    )
    transport.expect(
        "POST",
        f"{BASE}/requirements/owner-specifications",
        status=201,
        body={"status": "CREATED", "version": version},
    )
    transport.expect(
        "POST",
        f"{BASE}/requirements/gate/submit",
        body={"status": "SUBMITTED", "gate": {"status": "PENDING_APPROVAL"}},
    )
    transport.expect(
        "POST",
        f"{BASE}/requirements/gate/decision",
        body={"status": "APPLIED", "gate": {"status": "APPROVED"}},
    )
    transport.expect("POST", f"{BASE}/sections/alignment", status=404, body={"detail": "Not Found"})
    transport.expect("GET", f"{BASE}/alignment", status=404, body={"detail": "Not Found"})
    transport.expect(
        "POST",
        f"{BASE}/knowledge-packages",
        status=201,
        body={"reused": False, "version": {"version_number": 2}},
    )
    archive_reply(transport, 2, second)

    run = run_ut(["push"], tmp_path, transport=transport, answers=["", "y"], variables=WIDE)

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert lines[1] == (
        f'  {REQUIREMENTS} (added): document of the "Definition" step, its changes can be sent.'
    )
    assert "    + context" in lines
    assert (
        'Step "Definition" approved (version 1). Saved in .orchestwin/steps/requirements.json.'
        in lines
    )
    assert lines[-1] == f"Sent: Definition. Folder at version 2 ({len(valid_files())} files)."
    body = transport.requests("POST", f"{BASE}/requirements/owner-specifications")[0].json()
    specification = json.loads(valid_files()[REQUIREMENTS])["specification"]
    assert body == {"specification": push_flow.api_specification(specification)}
    assert "context" not in body["specification"]
    assert knowledge.verify(folder).package_version == 2
    transport.assert_done()


def missing_step(tmp_path: Path, through: str, path: str) -> tuple[Path, ScriptedTransport]:
    first = partial_archive(through=through)
    folder = linked(tmp_path, first)
    target = folder.joinpath(*path.split("/"))
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(valid_files()[path].encode("utf-8"))
    transport = ScriptedTransport()
    transport.expect(
        "GET", f"{BASE}/knowledge-packages?limit=1", body={"versions": [{"version_number": 1}]}
    )
    archive_reply(transport, 1, first)
    return folder, transport


def published_again(transport: ScriptedTransport, through: str) -> None:
    transport.expect("POST", f"{BASE}/sections/alignment", status=404, body={"detail": "Not Found"})
    transport.expect(
        "POST",
        f"{BASE}/knowledge-packages",
        status=201,
        body={"reused": False, "version": {"version_number": 2}},
    )
    archive_reply(transport, 2, partial_archive(through=through, version_number=2))


def test_a_team_missing_in_the_studio_goes_through_the_owner_route(tmp_path: Path) -> None:
    folder, transport = missing_step(tmp_path, "brief", "team/team.json")
    members = json.loads(valid_files()["team/team.json"])["proposal"]["members"]
    selected = team_api.ordered(str(member["agent_id"]) for member in members)
    version = {"id": VERSION_ID, "version_number": 1, "selected_agent_ids": selected}
    transport.expect(
        "GET", f"{BASE}/team-proposals/current", status=404, body={"detail": "not_found"}
    )
    transport.expect(
        "POST",
        f"{BASE}/team/owner-proposals",
        status=201,
        body={"status": "CREATED", "version": version, "issues": []},
    )
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/submit",
        status=201,
        body={"status": "SUBMITTED", "gate": {"status": "PENDING_APPROVAL"}},
    )
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/decisions",
        body={"status": "APPLIED", "gate": {"status": "APPROVED"}},
    )
    published_again(transport, "team")

    run = run_ut(["push"], tmp_path, transport=transport, answers=["", "y"], variables=WIDE)

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert (
        'Step "Perspectives" approved (version 1). Saved in .orchestwin/steps/team.json.' in lines
    )
    assert lines[-1].startswith("Sent: Perspectives. Folder at version 2 ")
    body = transport.requests("POST", f"{BASE}/team/owner-proposals")[0].json()
    assert body == {"selected_agent_ids": selected}
    assert knowledge.verify(folder).package_version == 2
    transport.assert_done()


def test_twins_missing_in_the_studio_go_through_the_owner_route(tmp_path: Path) -> None:
    folder, transport = missing_step(tmp_path, "team", "twins/twins.json")
    snapshot = json.loads(valid_files()["twins/twins.json"])
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/snapshots/current",
        status=404,
        body={"detail": {"code": "USER_MODELING_SNAPSHOT_NOT_FOUND"}},
    )
    transport.expect(
        "POST",
        f"{BASE}/user-modeling/owner-profiles",
        status=201,
        body={"status": "CREATED", "snapshot_version": snapshot, "twin_versions": []},
    )
    transport.expect(
        "POST",
        f"{BASE}/user-modeling/gate/submit",
        body={"outcome": "APPLIED", "gate": {"status": "PENDING_APPROVAL"}},
    )
    transport.expect(
        "POST",
        f"{BASE}/user-modeling/gate/decision",
        body={"outcome": "APPLIED", "gate": {"status": "APPROVED"}},
    )
    published_again(transport, "twins")

    run = run_ut(["push"], tmp_path, transport=transport, answers=["", "y"], variables=WIDE)

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[-1].startswith("Sent: User Twin. Folder at version 2 ")
    body = transport.requests("POST", f"{BASE}/user-modeling/owner-profiles")[0].json()
    assert body == {"profiles": push_flow.owner_profiles(snapshot["snapshot"])}
    assert [len(profile["observations"]) for profile in body["profiles"]] == [
        sum(
            1
            for item in twin["profile"]["observations"]
            if item["observation_key"].startswith("user_twin.")
        )
        for twin in snapshot["snapshot"]["twin_versions"]
    ]
    assert all(profile["persona_id"] for profile in body["profiles"])
    assert knowledge.verify(folder).package_version == 2
    transport.assert_done()


def test_without_a_folder_or_a_publication_the_push_explains_what_to_do(tmp_path: Path) -> None:
    link_folder(tmp_path / "project", project_id=ARCHIVE_PROJECT_ID)
    store_session(tmp_path)
    missing = run_ut(["push"], tmp_path, transport=NoNetwork())
    knowledge.unpack(valid_archive(), tmp_path / "project" / "orchestwin")
    transport = ScriptedTransport()
    transport.expect("GET", f"{BASE}/knowledge-packages?limit=1", body={"versions": []})
    unpublished = run_ut(["--lang", "it", "push"], tmp_path, transport=transport)

    assert missing.status == 1
    assert missing.errors == (
        "The project has no knowledge folder orchestwin/: download it with `ut package pull`, "
        "change it and launch `ut push` again.\n"
    )
    assert unpublished.status == 1
    assert unpublished.errors.startswith(
        "Lo Studio non ha ancora pubblicato una cartella di conoscenza per questo progetto."
    )
    transport.assert_done()


def test_the_help_names_the_options_and_an_unknown_stage_is_a_usage_error(
    tmp_path: Path,
) -> None:
    shown = run_ut(["push", "--help"], tmp_path, transport=NoNetwork(), variables=WIDE)
    wrong = run_ut(["push", "--stage", "dossier"], tmp_path, transport=NoNetwork())

    assert shown.status == 0
    assert (
        "Send the hand-made changes of the knowledge folder to the Studio as versions supplied "
        "by you" in shown.output
    )
    assert "only show the differences, without sending anything to the Studio" in shown.output
    assert "{brief,team,twins,requirements,design}" in shown.output
    assert wrong.status == 2


def test_the_api_helpers_send_the_paths_and_bodies_of_the_studio(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{BASE}/requirements/revisions", status=201, body={"diff": {"id": DIFF_ID}}
    )
    transport.expect("POST", f"{BASE}/requirements/revisions", status=201, body={"diff": None})
    transport.expect("POST", f"{BASE}/requirements/owner-specifications", status=201, body={})
    transport.expect("POST", f"{BASE}/user-modeling/twins/{TWIN_ID}/revisions", body={})
    transport.expect("POST", f"{BASE}/user-modeling/revisions/{DIFF_ID}/decision", body={})
    transport.expect("POST", f"{BASE}/user-modeling/revisions/{DIFF_ID}/decision", body={})
    transport.expect("POST", f"{BASE}/user-modeling/owner-profiles", status=201, body={})
    transport.expect("POST", f"{BASE}/team/owner-proposals", status=201, body={})
    store_session(tmp_path)
    context = command_context(environment(tmp_path, transport=transport))
    client = context.client()
    replacement = {"field": "goals", "value": {"kind": "ITEMS"}}

    proposed = requirements_api.propose_revision(client, ARCHIVE_PROJECT_ID, {"a": 1})
    with pytest.raises(ApiFailure):
        requirements_api.propose_revision(client, ARCHIVE_PROJECT_ID, {"a": 2})
    owned = requirements_api.owner_specification(client, ARCHIVE_PROJECT_ID, {"a": 3})
    twin_proposal = modeling_api.propose_revision(
        client, ARCHIVE_PROJECT_ID, TWIN_ID, [replacement]
    )
    approved = modeling_api.decide_revision(
        client, ARCHIVE_PROJECT_ID, DIFF_ID, modeling_api.APPROVE
    )
    rejected = modeling_api.decide_revision(
        client, ARCHIVE_PROJECT_ID, DIFF_ID, modeling_api.REJECT, "No"
    )
    profiles = modeling_api.owner_profiles(client, ARCHIVE_PROJECT_ID, [{"name": "Mario"}])
    team = team_api.owner_proposal(
        client, ARCHIVE_PROJECT_ID, ["UX_UI_DESIGNER", "WORKFLOW_ORCHESTRATOR"]
    )

    assert proposed == {"diff": {"id": DIFF_ID}}
    assert [owned[0], twin_proposal[0], approved[0], rejected[0], profiles[0], team[0]] == [
        201,
        200,
        200,
        200,
        201,
        201,
    ]
    assert [request.json() for request in transport.sent] == [
        {"specification": {"a": 1}},
        {"specification": {"a": 2}},
        {"specification": {"a": 3}},
        {"replacements": [replacement]},
        {"decision": "APPROVE"},
        {"decision": "REJECT", "reason": "No"},
        {"profiles": [{"name": "Mario"}]},
        {"selected_agent_ids": ["WORKFLOW_ORCHESTRATOR", "UX_UI_DESIGNER"]},
    ]
    transport.assert_done()


def test_the_signs_and_the_labels_of_a_design_diff(tmp_path: Path) -> None:
    context = context_of(tmp_path)
    diff = {
        "changes": [
            {"kind": "ADD", "artifact_kind": "OWNER_ASSERTION", "after": {"text": "Large  keys"}},
            {"kind": "REMOVE", "artifact_kind": "ALTERNATIVE", "before": {"code": "DES-003"}},
            {"kind": "REPLACE", "artifact_kind": "PROTOTYPE", "after": {"id": "x"}},
            {"kind": "REPLACE", "artifact_kind": "SOMETHING_NEW"},
            "noise",
        ]
    }

    push_flow.show_design_diff(context, diff)

    assert context.environment.stdout.getvalue().splitlines() == [
        "The proposed change. Changes: 4.",
        "    + owner_assertions Large keys",
        "    - alternatives DES-003",
        "    ~ prototype",
        "    ~ package",
    ]


def test_a_refusal_of_the_studio_keeps_its_code_and_a_pending_one_names_the_step() -> None:
    refused = push_flow.refusal(409, {"detail": {"code": "INVALID_PROPOSAL"}})
    stale = push_flow.refusal(409, {"status": "PROPOSAL_STALE"})
    unknown = push_flow.refusal(500, "broken")
    pending = push_flow.pending_or(
        ApiFailure("DIFF_ALREADY_PENDING", http_status=409), "Definition"
    )
    other = push_flow.pending_or(refused, "Definition")

    assert (refused.code, refused.http_status) == ("INVALID_PROPOSAL", 409)
    assert stale.code == "PROPOSAL_STALE"
    assert unknown.code == "API_FAILURE"
    assert (pending.code, dict(pending.values), pending.status) == (
        "PUSH_REVISION_PENDING",
        {"stage": "Definition"},
        1,
    )
    assert other is refused
