from __future__ import annotations

import json
from dataclasses import replace

import pytest

from orchestwin.cli.commands.evidence import file_text
from orchestwin.cli.errors import CliError
from orchestwin.cli.mcp.knowledge import load as load_knowledge
from orchestwin.cli.messages import text
from orchestwin.cli.project import ProjectFolder
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from src.test.python.knowledge.test_research_evidence import evidence_document

from .support import fake_studio
from .support.fake_studio import FakeStudio
from .test_mcp_knowledge import with_files
from .test_mcp_tools import build, run
from .test_package_import import sign_in
from .test_twin_update_flow import seeded, ut


@pytest.mark.parametrize("language", ["it", "en"])
def test_text_source_complete_cli_review_retirement_and_deletion(tmp_path, language):
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio, through="twins")
        directory = tmp_path / "project"
        source = directory / "source.txt"
        source.write_bytes(
            b"Synthetic test support.\r\nSynthetic test contradiction.\rSynthetic added vocabulary."
        )
        added = ut(
            tmp_path,
            "--lang",
            language,
            "--yes",
            "evidence",
            "add",
            "source.txt",
            "--limitations",
            "Synthetic, nonempirical test.",
        )
        assert added.status == 0, (added.output, added.errors, studio.errors)
        assert project.evidence_versions[0]["empirical"] is False
        assert "\r" not in project.evidence_texts[(project.evidence_versions[0]["id"], 1)]
        listed = ut(tmp_path, "evidence", "--json")
        document = json.loads(listed.output)
        assert "text" not in document["evidence"][0]
        before = project.snapshot["snapshot"]["twin_versions"][0]
        updated = ut(
            tmp_path,
            "--lang",
            language,
            "--yes",
            "twins",
            "update",
            "1",
            "--evidence",
            "EVD-001",
            answers=["", "e", "Corrected interpretation.", "d"],
        )
        assert updated.status == 0, (updated.output, updated.errors, studio.errors)
        twin = project.snapshot["snapshot"]["twin_versions"][0]
        assert twin["twin_id"] == before["twin_id"]
        assert twin["version_number"] == before["version_number"] + 1
        assert twin["profile"]["persona_reference"] == before["profile"]["persona_reference"]
        assert len(project.evidence_changes) == 2
        assert (
            text(
                "twins.update_evidence_approved",
                language,
                name=twin["profile"]["name"],
                label=project.twin_learning()[0]["label"],
                source="EVD-001",
                version=1,
                count=2,
            )
            in updated.output
        )
        assert "ha imparato: -." not in updated.output
        assert "learned: -." not in updated.output
        status = {item["observation_key"]: item for item in twin["profile"]["observations"]}
        assert status["user_twin.context_of_use"]["epistemic_status"] == "CONTESTED"
        assert status["user_twin.context_of_use"]["value"] == next(
            item["value"]
            for item in before["profile"]["observations"]
            if item["observation_key"] == "user_twin.context_of_use"
        )
        assert "Corrected interpretation." in status["user_twin.context_of_use"]["rationale"]
        retired = ut(
            tmp_path,
            "--yes",
            "evidence",
            "retire",
            "EVD-001",
            "--reason",
            "Synthetic test complete.",
        )
        assert retired.status == 0, (retired.output, retired.errors, studio.errors)
        twin = project.snapshot["snapshot"]["twin_versions"][0]
        statuses = {
            item["observation_key"]: item["epistemic_status"]
            for item in twin["profile"]["observations"]
        }
        assert (
            statuses["user_twin.goals"]
            == statuses["user_twin.context_of_use"]
            == "UNSUPPORTED_ASSUMPTION"
        )
        deleted = ut(tmp_path, "--yes", "evidence", "delete-text", "EVD-001")
        assert deleted.status == 0, (deleted.output, deleted.errors, studio.errors)
        assert project.evidence_texts == {}
        assert all(not source["text_available"] for source in project.evidence_versions)
        assert studio.errors == []


