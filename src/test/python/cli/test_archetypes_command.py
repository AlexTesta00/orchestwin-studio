from __future__ import annotations

import copy
import json

import pytest

from orchestwin.cli.views.personas import display_status, view_of

from .support.fake_studio import FakeStudio
from .test_fake_studio import signed_in
from .test_twins_command import seeded, ut

BODY = {
    "name": "Front desk",
    "description": "Checks the guest list.",
    "role": "Receptionist",
    "goals": ["Check reservations"],
    "context": "Hotel reception",
}


def test_fake_crud_preserves_ids_and_history_and_checks_ownership_and_version():
    with FakeStudio(language="en") as studio:
        client = signed_in(studio)
        project = studio.seed_project(owner="owner@example.com", name="Reception", through="team")
        path = f"/projects/{project.id}/user-modeling/archetypes"
        first = client.post(path, BODY)
        assert first.status == 201
        current = first.json()
        persona_id = current["persona_id"]
        assert (
            current["confirmation_status"] == "CONFIRMED" and current["source"] == "OWNER_PROVIDED"
        )
        assert (
            client.send(
                "PATCH", f"{path}/{persona_id}", BODY | {"based_on_version_number": 1}
            ).json()["version_id"]
            == current["version_id"]
        )
        edited = client.send(
            "PATCH",
            f"{path}/{persona_id}",
            BODY | {"description": "Checks late arrivals.", "based_on_version_number": 1},
        )
        assert edited.status == 200 and edited.json()["persona_id"] == persona_id
        assert edited.json()["version_number"] == 2
        assert (
            client.send("DELETE", f"{path}/{persona_id}", {"based_on_version_number": 1}).status
            == 409
        )
        assert client.send("DELETE", f"{path}/{persona_id}", {"based_on_version_number": 2}).json()[
            "archived"
        ]
        assert client.get(path).json() == [] and len(project.personas[persona_id]) == 3
        other = signed_in(studio, "other@example.com")
        assert other.get(path).status == 404
        assert project.personas[persona_id][0]["profile"]["name"] == BODY["name"]


def test_fake_regeneration_matches_persona_and_keeps_old_view_and_hash():
    with FakeStudio(language="en") as studio:
        client = signed_in(studio)
        project = studio.seed_project(owner="owner@example.com", name="Reception", through="twins")
        path = f"/projects/{project.id}/user-modeling"
        before = copy.deepcopy(project.snapshot)
        original = client.get(path + "/snapshots/current").json()
        archetype = client.get(path + "/archetypes").json()[0]
        twin = next(
            item
            for item in original["snapshot"]["twin_versions"]
            if item["profile"]["persona_reference"]["persona_id"] == archetype["persona_id"]
        )
        changed = {key: archetype[key] for key in BODY} | {
            "description": "Checks late arrivals.",
            "based_on_version_number": archetype["version_number"],
        }
        assert (
            client.send("PATCH", path + "/archetypes/" + archetype["persona_id"], changed).status
            == 200
        )
        readiness = client.get(path + "/readiness").json()
        assert readiness["context_current"] and not readiness["archetypes_current"]
        assert not readiness["approved_current_snapshot"]
        assert (
            client.post(path + "/context-alignment").json()["detail"]["code"]
            == "ARCHETYPES_CHANGED"
        )
        generated = client.post(path + "/snapshots/generate").json()["snapshot_version"]
        next_twin = next(
            item
            for item in generated["snapshot"]["twin_versions"]
            if item["twin_id"] == twin["twin_id"]
        )
        assert next_twin["version_number"] == 2 and next_twin["based_on_version_number"] == 1
        assert next_twin["view"]["basis"] == "PROVISIONAL"
        assert "view" not in project.snapshots[0]["snapshot"]["twin_versions"][0]
        assert project.snapshots[0] == before
        history = client.get(path + "/snapshots").json()
        assert history[0]["snapshot"]["twin_versions"] == original["snapshot"]["twin_versions"]


def test_fake_limit_pending_and_strict_input_match_the_api():
    with FakeStudio(language="en") as studio:
        client = signed_in(studio)
        project = studio.seed_project(owner="owner@example.com", name="Reception", through="team")
        path = f"/projects/{project.id}/user-modeling/archetypes"
        assert client.post(path, BODY | {"name": " "}).status == 422
        for number in range(8):
            assert client.post(path, BODY | {"name": f"Staff {number}"}).status == 201
        assert client.post(path, BODY).json()["detail"]["code"] == "ARCHETYPE_LIMIT_REACHED"
        project.updates.append({"status": "PROPOSED"})
        assert client.post(path, BODY).json()["detail"]["code"] == "USER_TWIN_REVISION_PENDING"
        assert (
            client.post(f"/projects/{project.id}/user-modeling/snapshots/generate").json()[
                "detail"
            ]["code"]
            == "USER_TWIN_REVISION_PENDING"
        )


def test_cli_archetypes_add_edit_clear_goals_remove_and_json(tmp_path):
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio, through="team")
        result = ut(
            tmp_path,
            "archetypes",
            "add",
            "--name",
            BODY["name"],
            "--description",
            BODY["description"],
            "--role",
            BODY["role"],
            "--goal",
            "First",
            "--goal",
            "Second",
            "--context",
            BODY["context"],
            "--json",
        )
        assert result.status == 0, result.errors
        first = json.loads(result.output)
        result = ut(tmp_path, "archetypes", "edit", first["persona_id"], "--clear-goals", "--json")
        assert result.status == 0, result.errors
        edited = json.loads(result.output)
        assert edited["goals"] == [] and edited["version_number"] == 2
        assert (
            ut(
                tmp_path,
                "archetypes",
                "edit",
                first["persona_id"],
                "--clear-goals",
                "--goal",
                "New",
            ).status
            == 2
        )
        assert ut(tmp_path, "archetypes", "remove", first["persona_id"]).status == 0
        assert len(project.personas[first["persona_id"]]) == 3


