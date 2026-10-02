from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.mcp import knowledge

from .support.fake_studio import FakeStudio, _fake_requirements
from .support.terminal import run_ut
from .support.transports import NoNetwork
from .test_api_design import design_session
from .test_definition_command import Offline, definition_version
from .test_mcp_protocol import call, initialize


@pytest.mark.parametrize("language", ["it", "en"])
def test_request_journeys_yes_applies_approves_and_downloads_current_definition(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, through="requirements", language=language) as session:
        before = copy.deepcopy(session.project.current("requirements"))

        run = session.ut("definition", "journeys", "--yes", language=language)

        assert run.status == 0, run.output + run.errors
        current = session.project.current("requirements")
        assert current["version_number"] == before["version_number"] + 1
        assert current["specification"]["journeys"]
        for key, value in before["specification"].items():
            assert current["specification"][key] == value
        changes = session.requests("POST", "/requirements/change-requests")
        assert len(changes) == 1
        assert json.loads(changes[0].body)["include_journeys"] is True
        assert session.count("POST", "/requirements/gate/submit") == 1
        assert session.count("POST", "/requirements/gate/decision") == 1
        assert session.project.approved("requirements")
        saved = json.loads(
            (session.folder / "orchestwin/requirements/requirements.json").read_text(
                encoding="utf-8"
            )
        )
        assert saved["content_hash"] == current["content_hash"]
        assert saved["version_number"] == current["version_number"]
        assert saved["specification"]["journeys"] == current["specification"]["journeys"]
        assert (session.folder / "orchestwin/requirements/tables/journeys.csv").is_file()
        assert "definition." not in run.output
        assert "init.artifact_journey" not in run.output


