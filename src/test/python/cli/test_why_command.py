from __future__ import annotations

import hashlib
import json

import pytest

from orchestwin.cli import folder
from orchestwin.cli.mcp.knowledge import FolderProblem, load
from orchestwin.why import explain_why
from src.test.python.cli.support.fake_studio import FakeStudio, _Call, _Refusal
from src.test.python.cli.support.folders import ARCHIVE_PROJECT_ID, partial_archive, valid_files
from src.test.python.cli.support.terminal import link_folder, run_ut, store_session
from src.test.python.cli.support.transports import API, NoNetwork, ScriptedTransport
from src.test.python.cli.test_fake_studio import BOUNDARY, multipart
from src.test.python.cli.test_mcp_tools import build, run


def project_with_files(tmp_path, files=None):
    project = link_folder(tmp_path, project_id=ARCHIVE_PROJECT_ID)
    for name, content in (valid_files() if files is None else files).items():
        path = project.knowledge.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    return project


@pytest.mark.parametrize("language", ["it", "en"])
def test_why_offline_without_login_or_network_preserves_the_full_answer(tmp_path, language):
    project = project_with_files(tmp_path)
    before = folder.read_files(project.knowledge)
    document = load(project.knowledge).why(project_id=ARCHIVE_PROJECT_ID)
    expected = explain_why(document, "REQ-001")

    result = run_ut(
        ["--lang", language, "why", "REQ-001", "--offline", "--json"],
        tmp_path,
        transport=NoNetwork(),
    )

    assert result.status == 0, result.errors
    assert json.loads(result.output) == expected
    assert "--offline" in result.errors
    assert folder.read_files(project.knowledge) == before


@pytest.mark.parametrize("status", [403, 404])
def test_why_does_not_hide_authorization_or_missing_artifact_failures(tmp_path, status):
    project_with_files(tmp_path)
    store_session(tmp_path)
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{ARCHIVE_PROJECT_ID}/artifacts/why?code=REQ-001",
        status=status,
        body={"detail": {"code": "WHY_CODE_NOT_FOUND"}},
    )

    result = run_ut(["why", "REQ-001", "--json"], tmp_path, transport=transport)

    assert result.status != 0
    assert result.output == ""
    assert "Dossier" not in result.errors
    transport.assert_done()


@pytest.mark.parametrize("tamper", ["body", "extra", "project", "link", "schema"])
def test_why_verifies_hashes_schema_scope_and_derivation(tmp_path, tamper):
    project = project_with_files(tmp_path)
    manifest_path = project.knowledge / "orchestwin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "extra":
        (project.knowledge / "extra.json").write_text("{}", encoding="utf-8")
    elif tamper == "body":
        (project.knowledge / "requirements/requirements.json").write_text("{}", encoding="utf-8")
    elif tamper == "project":
        manifest["project"]["id"] = "00000000-0000-4000-8000-000000000099"
    else:
        path = "traceability/why.json" if tamper == "link" else "requirements/requirements.json"
        document = json.loads((project.knowledge / path).read_text(encoding="utf-8"))
        if tamper == "link":
            document["links"] = []
        else:
            document["version_number"] = "wrong"
        content = json.dumps(document, ensure_ascii=False)
        (project.knowledge / path).write_text(content, encoding="utf-8")
        manifest["files"][path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FolderProblem):
        load(project.knowledge).why(project_id=ARCHIVE_PROJECT_ID)


@pytest.mark.parametrize("schema_version", [2, 3])
def test_legacy_why_rebuilds_the_available_chain_and_declares_the_limit(tmp_path, schema_version):
    files = valid_files()
    manifest = json.loads(files["orchestwin.json"])
    manifest.pop("why")
    manifest["schema_version"] = schema_version
    manifest["schemas"].pop("why")
    for path in ("traceability/why.json", "schema/why.schema.json"):
        files.pop(path)
        manifest["files"].pop(path)
    files["orchestwin.json"] = json.dumps(manifest)
    project_with_files(tmp_path, files)

    result = run_ut(["why", "REQ-001", "--offline", "--json"], tmp_path, transport=NoNetwork())

    assert result.status == 0, result.errors
    assert "LEGACY_DOSSIER" in json.loads(result.output)["limits"]


