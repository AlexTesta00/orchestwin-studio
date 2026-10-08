from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.console import Console
from orchestwin.cli.flows import init_requirements
from orchestwin.cli.http import Reply, unreachable
from orchestwin.cli.mcp import knowledge
from orchestwin.knowledge.archive import read_verified_folder

from .support.fake_studio import FakeStudio, _fake_requirements
from .support.terminal import PROJECT_ID, START, link_folder, run_ut, store_session, terminal
from .support.transports import API, NoNetwork, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}/requirements/current"
PASSWORD = "Test-password-not-real!"


def definition_version(schema_version: int = 2) -> dict[str, object]:
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", PASSWORD)
    project = studio.seed_project(
        owner="owner@example.com",
        name="Tip calculator",
        through="requirements",
        requirements_schema_version=schema_version,
    )
    return project.current("requirements")


class Offline:
    def send(self, method: str, url: str, **options: object) -> Reply:
        raise unreachable(url, sent=False)


def accounts_only() -> ScriptedTransport:
    return ScriptedTransport().expect(
        "GET", f"{API}/auth/mode", body={"access_mode": "ACCOUNTS", "registration_open": True}
    )


@pytest.mark.parametrize("language", ["it", "en"])
def test_definition_defaults_to_titles_in_chain_order_without_details(
    tmp_path: Path, language: str
) -> None:
    link_folder(tmp_path)
    store_session(tmp_path)
    version = definition_version()
    transport = ScriptedTransport().expect("GET", BASE, body=version)

    run = run_ut(["--lang", language, "definition"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    labels = (
        ["Scenari (2)", "Bisogni (2)", "Storie (2)", "Requisiti funzionali (3)"]
        if language == "it"
        else ["Scenarios (2)", "Needs (2)", "User stories (2)", "Functional requirements (3)"]
    )
    assert [run.output.index(label) for label in labels] == sorted(
        run.output.index(label) for label in labels
    )
    assert "REQ-001" not in run.output
    assert version["specification"]["requirements"][0]["statement"] not in run.output
    assert (
        "still needs to be checked with real users" in run.output
        if language == "en"
        else "resta da verificare con utenti reali" in run.output
    )
    transport.assert_done()


def test_definition_all_includes_actors_links_sources_and_every_group(tmp_path: Path) -> None:
    link_folder(tmp_path)
    store_session(tmp_path)
    version = definition_version()
    transport = ScriptedTransport().expect("GET", BASE, body=version)

    run = run_ut(["definition", "--all"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    specification = version["specification"]
    for scenario in specification["scenarios"]:
        for key in ("context", "goal", "trigger", "expected_outcome"):
            assert scenario[key] in run.output
        assert scenario["actor"]["name"] in run.output
    for group in ("requirements", "needs", "acceptance_criteria", "risks", "definition_of_done"):
        assert specification[group][0]["code"] in run.output
    assert "source_id=" in run.output
    assert "content_hash=" in run.output
    assert "Likelihood: POSSIBLE" in run.output
    assert "Mitigation:" in run.output
    assert "Applicability: REQUIRED" in run.output
    transport.assert_done()


@pytest.mark.parametrize("schema_version", [1, 2])
def test_definition_json_is_lossless_for_both_schemas(tmp_path: Path, schema_version: int) -> None:
    link_folder(tmp_path)
    store_session(tmp_path)
    version = definition_version(schema_version)
    version["specification"]["extra_future_field"] = {"preserve": [1, "è", None]}
    transport = ScriptedTransport().expect("GET", BASE, body=version)

    run = run_ut(["definition", "--all", "--json"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert json.loads(run.output) == version["specification"]
    assert run.errors == ""
    transport.assert_done()


@pytest.mark.parametrize("source", ["folder", "step"])
@pytest.mark.parametrize("signed_in", [False, True])
def test_definition_offline_uses_the_local_document_without_writing(
    tmp_path: Path, source: str, signed_in: bool
) -> None:
    project = link_folder(tmp_path)
    version = definition_version()
    if signed_in:
        store_session(tmp_path)
    if source == "folder":
        target = project.knowledge / "requirements" / "requirements.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(version), encoding="utf-8")
    else:
        target = project.save_step("requirements", version=version, gate={}, saved_at=START)
    before = target.read_bytes()

    run = run_ut(
        ["definition", "--json"], tmp_path, transport=Offline() if signed_in else accounts_only()
    )

    assert run.status == 0, run.errors
    assert json.loads(run.output) == version["specification"]
    assert "Reading the local Definition" in run.errors
    assert target.read_bytes() == before


def test_definition_missing_and_server_errors_do_not_use_stale_local_data(tmp_path: Path) -> None:
    project = link_folder(tmp_path)
    store_session(tmp_path)
    project.save_step("requirements", version=definition_version(), gate={}, saved_at=START)
    transport = ScriptedTransport().expect(
        "GET", BASE, status=404, body={"detail": {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"}}
    )

    run = run_ut(["definition"], tmp_path, transport=transport)

    assert run.status != 0
    assert "not available yet" in run.errors
    assert run.output == ""
    transport.assert_done()


def test_legacy_definition_declares_absent_needs_without_fabricating_fields(tmp_path: Path) -> None:
    project = link_folder(tmp_path)
    version = definition_version(1)
    project.save_step("requirements", version=version, gate={}, saved_at=START)

    run = run_ut(["definition", "--all"], tmp_path, transport=accounts_only())

    assert run.status == 0, run.errors
    assert "contains no needs" in run.output
    assert "Needs (0)" in run.output
    assert "Context:" not in run.output
    assert "Potential difficulties:" not in run.output
    assert "NED-" not in run.output


@pytest.mark.parametrize("schema_version", [1, 2])
def test_fake_definition_hash_and_published_version_follow_current_schema(
    tmp_path: Path, schema_version: int
) -> None:
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", PASSWORD)
    project = studio.seed_project(
        owner="owner@example.com",
        name="Tip calculator",
        through="design",
        requirements_schema_version=schema_version,
    )
    version = project.current("requirements")
    specification = _fake_requirements(version["specification"])

    folder = studio._knowledge_folder(
        project, ("brief", "team", "twins", "requirements", "design"), 1, START
    )
    from orchestwin.knowledge.folder import folder_archive

    verified = read_verified_folder(folder_archive(folder).content)
    document = verified.documents["requirements"]
    assert document["version_number"] == version["version_number"]
    assert document["content_hash"] == version["content_hash"] == specification.content_hash
    assert document["specification"] == specification.to_snapshot()
    assert document["specification"]["schema_version"] == schema_version
    assert ("needs" in document["specification"]) is (schema_version == 2)


def test_need_diff_envelope_and_selection_preserve_typed_need() -> None:
    need = definition_version()["specification"]["needs"][0]

    assert "NEED" in requirements_api.ARTIFACT_KINDS
    assert requirements_api.artifact({"kind": "NEED", "need": need}) == need
    assert requirements_api.artifact({"kind": "NEED", "scenario": need}) is None


@pytest.mark.parametrize(("language", "label"), [("en", "the need"), ("it", "il bisogno")])
def test_the_shared_init_and_alignment_diff_names_a_typed_need(
    tmp_path: Path, language: str, label: str
) -> None:
    need = definition_version()["specification"]["needs"][0]
    bundle = terminal(tmp_path, transport=NoNetwork())
    console = Console(bundle.environment, language=language, color=False)
    journey = SimpleNamespace(console=console, text=console.text, say=console.say)
    diff = {
        "operations": [
            {
                "artifact_kind": "NEED",
                "operation": "ADD",
                "display_code": need["code"],
                "after": {"kind": "NEED", "need": need},
            }
        ]
    }

    init_requirements.show_diff(journey, diff)

    assert label in bundle.output
    assert need["code"] in bundle.output
    assert need["statement"] in bundle.output


def test_mcp_definition_preserves_real_links_and_legacy_absence() -> None:
    version = definition_version()
    view = knowledge.requirements_view(version)
    specification = version["specification"]

    assert view["schema_version"] == 2
    assert view["needs"][0]["sources"] == specification["needs"][0]["sources"]
    assert view["needs"][0]["scenario_codes"] == ["SCN-001"]
    assert view["requirements"][0]["need_codes"] == ["NED-001", "NED-002"]
    assert view["scenarios"][0]["actor"] == specification["scenarios"][0]["actor"]
    assert len(view["actors"]) == 2
    legacy = knowledge.requirements_view(definition_version(1))
    assert legacy["needs"] == []
    assert "need_codes" not in legacy["requirements"][0]
    assert "sources" not in legacy["scenarios"][0]
    assert "context" not in legacy["scenarios"][0]


@pytest.mark.parametrize("code", ["REQ-001", "USR-001", "AC-001", "NED-001", "SCN-001"])
def test_mcp_selection_closes_dependencies_without_selecting_an_unrelated_chain(code: str) -> None:
    view = {
        "version_number": 4,
        "schema_version": 2,
        "requirements": [],
        "user_stories": [],
        "acceptance_criteria": [],
        "needs": [],
        "scenarios": [],
    }
    for number in (1, 2):
        suffix = f"{number:03d}"
        actor = {"twin_id": suffix, "name": f"Actor {number}"}
        view["scenarios"].append({"code": f"SCN-{suffix}", "actor": actor})
        view["needs"].append(
            {
                "code": f"NED-{suffix}",
                "scenario_codes": [f"SCN-{suffix}"],
                "sources": [{"source_id": suffix}],
            }
        )
        view["requirements"].append({"code": f"REQ-{suffix}", "need_codes": [f"NED-{suffix}"]})
        view["user_stories"].append(
            {
                "code": f"USR-{suffix}",
                "requirement_codes": [f"REQ-{suffix}"],
                "need_codes": [f"NED-{suffix}"],
                "user_twin_reference": actor,
            }
        )
        view["acceptance_criteria"].append(
            {"code": f"AC-{suffix}", "requirement_codes": [f"REQ-{suffix}"]}
        )
    before = copy.deepcopy(view)

    selected, unknown = knowledge.select_codes(view, [code.lower(), "UNKNOWN", "unknown"])

    assert unknown == ["UNKNOWN"]
    assert all(
        item["code"].endswith("001")
        for group in ("requirements", "user_stories", "acceptance_criteria", "needs", "scenarios")
        for item in selected[group]
    )
    assert selected["requirements"][0]["code"] == "REQ-001"
    assert selected["needs"][0]["code"] == "NED-001"
    assert selected["scenarios"][0]["code"] == "SCN-001"
    assert selected["actors"] == [{"twin_id": "001", "name": "Actor 1"}]
    if code.startswith(("NED", "SCN", "REQ")):
        assert selected["acceptance_criteria"][0]["code"] == "AC-001"
    assert view == before


@pytest.mark.parametrize("schema_version", [1, 2])
def test_fake_changes_preserve_surviving_artifacts_and_upgrade_only_explicit_legacy_changes(
    schema_version: int,
) -> None:
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", PASSWORD)
    project = studio.seed_project(
        owner="owner@example.com",
        name="Tip calculator",
        through="requirements",
        requirements_schema_version=schema_version,
    )
    current = project.current("requirements")
    before = copy.deepcopy(current["specification"])

    proposed, added = studio._with_requirement(before, "Show the bill history.")
    domain = _fake_requirements(proposed)

    assert current["specification"] == before
    assert domain.schema_version == 2
    assert added["need_ids"]
    for group in (
        "requirements",
        "user_stories",
        "acceptance_criteria",
        "scenarios",
        "risks",
        "definition_of_done",
    ):
        later = {item["id"]: item for item in proposed[group]}
        for item in before[group]:
            assert item["code"] == later[item["id"]]["code"]
            for key, value in item.items():
                assert later[item["id"]][key] == value
    if schema_version == 2:
        assert proposed["needs"] == before["needs"]
    else:
        assert "needs" not in before
        assert len(proposed["needs"]) == len(before["user_twin_references"])


@pytest.mark.parametrize("schema_version", [1, 2])
def test_realigning_fake_definition_preserves_schema_chain_and_historical_sources(
    schema_version: int,
) -> None:
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", PASSWORD)
    project = studio.seed_project(
        owner="owner@example.com",
        name="Tip calculator",
        through="requirements",
        requirements_schema_version=schema_version,
    )
    before = project.current("requirements")
    content = copy.deepcopy(before["specification"])
    project.seed_brief_change()
    studio._realign_team(project, project.account)
    studio._seed_approval(project, "team")
    studio._realign_twins(project, project.account)
    studio._seed_approval(project, "twins")

    after = studio._realign_requirements(project, project.account)

    assert after["version_number"] == before["version_number"] + 1
    assert after["based_on_version_number"] == before["version_number"]
    assert after["content_hash"] == _fake_requirements(after["specification"]).content_hash
    assert after["specification"]["schema_version"] == schema_version
    if schema_version == 2:
        assert after["specification"]["needs"] == content["needs"]
    else:
        assert "needs" not in after["specification"]
    for old, new in zip(content["scenarios"], after["specification"]["scenarios"], strict=True):
        assert {key: value for key, value in old.items() if key != "actor"} == {
            key: value for key, value in new.items() if key != "actor"
        }
        assert old["actor"]["twin_id"] == new["actor"]["twin_id"]
        assert new["actor"]["version_number"] == old["actor"]["version_number"] + 1


@pytest.mark.parametrize("schema_version", [1, 2])
def test_test_plan_cache_tracks_definition_versions_and_criteria(schema_version: int) -> None:
    from orchestwin.cli.flows import test_plan

    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", PASSWORD)
    project = studio.seed_project(
        owner="owner@example.com",
        name="Tip calculator",
        through="design",
        requirements_schema_version=schema_version,
    )
    run = project.seed_test_run(reviewed=False)
    plan = test_plan.SavedPlan("", {}, project.test_plans()[0])
    current = project.current("requirements")
    criteria = [item["code"] for item in current["specification"]["acceptance_criteria"]]
    reference = (current["version_number"], project.current("design")["version_number"])

    assert test_plan.decide(plan, reference, criteria, new=False).reuse
    assert set(plan.criteria()) == set(criteria)
    assert {item["code"] for item in run["criteria"]} == set(criteria)
    missing = test_plan.decide(plan, reference, [*criteria, "AC-999"], new=False)
    assert not missing.reuse
    assert missing.values["codes"] == "AC-999"
    project.seed_requirements_change()
    changed = (project.current("requirements")["version_number"], reference[1])
    assert not test_plan.decide(plan, changed, criteria, new=False).reuse