def test_request_journeys_rejection_keeps_version_and_does_not_publish(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        before = copy.deepcopy(session.project.current("requirements"))

        run = session.ut("definition", "journeys", answers=["n"])

        assert run.status == 0, run.output + run.errors
        assert session.project.current("requirements") == before
        assert session.project.requirement_diffs[0]["status"] == "REJECTED"
        assert session.count("POST", "/requirements/gate/submit") == 0
        assert not (session.folder / "orchestwin").exists()


def test_request_journeys_uses_one_owner_confirmation(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        run = session.ut("definition", "journeys", answers=["y"])

        assert run.status == 0, run.output + run.errors
        assert session.project.approved("requirements")
        assert session.project.current("requirements")["specification"]["journeys"]


def test_journey_flags_cannot_be_used_as_read_only_options(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        for option in ("--all", "--json"):
            run = session.ut("definition", "journeys", option)
            assert run.status == 2
            assert "Use `ut definition journeys`" in run.errors
        assert session.count("POST", "/requirements/change-requests") == 0


def test_journey_change_body_omits_the_false_flag() -> None:
    assert requirements_api.change_body("Change") == {"request": "Change"}
    assert requirements_api.change_body("Journeys", include_journeys=True) == {
        "request": "Journeys",
        "include_journeys": True,
    }


@pytest.mark.parametrize("value", ["true", 1, None])
def test_fake_journey_request_requires_a_strict_boolean(tmp_path: Path, value: object) -> None:
    with design_session(tmp_path, through="requirements") as session:
        reply = session.client().request(
            "POST",
            requirements_api.change_path(session.project.id),
            body={"request": "Journeys", "include_journeys": value},
        )
        assert reply.status == 422
        assert session.project.requirement_diffs == []


def test_journey_publication_failure_is_reported_after_approval(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=503,
            body={"detail": {"code": "PUBLICATION_FAILED"}},
        )
        run = session.ut("definition", "journeys", "--yes")
        assert run.status == 1
        assert "PUBLICATION_FAILED" in run.errors
        assert session.project.approved("requirements")
        assert not (session.folder / "orchestwin").exists()


@pytest.mark.parametrize("language", ["it", "en"])
def test_journey_help_and_detailed_read_keep_phases_out_of_the_summary(
    tmp_path: Path, language: str
) -> None:
    help_run = run_ut(
        ["--lang", language, "definition", "journeys", "--help"], tmp_path, transport=NoNetwork()
    )
    assert help_run.status == 0
    assert "definition.option_" not in help_run.output
    assert "--yes" in help_run.output
    with design_session(tmp_path, through="requirements", language=language) as session:
        assert session.ut("--yes", "definition", "journeys", language=language).status == 0
        writes = len(session.writes())
        brief = session.ut("definition", language=language)
        details = session.ut("definition", "--all", language=language)
        online = session.ut("definition", "--json", language=language)
        offline = run_ut(
            ["--lang", language, "definition", "--json"], tmp_path, transport=Offline()
        )
        current = session.project.current("requirements")
        assert len(session.writes()) == writes
        scenario_label = "Scenari" if language == "it" else "Scenarios"
        need_label = "Bisogni" if language == "it" else "Needs"
        assert (
            brief.output.index(scenario_label + " (")
            < brief.output.index(need_label + " (")
            < brief.output.index("Journey (")
        )
        assert json.loads(online.output) == current["specification"]
        assert (
            json.loads(offline.output) == _fake_requirements(current["specification"]).to_snapshot()
        )
        for journey in current["specification"]["journeys"]:
            assert journey["title"] in brief.output
            assert journey["code"] in details.output
            for phase in journey["phases"]:
                assert phase["title"] not in brief.output
                assert phase["title"] in details.output
                assert phase["action"] in details.output
        assert "source_id=" in details.output


def test_journey_request_respects_pending_and_unchanged_revisions(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        session.project.requirement_diffs.append(
            {"status": "PROPOSED", "base_version_id": session.project.current("requirements")["id"]}
        )
        pending = session.ut("definition", "journeys", "--yes")
        assert pending.status == 1
        assert "pending Definition revision" in pending.errors
        assert session.count("POST", "/requirements/change-requests") == 0
        session.project.requirement_diffs.clear()
        assert session.ut("definition", "journeys", "--yes").status == 0
        current = copy.deepcopy(session.project.current("requirements"))
        same = session.ut("definition", "journeys", "--yes")
        assert same.status == 0, same.output + same.errors
        assert session.project.current("requirements") == current
        assert session.count("POST", "/requirements/gate/decision") == 1


@pytest.mark.parametrize("schema_version", [1, 2])
def test_fake_journey_proposals_preserve_identity_diff_sources_and_canonical_empty_hash(
    schema_version: int,
) -> None:
    before = definition_version(schema_version)["specification"]
    studio = FakeStudio(language="en")
    proposed = studio._with_journeys(before)
    domain = _fake_requirements(proposed)
    assert domain.schema_version == 2
    assert domain.journeys
    assert studio._with_journeys(proposed) == proposed
    ordinary, _ = studio._with_requirement(proposed, "Show history")
    assert ordinary["journeys"] == proposed["journeys"]
    if schema_version == 2:
        assert {key: value for key, value in proposed.items() if key != "journeys"} == before
        assert (
            _fake_requirements({**before, "journeys": []}).content_hash
            == _fake_requirements(before).content_hash
        )
    else:
        assert "needs" not in before
    for group in (
        "requirements",
        "user_stories",
        "scenarios",
        "acceptance_criteria",
        "risks",
        "definition_of_done",
    ):
        assert [(item["id"], item["code"]) for item in before[group]] == [
            (item["id"], item["code"]) for item in proposed[group]
        ][: len(before[group])]
    scenarios = {item["id"]: item for item in proposed["scenarios"]}
    for journey in proposed["journeys"]:
        assert journey["sources"] == scenarios[journey["scenario_id"]]["sources"]
        assert [phase["action"] for phase in journey["phases"]] == scenarios[
            journey["scenario_id"]
        ]["steps"]
        assert all(phase["touchpoint"] is None for phase in journey["phases"])


def test_fake_journey_diff_and_realign_preserve_all_journey_content(tmp_path: Path) -> None:
    with design_session(tmp_path, through="requirements") as session:
        assert session.ut("definition", "journeys", "--yes").status == 0
        current = copy.deepcopy(session.project.current("requirements"))
        diff = session.project.requirement_diffs[0]
        assert {operation["artifact_kind"] for operation in diff["operations"]} == {"JOURNEY"}
        assert all(operation["after"]["journey"]["phases"] for operation in diff["operations"])
        session.project.seed_brief_change()
        session.studio._realign_team(session.project, session.project.account)
        session.studio._seed_approval(session.project, "team")
        session.studio._realign_twins(session.project, session.project.account)
        session.studio._seed_approval(session.project, "twins")
        after = session.studio._realign_requirements(session.project, session.project.account)
        assert after["specification"]["journeys"] == current["specification"]["journeys"]
        assert after["content_hash"] == _fake_requirements(after["specification"]).content_hash


def test_mcp_journeys_preserve_sources_phases_and_use_codes() -> None:
    current = definition_version()
    current["specification"] = FakeStudio()._with_journeys(current["specification"])
    view = knowledge.requirements_view(current)
    ids = {
        item["id"]: item["code"]
        for group in ("needs", "scenarios")
        for item in current["specification"][group]
    }
    for raw, item in zip(current["specification"]["journeys"], view["journeys"], strict=True):
        assert item["sources"] == raw["sources"]
        assert item["scenario_code"] == ids[raw["scenario_id"]]
        for phase, projected in zip(raw["phases"], item["phases"], strict=True):
            assert projected == {
                **{key: phase[key] for key in ("title", "action", "touchpoint", "criticalities")},
                "need_codes": [ids[identifier] for identifier in phase["need_ids"]],
            }
    assert "journeys" not in knowledge.requirements_view(definition_version())
    assert "journeys" not in knowledge.requirements_view(definition_version(1))


def test_mcp_serves_selected_journeys_from_the_published_folder_without_network(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, through="requirements") as session:
        assert session.ut("definition", "journeys", "--yes").status == 0
        before = len(session.studio.requests)
        run = run_ut(
            ["mcp"],
            tmp_path,
            transport=NoNetwork(),
            answers=[initialize(), call(2, "get_requirements", {"codes": ["jrn-001", "JRN-999"]})],
        )
        assert run.status == 0, run.output + run.errors
        replies = [json.loads(line) for line in run.output.splitlines()]
        result = replies[1]["result"]
        assert result["isError"] is False
        document = result["structuredContent"]
        assert document["unknown_codes"] == ["JRN-999"]
        assert document["journeys"][0]["code"] == "JRN-001"
        assert document["journeys"][0]["phases"][0]["need_codes"]
        assert document["actors"]
        assert len(session.studio.requests) == before


@pytest.mark.parametrize("code", ["JRN-001", "SCN-001", "NED-001"])
def test_mcp_journey_closure_stays_within_the_selected_chain(code: str) -> None:
    view = {
        "version_number": 2,
        "schema_version": 2,
        "journeys": [],
        "scenarios": [],
        "needs": [],
        "requirements": [],
        "user_stories": [],
        "acceptance_criteria": [],
    }
    for number in (1, 2):
        suffix = f"{number:03d}"
        view["journeys"].append(
            {
                "code": f"JRN-{suffix}",
                "scenario_code": f"SCN-{suffix}",
                "need_codes": [f"NED-{suffix}"],
                "phases": [{"need_codes": [f"NED-{suffix}"]}],
            }
        )
        view["scenarios"].append(
            {"code": f"SCN-{suffix}", "actor": {"twin_id": suffix, "name": f"Actor {number}"}}
        )
        view["needs"].append({"code": f"NED-{suffix}", "scenario_codes": [f"SCN-{suffix}"]})
        view["requirements"].append({"code": f"REQ-{suffix}", "need_codes": [f"NED-{suffix}"]})
        view["user_stories"].append(
            {"code": f"USR-{suffix}", "requirement_codes": [f"REQ-{suffix}"]}
        )
        view["acceptance_criteria"].append(
            {"code": f"AC-{suffix}", "requirement_codes": [f"REQ-{suffix}"]}
        )
    selected, unknown = knowledge.select_codes(view, [code.lower(), "JRN-999"])
    assert unknown == ["JRN-999"]
    for group in (
        "journeys",
        "scenarios",
        "needs",
        "requirements",
        "user_stories",
        "acceptance_criteria",
    ):
        assert selected[group]
        assert all(item["code"].endswith("001") for item in selected[group])
    assert selected["actors"] == [{"twin_id": "001", "name": "Actor 1"}]
