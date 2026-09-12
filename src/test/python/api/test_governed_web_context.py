"""Execution preparation uses verified source bytes and trusted runner configuration."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_web_execution_start_runtime import _command

from orchestwin.api.governed_web_context import GovernedWebSettings, WebExecutionBackend
from orchestwin.api.web_execution import WebBrowserRouteCommand
from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)
from orchestwin.workflow.web_execution import WebExecutionPurpose


def context_fixture(tmp_path, monkeypatch):
    content = b'<!doctype html><html lang="en"><head><title>Unit7 development fixture</title></head><body><main><h1>Verified source</h1></main></body></html>'
    source_store = FileSystemWebSourceContentStore(tmp_path / "source-objects")
    entry = source_store.store(
        normalized_path="index.html", content=content, media_type="text/html"
    )
    revision = create_web_source_revision(
        revision_id=uuid4(),
        project_id=uuid4(),
        created_by_user_id=uuid4(),
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            WebImplementationLanguage.STATIC_ASSETS, None
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(entry,),
        provenance_references=(
            WebSourceProvenanceReference(
                WebSourceProvenanceKind.SOURCE_PLAN, "unit7.fixture", 1, "a" * 64
            ),
        ),
        created_at=datetime.now(UTC),
    )
    root = Path(__file__).parents[4]
    identities = {
        kind: WebPhaseRunnerIdentity(kind, "sha256:" + digest * 64, "d" * 64, "e" * 64)
        for kind, digest in (("NODE", "b"), ("PHP", "a"), ("BROWSER", "c"))
    }
    monkeypatch.setattr(
        "orchestwin.api.governed_web_context.load_phase_runner_identity",
        lambda *args, kind, **kwargs: identities[kind],
    )
    config = GovernedWebSettings(
        _env_file=None,
        enabled=True,
        repo_root=root,
        runner_manifest=tmp_path / "manifest.json",
        workspaces_root=tmp_path / "runtime",
        docker_context="desktop-linux",
    )
    backend = WebExecutionBackend(
        config=config,
        content_root=tmp_path / "source-objects",
        evidence_root=tmp_path / "evidence",
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
    )
    command = replace(
        _command(purpose=WebExecutionPurpose.PROFILE_VALIDATION),
        source_revision_id=revision.id,
        policy_content_hash=DEFAULT_SANDBOX_EXECUTION_POLICY.content_hash,
    )
    return backend, revision, command


def test_web_runtime_disabled_by_default_and_requires_explicit_absolute_paths(tmp_path):
    assert not GovernedWebSettings(_env_file=None).enabled
    with pytest.raises(ValueError):
        GovernedWebSettings(_env_file=None, enabled=True)
    with pytest.raises(ValueError):
        GovernedWebSettings(
            _env_file=None,
            enabled=True,
            repo_root=Path("relative"),
            runner_manifest=tmp_path / "manifest",
            workspaces_root=tmp_path / "work",
        )


def test_prepare_binds_actual_source_routes_and_local_runner_without_starting_docker(
    tmp_path, monkeypatch
):
    backend, revision, command = context_fixture(tmp_path, monkeypatch)
    context = backend.prepare(
        revision, command=command, registry=create_sprint08_web_profile_registry(), previous=None
    )
    assert context.payload["source_revision"]["content_hash"] == revision.content_hash
    assert (
        context.payload["contract"]["browser_evidence_request"]["source_tree_hash"]
        == revision.source_tree_hash
    )
    assert not (tmp_path / "runtime").exists()
    second = backend.prepare(
        revision,
        command=replace(
            command, declared_routes=(WebBrowserRouteCommand("details", "/details.html"),)
        ),
        registry=create_sprint08_web_profile_registry(),
        previous=None,
    )
    assert context.payload != second.payload


@pytest.mark.parametrize("invalid", ["source", "runner", "policy"])
def test_tampered_input_cannot_prepare_an_execution(tmp_path, monkeypatch, invalid):
    backend, revision, command = context_fixture(tmp_path, monkeypatch)
    if invalid == "source":
        (tmp_path / "source-objects" / revision.files[0].storage_key).write_bytes(b"changed")
    elif invalid == "runner":
        command = replace(command, execution_runner_image_digest="f" * 64)
    else:
        command = replace(command, policy_content_hash="f" * 64)
    with pytest.raises(ValueError):
        backend.prepare(
            revision,
            command=command,
            registry=create_sprint08_web_profile_registry(),
            previous=None,
        )


def test_validation_purpose_cannot_use_an_owner_initial_trigger(tmp_path, monkeypatch):
    backend, revision, command = context_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="TRIGGER"):
        backend.prepare(
            revision,
            command=replace(command, trigger=WebExecutionAttemptTrigger.INITIAL),
            registry=create_sprint08_web_profile_registry(),
            previous=None,
        )