def test_json_why_reports_unknown_selectors_as_a_structured_stderr_error(tmp_path):
    project_with_files(tmp_path)

    result = run_ut(
        ["why", "NO-SUCH-CLAIM", "--offline", "--json"], tmp_path, transport=NoNetwork()
    )

    assert result.status != 0
    assert result.output == ""
    assert json.loads(result.errors.splitlines()[-1]) == {
        "error": {"code": "WHY_CODE_NOT_FOUND", "candidates": []}
    }


def test_json_why_preserves_ambiguity_candidates_on_stderr(tmp_path):
    project = project_with_files(tmp_path)
    document = load(project.knowledge).why()
    candidates = [node["key"] for node in document["nodes"][:2]]
    store_session(tmp_path)
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{ARCHIVE_PROJECT_ID}/artifacts/why?code=REQ-001",
        status=409,
        body={"detail": {"code": "WHY_CODE_AMBIGUOUS", "candidates": candidates}},
    )

    result = run_ut(["why", "REQ-001", "--json"], tmp_path, transport=transport)

    assert result.status != 0
    assert result.output == ""
    assert json.loads(result.errors.splitlines()[-1]) == {
        "error": {"code": "WHY_CODE_AMBIGUOUS", "candidates": candidates}
    }
    transport.assert_done()


def test_partial_why_retains_omitted_sections(tmp_path):
    project = link_folder(tmp_path, project_id=ARCHIVE_PROJECT_ID)
    folder.unpack(partial_archive(through="requirements"), project.knowledge)

    document = load(project.knowledge).why(project_id=ARCHIVE_PROJECT_ID)

    assert document["omitted_sections"] == ["design"]
    assert not any(item["kind"] == "DESIGN_ALTERNATIVE" for item in document["nodes"])


def test_get_why_is_the_thirteenth_tool_read_only_without_spending(tmp_path):
    project = project_with_files(tmp_path)
    tools, bundle = build(tmp_path)
    definitions = tools.definitions()

    result = run(tools, "get_why", code="REQ-001")

    assert len(definitions) == 13
    assert [item["name"] for item in definitions[-2:]] == ["get_evidence", "get_why"]
    assert definitions[-1]["annotations"]["readOnlyHint"] is True
    assert result == explain_why(load(project.knowledge).why(), "REQ-001")
    assert bundle.environment.stderr.getvalue() == ""


def test_fake_studio_why_uses_the_shared_builder_without_spending():
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", "Test-password-not-real!")
    project = studio.seed_project(
        owner="owner@example.com", name="Synthetic example", through="design"
    )

    document = studio._why_document(project)
    answer = explain_why(document, "REQ-001")

    assert answer["kind"] == "orchestwin.why-answer"
    assert project.usage == []


def test_why_summary_stays_short_and_all_retains_details(tmp_path):
    project = project_with_files(tmp_path)
    answer = explain_why(load(project.knowledge).why(), "REQ-001")

    brief = run_ut(["why", "REQ-001", "--offline"], tmp_path, transport=NoNetwork())
    detailed = run_ut(["why", "REQ-001", "--offline", "--all"], tmp_path, transport=NoNetwork())

    assert brief.status == detailed.status == 0
    assert "version " + str(answer["target"]["reference"]["version_number"]) in brief.output
    assert "--all" in brief.output
    assert answer["target"]["reference"]["content_hash"] not in brief.output
    assert answer["target"]["reference"]["content_hash"] in detailed.output
    assert len(brief.output) < len(detailed.output)