def test_file_size_error_invites_splitting_and_preserves_all_whitespace(tmp_path):
    path = tmp_path / "source.md"
    raw = "  A\tB\r\nC\rD  "
    path.write_bytes(raw.encode("utf-8"))
    assert file_text(path) == raw
    path.write_bytes(b"x" * 24001)
    with pytest.raises(CliError) as error:
        file_text(path)
    assert error.value.code == "EVIDENCE_LIMIT"


def test_raw_crlf_input_is_bounded_before_utf8_and_canonical_limits(tmp_path):
    path = tmp_path / "source.txt"
    raw = "a\r\n" * 8000
    path.write_bytes(raw.encode("utf-8"))
    assert file_text(path) == raw
    path.write_bytes(b"\xff" * 65537)
    with pytest.raises(CliError) as refused:
        file_text(path)
    assert refused.value.code == "EVIDENCE_LIMIT"


def test_add_requires_owner_acknowledgement_before_sending_document(tmp_path):
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio, through="twins")
        (tmp_path / "project" / "source.txt").write_text(
            "Synthetic private test body.", encoding="utf-8"
        )
        rejected = ut(tmp_path, "evidence", "add", "source.txt", answers=["n"])
        assert rejected.status == 0
        assert "Anonymize" in rejected.output
        assert not any(
            request.method == "POST" and request.path.endswith("/evidence")
            for request in studio.requests
        )


def test_corrected_addition_preserves_existing_items_and_reopens_downstream(tmp_path):
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        (tmp_path / "project" / "source.txt").write_text(
            "Synthetic support.\nSynthetic contradiction.\nSynthetic addition.", encoding="utf-8"
        )
        assert ut(tmp_path, "--yes", "evidence", "add", "source.txt").status == 0
        before = project.snapshot["snapshot"]["twin_versions"][0]
        original = next(
            item["value"]["items"]
            for item in before["profile"]["observations"]
            if item["observation_key"] == "user_twin.preferred_vocabulary"
        )
        result = ut(
            tmp_path,
            "--lang",
            "en",
            "--yes",
            "twins",
            "update",
            "1",
            "--evidence",
            "EVD-001",
            answers=["d", "d", "e", "Corrected synthetic vocabulary."],
        )
        assert result.status == 0, (result.output, result.errors, studio.errors)
        twin = project.snapshot["snapshot"]["twin_versions"][0]
        observation = next(
            item
            for item in twin["profile"]["observations"]
            if item["observation_key"] == "user_twin.preferred_vocabulary"
        )
        assert observation["value"]["items"] == [*original, "Corrected synthetic vocabulary."]
        assert twin["twin_id"] == before["twin_id"]
        shown = ut(tmp_path, "evidence", "show", "EVD-001", "--json")
        assert json.loads(shown.output)["citations"][0]["effect"] == "ADDS"
        folder = load_knowledge(tmp_path / "project" / "orchestwin")
        assert folder.approved == ("brief", "team", "twins")
        omitted = folder.evidence()["omitted_sections"]
        assert [item["stage"] for item in omitted] == ["requirements", "design"]
        assert omitted[0]["affected_codes"]["requirements"]
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_mcp_evidence_is_offline_read_only_and_returns_quotes_without_body(tmp_path, language):
    sources = real_sources()
    document = evidence_document(sources)
    folder = build_knowledge_folder(
        replace(sources, research_evidence=document), version_number=3, created_at=PUBLISHED_AT
    )
    with_files(tmp_path, folder.files, language=language)
    tools, _ = build(tmp_path, language=language)
    result = run(tools, "get_evidence", code="evd-001")
    assert result["citations"] == document["citations"]
    assert result["original_text_included"] is False
    assert "Unexported synthetic preface" not in json.dumps(result)
    details = run(tools, "get_twin", twin="1")
    assert details["evidence"]["citations"] == document["citations"]
    definition = next(item for item in tools.definitions() if item["name"] == "get_evidence")
    assert definition["annotations"]["readOnlyHint"] is True
    assert definition["annotations"]["openWorldHint"] is False


