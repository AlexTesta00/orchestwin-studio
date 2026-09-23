"""Configured preparation never executes, approves, or trusts browser-supplied runner IDs."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from orchestwin.api import execution_launch as launch
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.jvm_execution import JvmApiCommandResult, JvmApiCommandStatus
from orchestwin.api.web_execution import WebApiCommandResult, WebApiCommandStatus
from orchestwin.sandbox.execution_profiles import ExecutionTarget


def revision(target=ExecutionTarget.JVM_JAVA):
    return SimpleNamespace(
        id=uuid4(), content_hash="a" * 64, target_selection=SimpleNamespace(target=target)
    )


def backend():
    return SimpleNamespace(
        config=SimpleNamespace(
            enabled=True, gradle_image_id="sha256:" + "b" * 64, sbt_image_id="sha256:" + "c" * 64
        )
    )


@pytest.mark.parametrize(
    "target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA]
)
def test_defaults_bind_configured_runner_and_require_later_owner_approval(target):
    source = revision(target)
    command = launch.default_execution_command("jvm", backend(), source, None)
    assert command.source_revision_id == source.id
    assert command.runner_image_digest == ("c" if target is ExecutionTarget.JVM_SCALA else "b") * 64
    assert command.authorization_id is None
    assert command.purpose.value == "OWNER_PROJECT"
    assert command.trigger.value == "INITIAL"


@pytest.mark.parametrize("same_source,trigger", [(True, "MANUAL_RERUN"), (False, "REPAIR_RERUN")])
def test_reruns_include_all_phases_for_a_fresh_workspace(same_source, trigger):
    source = revision()
    previous = SimpleNamespace(
        source_revision=SimpleNamespace(
            content_hash=source.content_hash if same_source else "d" * 64
        )
    )
    command = launch.default_execution_command("jvm", backend(), source, previous)
    assert command.trigger.value == trigger
    assert command.rerun_phases == tuple(launch.JvmExecutionPhase)


def test_disabled_runtime_has_no_invented_defaults():
    configured = backend()
    configured.config.enabled = False
    with pytest.raises(ValueError, match="DISABLED"):
        launch.default_execution_command("jvm", configured, revision(), None)


@pytest.mark.parametrize("target", [ExecutionTarget.WEB_STATIC, ExecutionTarget.WEB_NODE_EXPRESS])
@pytest.mark.parametrize("include_checks", [False, True])
def test_web_launch_binds_browser_checks_and_requires_them_for_browser_targets(
    monkeypatch, target, include_checks
):
    source = revision(target)
    owner, project = uuid4(), uuid4()

    class Sources:
        def __init__(self, session, *, owner_user_id):
            assert owner_user_id == owner

        async def current(self, *, project_id):
            assert project_id == project
            return source

    class Attempts(Sources):
        async def current(self, *, project_id):
            return None

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(launch, "SqlAlchemyWebSourceRevisionRepository", Sources)
    monkeypatch.setattr(launch, "SqlAlchemyWebExecutionAttemptRepository", Attempts)
    monkeypatch.setattr(
        launch,
        "load_phase_runner_identity",
        lambda *args, kind, **kwargs: SimpleNamespace(
            image_id="sha256:" + ("b" if kind == "NODE" else "c") * 64
        ),
    )
    service = SimpleNamespace(
        sessions=sessions,
        backend=SimpleNamespace(
            config=SimpleNamespace(enabled=True, runner_manifest="fixture", repo_root="fixture"),
            policy=SimpleNamespace(content_hash="d" * 64),
        ),
        prepare_execution=AsyncMock(
            return_value=WebApiCommandResult(
                WebApiCommandStatus.EXECUTION_PREPARED, {"id": str(uuid4())}, "Prepared only."
            )
        ),
    )
    app = FastAPI()
    app.state.web_execution_start_api_service = service
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    app.include_router(launch.create_execution_launch_router())
    body = {
        "source_revision_id": str(source.id),
        "source_revision_content_hash": source.content_hash,
    }
    if include_checks:
        body.update(
            declared_routes=[],
            browser_interactions=[
                {
                    "route_id": "root",
                    "actions": [
                        {"kind": "click", "selector": "#submit", "value": None},
                        {"kind": "expect_text", "selector": "#result", "value": "Saved"},
                        {"kind": "press", "selector": "#submit", "value": "Enter"},
                        {"kind": "expect_text", "selector": "#result", "value": "Saved again"},
                    ],
                }
            ],
        )

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            response = await client.post(
                f"/projects/{project}/execution-launch/web/prepare", json=body
            )
            needs_checks = target is ExecutionTarget.WEB_STATIC and not include_checks
            assert response.status_code == (422 if needs_checks else 201), response.text
            if not needs_checks:
                command = service.prepare_execution.call_args.kwargs["command"]
                assert command.authorization_id is None and command.purpose.value == "OWNER_PROJECT"
                assert command.execution_runner_image_digest == "b" * 64
                assert command.browser_runner_image_digest == (
                    "c" * 64 if target is ExecutionTarget.WEB_STATIC else None
                )
                if include_checks:
                    assert (
                        command.browser_interactions[0].to_snapshot()
                        == body["browser_interactions"][0]
                    )
            else:
                service.prepare_execution.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,status", [("valid", 201), ("foreign", 404), ("stale", 409), ("runner_override", 422)]
)
def test_route_revalidates_source_and_only_prepares(monkeypatch, case, status):
    source = revision()
    owner, project = uuid4(), uuid4()
    reads = []

    class Sources:
        def __init__(self, session, *, owner_user_id):
            assert owner_user_id == owner

        async def current(self, *, project_id):
            reads.append(project_id)
            return None if case == "foreign" else source

    class Attempts(Sources):
        async def current(self, *, project_id):
            return None

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(launch, "SqlAlchemyJvmSourceRevisionRepository", Sources)
    monkeypatch.setattr(launch, "SqlAlchemyJvmExecutionAttemptRepository", Attempts)
    service = SimpleNamespace(
        sessions=sessions,
        backend=backend(),
        prepare_execution=AsyncMock(
            return_value=JvmApiCommandResult(
                JvmApiCommandStatus.EXECUTION_PREPARED, {"id": str(uuid4())}, "Prepared only."
            )
        ),
        start_execution=AsyncMock(),
    )
    app = FastAPI()
    app.state.jvm_execution_start_api_service = service
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    app.include_router(launch.create_execution_launch_router())

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {
                "source_revision_id": str(source.id),
                "source_revision_content_hash": "d" * 64
                if case == "stale"
                else source.content_hash,
            }
            if case == "runner_override":
                body["runner_image_digest"] = "e" * 64
            response = await client.post(
                f"/projects/{project}/execution-launch/jvm/prepare", json=body
            )
            assert response.status_code == status, response.text

    asyncio.run(run())
    service.start_execution.assert_not_called()
    assert service.prepare_execution.call_count == int(case == "valid")
    if case == "valid":
        assert reads == [project]
        assert service.prepare_execution.call_args.kwargs["command"].authorization_id is None


def static_prototype():
    def element(code, kind, content, **extra):
        return {
            "id": "id-" + code,
            "code": code,
            "kind": kind,
            "content": content,
            "accessible_name": None,
            **extra,
        }

    return {
        "entry_screen_id": "s1",
        "screens": [
            {
                "id": "s1",
                "code": "SCR-001",
                "title": "Inserimento",
                "elements": [
                    element("ELM-001", "HEADING", "Aggiungi un ospite"),
                    element(
                        "ELM-002",
                        "TEXT_INPUT",
                        "Nome ospite",
                        field_name="guest_name",
                        required=True,
                    ),
                    element("ELM-003", "BUTTON", "Aggiungi"),
                ],
            },
            {
                "id": "s2",
                "code": "SCR-002",
                "title": "Conferma",
                "elements": [
                    element("ELM-006", "HEADING", "Ospite aggiunto"),
                    element("ELM-007", "TEXT", "Esempio: 1. Mario Rossi"),
                    element("ELM-008", "LINK", "Torna"),
                ],
            },
        ],
        "transitions": [
            {
                "trigger_element_id": "id-ELM-003",
                "source_screen_id": "s1",
                "target_screen_id": "s2",
            },
            {
                "trigger_element_id": "id-ELM-008",
                "source_screen_id": "s2",
                "target_screen_id": "s1",
            },
        ],
    }


@pytest.mark.parametrize("case", ["derived", "non_static", "missing"])
def test_journey_route_derives_the_static_journey_from_the_approved_prototype(monkeypatch, case):
    owner, project = uuid4(), uuid4()
    architecture_id, design_id = uuid4(), uuid4()
    target = ExecutionTarget.WEB_VUE if case == "non_static" else ExecutionTarget.WEB_STATIC
    source = SimpleNamespace(
        id=uuid4(),
        content_hash="a" * 64,
        target_selection=SimpleNamespace(target=target),
        provenance_references=(
            SimpleNamespace(
                kind=SimpleNamespace(value="ARCHITECTURE"),
                reference_id=f"architecture:{architecture_id}",
                content_hash="e" * 64,
            ),
        ),
    )

    class Sources:
        def __init__(self, session, *, owner_user_id):
            assert owner_user_id == owner

        async def current(self, *, project_id):
            assert project_id == project
            return None if case == "missing" else source

    class Architectures(Sources):
        async def get(self, *, project_id, version_id):
            assert (project_id, version_id) == (project, architecture_id)
            return SimpleNamespace(
                content_hash="e" * 64,
                package=SimpleNamespace(
                    grounding=SimpleNamespace(
                        design_package_reference=SimpleNamespace(
                            artifact_id=design_id, content_hash="f" * 64
                        )
                    )
                ),
            )

    class Designs(Sources):
        async def get(self, *, project_id, version_id):
            assert (project_id, version_id) == (project, design_id)
            return SimpleNamespace(
                content_hash="f" * 64,
                to_snapshot=lambda: {"package": {"prototype": static_prototype()}},
            )

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(launch, "SqlAlchemyWebSourceRevisionRepository", Sources)
    monkeypatch.setattr(launch, "SqlAlchemyArchitecturePackageRepository", Architectures)
    monkeypatch.setattr(launch, "SqlAlchemyDesignPackageRepository", Designs)
    app = FastAPI()
    app.state.web_execution_start_api_service = SimpleNamespace(sessions=sessions)
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    app.include_router(launch.create_execution_launch_router())

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            return await client.get(f"/projects/{project}/execution-launch/web/journey")

    response = asyncio.run(call())
    if case == "missing":
        assert response.status_code == 404
        return
    payload = response.json()
    assert response.status_code == 200 and payload["source_revision_id"] == str(source.id)
    if case == "non_static":
        assert payload == {
            "status": "NOT_DERIVABLE",
            "reason": "JOURNEY_REQUIRES_STATIC_TARGET",
            "source_revision_id": str(source.id),
        }
        return
    assert payload["status"] == "DERIVED"
    kinds = [step["action"]["kind"] for step in payload["steps"]]
    assert kinds == ["fill", "press", "expect_not_text", "expect_contains", "click", "expect_text"]
    assert payload["browser_interactions"][0]["actions"][0]["selector"] == "#ELM-002"
    assert payload["steps"][1]["element_label"] == "Aggiungi"
