"""Scoped SQL and read-only adapter checks without executing project code."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from orchestwin.api import web_execution_read_runtime as module
from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.attempt_persistence import web_execution_attempt_to_record
from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor
from orchestwin.web_execution.phase_browser_transport import WebBrowserTransportResult
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import WebEvidenceReference
from orchestwin.web_execution.static_browser_jobs import canonical_bytes
from src.test.python.web_execution.test_attempt_persistence import create_attempt
from src.test.python.web_execution.test_phase_browser_evidence import envelope, events, report
from src.test.python.web_execution.test_phase_executor import setup_executor

OWNER = UUID(int=5801)
PROJECT = UUID(int=5802)
EXECUTION = UUID(int=5803)


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def execute(self, query):
        self.queries.append(query)
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(
                all=lambda: self.rows, one_or_none=lambda: self.rows[0] if self.rows else None
            )
        )


@pytest.fixture
def schema(monkeypatch: pytest.MonkeyPatch):
    # SQL clauses are real SQLAlchemy expressions; no database connection is made.
    attempts = sa.table(
        "web_execution_attempts",
        *[sa.column(name) for name in ("id", "project_id", "created_by_user_id", "attempt_number")],
    )
    projects = sa.table(
        "projects", *[sa.column(name) for name in ("id", "owner_user_id", "archived_at")]
    )
    monkeypatch.setattr(module, "_schema", lambda: (attempts, projects))


def test_query_filters_owner_creator_project_and_archival(schema) -> None:
    query = module._owned_attempts(OWNER).where(module._schema()[0].c.project_id == PROJECT)
    compiled = query.compile(dialect=postgresql.dialect())
    text = str(compiled)
    assert "projects.owner_user_id =" in text
    assert "web_execution_attempts.created_by_user_id =" in text
    assert "projects.archived_at IS NULL" in text
    assert "web_execution_attempts.project_id =" in text
    assert OWNER in compiled.params.values()
    assert PROJECT in compiled.params.values()


def test_empty_history_remains_empty_and_closes_session(schema) -> None:
    session = Session([])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    assert asyncio.run(service.execution_history(owner_user_id=OWNER, project_id=PROJECT)) == ()
    assert session.closed
    assert "ORDER BY web_execution_attempts.attempt_number" in str(session.queries[0])


def test_missing_execution_does_not_invent_a_report(schema) -> None:
    session = Session([])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    assert (
        asyncio.run(service.execution_report(owner_user_id=OWNER, execution_id=EXECUTION)) is None
    )
    assert session.closed


def test_existing_execution_is_decoded_before_return(
    schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {"attempt_snapshot": "test sentinel"}
    session = Session([row])
    observed = []

    def decode(value):
        observed.append(value)
        return SimpleNamespace(
            to_snapshot=lambda: {"id": str(EXECUTION), "report": {"status": "FAILED"}}
        )

    monkeypatch.setattr(module, "_decode_attempt", decode)
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    report = asyncio.run(service.execution_report(owner_user_id=OWNER, execution_id=EXECUTION))
    assert report == {"status": "FAILED"}
    assert observed == [row]
    assert session.closed


def test_bad_hash_never_becomes_success(schema, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_row):
        raise ValueError("private-row-value")

    monkeypatch.setattr(module, "_decode_attempt", reject)
    session = Session([{}])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.execution(owner_user_id=OWNER, execution_id=EXECUTION))
    assert caught.value.status_code == 409
    assert "private" not in str(caught.value.detail)
    assert session.closed


def test_constructor_never_opens_a_session() -> None:
    def prohibited():
        raise AssertionError("startup must not connect")

    assert module.SqlAlchemyWebExecutionReadApiService(prohibited) is not None


def browser_fixture(tmp_path, *, case="passed"):
    """Produce canonical domain rows/CAS with the real adapter and a fake transport."""

    async def prepare():
        executor, contract, store, _ = setup_executor(tmp_path)
        executor.bind_attempt(EXECUTION)
        validation = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        identity = WebPhaseRunnerIdentity("BROWSER", "sha256:" + "c" * 64, "d" * 64, "e" * 64)
        runtime = SimpleNamespace(
            execution_attempt_id=EXECUTION,
            contract_content_hash=contract.content_hash,
            bootstrap_manifest_hash=identity.bootstrap_manifest_hash,
            image_id="sha256:" + "b" * 64,
        )

        class Transport:
            async def execute(self, job, **kwargs):
                body = report(job)
                if case == "console":
                    observed = events()
                    observed["console_messages"].append(
                        {"level": "ERROR", "message": "development failure", "location": None}
                    )
                    body["screens"][0]["events"] = envelope(canonical_bytes(observed))
                raw = b'{"partial":' if case == "timeout" else canonical_bytes(body)
                return WebBrowserTransportResult(
                    (
                        (
                            "EXECUTE",
                            BoundedHostProcessResult(
                                "TIMED_OUT" if case == "timeout" else "COMPLETED",
                                None if case == "timeout" else 0,
                                raw,
                                b"actual stderr",
                                None,
                            ),
                        ),
                    ),
                    None if case == "timeout" else 0,
                    True,
                    "WEB_BROWSER_TRANSPORT_LIMIT_OR_FAILURE" if case == "timeout" else None,
                    "d" * 64,
                    "e" * 64,
                )

        browser = await GovernedWebBrowserExecutor(
            runner_identity=identity,
            repo_root=Path(__file__).parents[4],
            evidence_store=store,
            transport=Transport(),
        ).execute(
            contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE),
            contract=contract,
            runtime=runtime,
            execution_attempt_id=EXECUTION,
        )
        await executor.finalize()
        base = create_attempt(attempt_id=EXECUTION)
        source = replace(
            base.source_revision, project_id=PROJECT, source_tree_hash=contract.source_tree_hash
        )
        phases = tuple(
            browser
            if item.phase is WebExecutionPhase.BROWSER_EVIDENCE
            else validation
            if item.phase is WebExecutionPhase.VALIDATE
            else item
            for item in base.report.phase_results
        )
        attempt = replace(
            base,
            project_id=PROJECT,
            created_by_user_id=OWNER,
            source_revision=source,
            report=replace(
                base.report,
                source_tree_hash=source.source_tree_hash,
                runner_image_digest="b" * 64,
                policy_content_hash=executor.policy.content_hash,
                phase_results=phases,
            ),
            executed_phases=(WebExecutionPhase.VALIDATE, WebExecutionPhase.BROWSER_EVIDENCE),
            started_at=validation.started_at,
            completed_at=browser.completed_at,
        )
        manifests = [
            (ref, json.loads(store.read(ref.storage_key)))
            for ref in browser.artifact_refs
            if ref.media_type == "application/json"
        ]
        reference, manifest = next(
            (ref, body)
            for ref, body in manifests
            if body.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE"
        )
        return attempt, store, reference, manifest

    return asyncio.run(prepare())


def replace_manifest(attempt, store, old_ref, manifest):
    saved = store.store_artifact(
        run_id=EXECUTION,
        command_id="test",
        normalized_path="browser/execution.json",
        content=canonical_bytes(manifest),
        media_type="application/json",
    )
    replacement = WebEvidenceReference(
        saved.storage_key, saved.sha256_digest, saved.size_bytes, saved.media_type
    )
    return replace(
        attempt,
        report=replace(
            attempt.report,
            phase_results=tuple(
                replace(
                    phase,
                    artifact_refs=tuple(
                        sorted(
                            replacement if ref == old_ref else ref for ref in phase.artifact_refs
                        )
                    ),
                )
                if phase.phase is WebExecutionPhase.BROWSER_EVIDENCE
                else phase
                for phase in attempt.report.phase_results
            ),
        ),
    )


@pytest.mark.parametrize("case", ["passed", "console", "timeout"])
def test_browser_read_returns_verified_stored_manifest_without_writes(
    schema, tmp_path, monkeypatch, case
):
    attempt, store, _, manifest = browser_fixture(tmp_path, case=case)
    session = Session([web_execution_attempt_to_record(attempt)])
    root = tmp_path / "evidence"
    before = {
        str(path.relative_to(root)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        type(store), "store_artifact", lambda *a, **kw: pytest.fail("read wrote an artifact")
    )
    monkeypatch.setattr(type(store), "store_log", lambda *a, **kw: pytest.fail("read wrote a log"))
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session, evidence_root=root)
    result = asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION))
    assert result == manifest
    assert (
        result["status"] == {"passed": "PASSED", "console": "FAILED", "timeout": "TIMED_OUT"}[case]
    )
    assert (result["bundle"] is None) is (case == "timeout")
    assert result["formal_run_started"] is result["level_d_validated"] is False
    assert session.closed
    query = session.queries[0].compile(dialect=postgresql.dialect())
    assert "projects.owner_user_id =" in str(query)
    assert "web_execution_attempts.created_by_user_id =" in str(query)
    assert "projects.archived_at IS NULL" in str(query)
    assert "web_execution_attempts.id =" in str(query)
    assert OWNER in query.params.values() and EXECUTION in query.params.values()
    after = {
        str(path.relative_to(root)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("existing", [False, True])
def test_missing_browser_evidence_is_not_fabricated(schema, tmp_path, existing):
    rows = (
        [web_execution_attempt_to_record(create_attempt(attempt_id=EXECUTION))] if existing else []
    )
    session = Session(rows)
    root = tmp_path / "absent"
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session, evidence_root=root)
    assert (
        asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION)) is None
    )
    assert session.closed and not root.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "attempt",
        "source",
        "tree",
        "contract",
        "runner",
        "job_hash",
        "bundle",
        "metadata",
        "phase_status",
        "nested_media",
        "nested_size",
        "nested_key",
        "missing_artifact",
        "tampered_artifact",
    ],
)
def test_browser_read_rejects_tampered_cas_and_self_consistent_unbound_manifests(
    schema, tmp_path, corruption
):
    attempt, store, ref, manifest = browser_fixture(tmp_path)
    if corruption in {"missing_artifact", "tampered_artifact"}:
        screenshot = manifest["browser_evidence"]["screens"][0]["artifacts"]["screenshot"]
        path = tmp_path / "evidence" / screenshot["storage_key"]
        if corruption == "missing_artifact":
            path.unlink()
        else:
            path.write_bytes(b"untrusted private replacement")
    else:
        if corruption == "attempt":
            manifest["execution_attempt_id"] = str(UUID(int=9999))
        elif corruption == "source":
            manifest["source_revision_content_hash"] = "f" * 64
        elif corruption == "tree":
            manifest["source_tree_hash"] = "f" * 64
        elif corruption == "contract":
            manifest["contract_content_hash"] = "f" * 64
        elif corruption == "runner":
            manifest["browser_image_id"] = "sha256:" + "f" * 64
        elif corruption == "job_hash":
            manifest["job"]["job_content_hash"] = "f" * 64
        elif corruption == "bundle":
            manifest["bundle"]["routes"][0]["final_path"] = "/invented"
        elif corruption == "metadata":
            manifest["browser_evidence"]["versions"]["playwright"] = "invented"
        elif corruption == "phase_status":
            manifest["status"] = "FAILED"
        elif corruption == "nested_media":
            manifest["browser_evidence"]["screens"][0]["artifacts"]["screenshot"]["media_type"] = (
                "text/html"
            )
        elif corruption == "nested_size":
            manifest["browser_evidence"]["screens"][0]["artifacts"]["screenshot"]["size_bytes"] += 1
        elif corruption == "nested_key":
            manifest["browser_evidence"]["screens"][0]["artifacts"]["screenshot"]["storage_key"] = (
                "../private"
            )
        attempt = replace_manifest(attempt, store, ref, manifest)
    session = Session([web_execution_attempt_to_record(attempt)])
    service = module.SqlAlchemyWebExecutionReadApiService(
        lambda: session, evidence_root=tmp_path / "evidence"
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION))
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "WEB_EXECUTION_EVIDENCE_INTEGRITY_FAILED"}
    assert session.closed


def test_foreign_or_missing_attempt_cannot_read_any_cas_object(schema, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "read_regular", lambda *a, **kw: pytest.fail("unowned read"))
    session = Session([])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session, evidence_root=tmp_path)
    assert (
        asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION)) is None
    )
    assert session.closed


def test_duplicate_browser_manifests_fail_closed(schema, tmp_path):
    attempt, store, old_ref, manifest = browser_fixture(tmp_path)
    manifest["recipe_content_hash"] = "f" * 64
    changed = replace_manifest(attempt, store, old_ref, manifest)
    changed = replace(
        changed,
        report=replace(
            changed.report,
            phase_results=tuple(
                replace(phase, artifact_refs=tuple(sorted((*phase.artifact_refs, old_ref))))
                if phase.phase is WebExecutionPhase.BROWSER_EVIDENCE
                else phase
                for phase in changed.report.phase_results
            ),
        ),
    )
    session = Session([web_execution_attempt_to_record(changed)])
    service = module.SqlAlchemyWebExecutionReadApiService(
        lambda: session, evidence_root=tmp_path / "evidence"
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION))
    assert error.value.status_code == 409


def test_partial_browser_manifest_requires_a_valid_transport_status(schema, tmp_path):
    attempt, store, ref, manifest = browser_fixture(tmp_path, case="timeout")
    manifest["operations"][0]["status"] = "INVENTED"
    attempt = replace_manifest(attempt, store, ref, manifest)
    session = Session([web_execution_attempt_to_record(attempt)])
    service = module.SqlAlchemyWebExecutionReadApiService(
        lambda: session, evidence_root=tmp_path / "evidence"
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.browser_evidence(owner_user_id=OWNER, execution_id=EXECUTION))
    assert error.value.status_code == 409