def test_cli_persona_json_and_why_preserve_status_rationale_and_sources(tmp_path):
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio, through="twins")
        twin = project.current("twins")["snapshot"]["twin_versions"][0]
        result = ut(tmp_path, "twins", "persona", twin["twin_id"], "--json")
        assert result.status == 0, result.errors
        assert json.loads(result.output) == twin["view"]
        result = ut(tmp_path, "twins", "persona", twin["twin_id"], "--why", "description")
        assert result.status == 0, result.errors
        assert (
            "Provisional" in result.output
            and "Why?" in result.output
            and "PROJECT_BRIEF" in result.output
        )
        result = ut(tmp_path, "--lang", "it", "twins", "persona", twin["twin_id"], "--why", "needs")
        assert (
            "Provvisorio" in result.output
            and "Perché?" in result.output
            and "Dedotto" in result.output
        )


@pytest.mark.parametrize(
    "status,sources,expected",
    [
        ("EMPIRICALLY_SUPPORTED", [{"source_kind": "EMPIRICAL_RESEARCH"}], "EVIDENCED"),
        ("MODEL_INFERRED", [], "INFERRED"),
        ("UNSUPPORTED_ASSUMPTION", [], "HYPOTHESIZED"),
        ("CONTESTED", [], "CONTESTED"),
        ("USER_PROVIDED", [], "HYPOTHESIZED"),
    ],
)
def test_readable_five_states_and_owner_input_is_not_empirical(status, sources, expected):
    assert (
        display_status(
            {
                "value": {"kind": "TEXT", "text": "Known"},
                "epistemic_status": status,
                "provenance": sources,
            }
        )
        == expected
    )
    assert (
        display_status(
            {"value": {"kind": "UNKNOWN"}, "epistemic_status": status, "provenance": sources}
        )
        == "UNKNOWN"
    )


def test_legacy_fallback_does_not_promote_basis_or_use_a_cross_project_archetype():
    reference = {"persona_id": "p", "version_number": 1, "content_hash": "a" * 64}
    version = {"project_id": "one", "profile": {"persona_reference": reference, "observations": []}}
    persona = reference | {
        "project_id": "two",
        "profile": {
            "observations": [
                {
                    "observation_key": "persona.summary",
                    "value": {"kind": "TEXT", "text": "Private description"},
                }
            ]
        },
    }
    view = view_of(version, persona)
    assert (
        view["basis"] == "PROVISIONAL"
        and view["persona"]["description"]["display_status"] == "UNKNOWN"
    )


@pytest.mark.parametrize(
    "language,labels",
    [
        (
            "en",
            (
                "Basis: Provisional",
                "Represents:",
                "Does not represent: Unknown",
                "Evidence gaps: Unknown",
            ),
        ),
        (
            "it",
            (
                "Fondamento: Provvisorio",
                "Chi rappresenta:",
                "Chi non rappresenta: Sconosciuto",
                "Lacune nelle evidenze: Sconosciuto",
            ),
        ),
    ],
)
def test_default_cli_surfaces_declare_basis_scope_and_unknown_gaps(tmp_path, language, labels):
    with FakeStudio(language=language) as studio:
        project = seeded(tmp_path, studio, through="twins")
        twin = project.current("twins")["snapshot"]["twin_versions"][0]
        original = copy.deepcopy(project.snapshot)
        for action in (("persona", twin["twin_id"]), ("show", "1"), ("list",)):
            result = ut(tmp_path, "--lang", language, "twins", *action)
            assert result.status == 0, result.errors
            assert all(label in result.output for label in labels)
        assert project.snapshot == original


def test_fake_added_and_archived_archetypes_change_roster_without_reusing_a_twin_identity():
    with FakeStudio(language="en") as studio:
        client = signed_in(studio)
        project = studio.seed_project(owner="owner@example.com", name="Roster", through="twins")
        path = f"/projects/{project.id}/user-modeling"
        previous = copy.deepcopy(project.snapshot)
        old_ids = {item["twin_id"] for item in previous["snapshot"]["twin_versions"]}
        removed = client.get(path + "/archetypes").json()[0]
        added = client.post(path + "/archetypes", BODY).json()
        assert (
            client.send(
                "DELETE",
                path + "/archetypes/" + removed["persona_id"],
                {"based_on_version_number": removed["version_number"]},
            ).status
            == 200
        )
        assert not client.get(path + "/readiness").json()["archetypes_current"]
        sections = project.sections()
        modeling = next(item for item in sections["sections"] if item["key"] == "USER_TWINS")
        assert "ARCHETYPES_CHANGED" in modeling["reasons"]
        assert modeling["blocked"] == "PREPARE_TWINS"
        generated = client.post(path + "/snapshots/generate").json()["snapshot_version"]
        versions = generated["snapshot"]["twin_versions"]
        assert all(
            item["profile"]["persona_reference"]["persona_id"] != removed["persona_id"]
            for item in versions
        )
        fresh = next(
            item
            for item in versions
            if item["profile"]["persona_reference"]["persona_id"] == added["persona_id"]
        )
        assert fresh["version_number"] == 1 and fresh["based_on_version_number"] is None
        assert fresh["twin_id"] not in old_ids
        assert project.snapshots[0] == previous