def test_imported_source_reassociates_exact_hash_without_promoting_or_changing_identity(tmp_path):
    sources = real_sources()
    document = evidence_document(sources)
    folder = build_knowledge_folder(
        replace(sources, research_evidence=document), version_number=3, created_at=PUBLISHED_AT
    )
    archive = tmp_path / "synthetic.zip"
    archive.write_bytes(folder_archive(folder).content)
    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        imported = ut(tmp_path, "--yes", "package", "import", str(archive), answers=["y"])
        assert imported.status == 0, (imported.output, imported.errors, studio.errors)
        link = ProjectFolder(tmp_path / "project").link()
        project = studio.project(link.project_id)
        source = project.evidence_versions[0]
        assert source["id"] != document["evidence"][0]["id"]
        assert source["version"] == 2 and source["text_available"] is False
        assert source["empirical"] is False
        imported_citation = studio._evidence_citations(project)[0]
        assert imported_citation["status"] == document["citations"][0]["status"] == "ACTIVE"
        assert imported_citation["twin_version"] == document["citations"][0]["twin_version"]
        assert imported_citation["citation"] == {
            **document["citations"][0]["citation"],
            "source_id": source["id"],
        }
        assert imported_citation["imported_from"]["mapped_twin_version"] == 1
        why = studio._why_document(project)
        claim = next(
            node
            for node in why["nodes"]
            if node["kind"] == "USER_TWIN_CLAIM"
            and node["reference"]["artifact_id"] == imported_citation["twin_id"]
            and node["code"].endswith(":user_twin.goals")
        )
        assert len(claim["citations"]) == 1
        assert claim["citations"][0]["status"] == "ACTIVE"
        assert claim["citations"][0]["applicable"] is False
        before = json.dumps(project.snapshot, sort_keys=True)
        original = (
            "Unexported synthetic preface.\r\n"
            + document["citations"][0]["citation"]["quote"].replace("\n", "\r\n")
            + "\r\nUnexported synthetic ending."
        )
        (tmp_path / "project" / "source.txt").write_bytes(original.encode("utf-8"))
        result = ut(
            tmp_path, "--yes", "evidence", "reassociate", "EVD-001", "source.txt", "--version", "2"
        )
        assert result.status == 0, (result.output, result.errors, studio.errors)
        assert source["text_available"] is True
        assert len(project.evidence_versions) == 1
        assert json.dumps(project.snapshot, sort_keys=True) == before
        assert project.gates == {}
        assert (
            project.evidence_changes[0]["change"]["citation"]["quote"]
            == document["citations"][0]["citation"]["quote"]
        )
        (tmp_path / "project" / "source.txt").write_text(
            "Different synthetic text.", encoding="utf-8"
        )
        mismatch = ut(tmp_path, "--yes", "evidence", "reassociate", "EVD-001", "source.txt")
        assert mismatch.status != 0
        assert "does not match the imported version hash" in mismatch.errors
        assert studio.errors == []


def test_empty_evidence_proposal_preserves_and_shows_individual_rejection_count(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        fake_studio,
        "bind_evidence_update",
        lambda result, *, context: ("Synthetic rejected quotes.", (), 3),
    )
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio, through="twins")
        (tmp_path / "project" / "source.txt").write_text("Synthetic source.", encoding="utf-8")
        assert ut(tmp_path, "--yes", "evidence", "add", "source.txt").status == 0
        result = ut(
            tmp_path, "--lang", "en", "--yes", "twins", "update", "1", "--evidence", "EVD-001"
        )
        assert result.status == 0, (result.output, result.errors, studio.errors)
        update = project.updates[0]
        assert update["status"] == "EMPTY"
        assert update["evidence"]["rejected_changes"] == 3
        assert "3" in result.output and "rejected" in result.output
        assert project.evidence_changes == []