@pytest.mark.parametrize(
    "gap_code", ["SOURCE_TEXT_UNAVAILABLE", "MISSING_RATIONALE", "CONTEXT_OUTDATED"]
)
def test_reader_keeps_nonbreaking_gaps_as_deduplicated_limits(tmp_path, gap_code):
    from orchestwin.cli.views.why import show
    from src.test.python.cli.test_console import console_for

    project = project_with_files(tmp_path)
    document = load(project.knowledge).why()
    for node in document["nodes"]:
        node["gaps"] = []
    target = next(node for node in document["nodes"] if node["code"] == "REQ-001")
    gap = {
        "code": gap_code,
        "node_key": target["key"],
        "related_code": None,
        "stage": "requirements",
    }
    target["gaps"] = [gap, gap]
    answer = explain_why(document, target["key"])
    console, bundle = console_for(tmp_path)

    show(console, answer)

    assert "Interrupted chain" not in bundle.output
    assert "Limits (2)" in bundle.output
    assert bundle.output.count(console.text("why.gap." + gap_code)) == 1
    assert "Reaches twin:" in bundle.output
    assert "active evidence:" in bundle.output
    assert "all branches complete:" in bundle.output


@pytest.mark.parametrize("published", [False, True, "journey"])
def test_fake_import_compares_the_exported_and_remapped_derived_documents(monkeypatch, published):
    import orchestwin.knowledge.why as portable
    from src.test.python.cli.support.folders import valid_archive

    captured = []
    normalize = portable.normalized_why

    def capture(*args, **kwargs):
        result = normalize(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(portable, "normalized_why", capture)
    if published == "journey":
        from src.test.python.cli.test_fake_studio import test_the_whole_path_runs_with_urllib

        try:
            test_the_whole_path_runs_with_urllib()
        except AssertionError:
            before = {node["key"]: node for node in captured[0]["nodes"]}
            after = {node["key"]: node for node in captured[1]["nodes"]}
            changes = [
                {
                    "key": key,
                    **{
                        name: (before[key][name], after[key][name])
                        for name in before[key]
                        if before[key][name] != after[key][name]
                    },
                }
                for key in sorted(before.keys() & after.keys())
                if before[key] != after[key]
            ]
            raise AssertionError(
                json.dumps(
                    {
                        "missing": sorted(before.keys() - after.keys()),
                        "extra": sorted(after.keys() - before.keys()),
                        "changes": changes[:3],
                    },
                    indent=2,
                )
            ) from None
        return
    studio = FakeStudio(language="en")
    studio.add_account("owner@example.com", "Test-password-not-real!")
    archive = valid_archive()
    if published:
        from orchestwin.knowledge.folder import folder_archive
        from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT

        project = studio.seed_project(
            owner="owner@example.com", name="Synthetic example", through="design"
        )
        archive = folder_archive(
            studio._knowledge_folder(
                project, ("brief", "team", "twins", "requirements", "design"), 1, PUBLISHED_AT
            )
        ).content
    content = multipart({}, {"archive": ("folder.zip", "application/zip", archive)})
    call = _Call(
        "POST",
        "/project-imports",
        studio._accounts["owner@example.com"],
        {},
        {},
        {"content-type": f"multipart/form-data; boundary={BOUNDARY}"},
        content,
        False,
    )

    try:
        reply = studio._route_import_project(call)
    except _Refusal:
        before = {node["key"]: node for node in captured[0]["nodes"]}
        after = {node["key"]: node for node in captured[1]["nodes"]}
        changes = [
            {
                name: (before[key][name], after[key][name])
                for name in before[key]
                if before[key][name] != after[key][name]
            }
            for key in before.keys() & after.keys()
            if before[key] != after[key]
        ]
        raise AssertionError(
            json.dumps(
                {
                    "missing": sorted(before.keys() - after.keys()),
                    "extra": sorted(after.keys() - before.keys()),
                    "changes": changes[:3],
                },
                ensure_ascii=True,
                indent=2,
            )
        ) from None

    assert reply.status == 201
    assert captured[0] == captured[1]
