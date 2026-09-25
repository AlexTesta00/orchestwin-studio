"""Real-required composition controls with synthetic HTTP/model-session fixtures."""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings, ModelRuntimeMode, RuntimeEnvironment
from orchestwin.models import real_runtime
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.real_runtime import RealModelRuntimeError, build_real_model_runtime
from orchestwin.models.serialized_generation import SerializedGenerationPort
from src.test.python.api.test_training_api import _user
from src.test.python.models.final_session_support import health, make_session
from src.test.python.models.test_model_proposals import make_generator


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    generator, _ = make_generator(tmp_path, {})
    generator.configuration.token_file.write_text("proposal-secret-" + "t" * 40, encoding="ascii")
    proposal = tmp_path / "proposal.json"
    proposal.write_text(generator.configuration.model_dump_json(), encoding="utf-8")
    final = make_session(tmp_path / "final")
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_config_file": str(proposal),
                "final_evaluator_ready_file": str(final.ready_path),
            }
        ),
        encoding="utf-8",
    )
    return path, proposal, final


def test_real_factory_builds_all_twelve_tasks_and_keeps_evaluator_separate(configuration):
    runtime = build_real_model_runtime(configuration[0])
    assert type(runtime.team).__name__ == "ModelTeamProposalAdapter"
    for member, expected in (
        (runtime.user_modeling, "ModelUserModelingAdapter"),
        (runtime.requirements, "ModelRequirementsAdapter"),
        (runtime.design, "ModelDesignAdapter"),
    ):
        assert (
            member.mode.value == "MODEL_ADAPTER" and type(member.proposal_port).__name__ == expected
        )
        assert member.proposal_port.generator is runtime.team.generator
    assert runtime.proposal_configuration.temperature > 0
    assert len(TASKS) == 8
    assert runtime.final_evaluator.session.identity["adapter_id"] == "s67-final-user-twin-evaluator"
    assert runtime.final_evaluator.generation_lock is runtime.team.generator.port._lock
    assert "proposal-secret-" not in repr(runtime)


@pytest.mark.parametrize(
    "variable,value",
    [
        ("TEAM_PROPOSAL_PROVIDER", "FAKE_DETERMINISTIC"),
        ("USER_MODELING_MODE", "FAKE_DETERMINISTIC"),
        ("REQUIREMENTS_MODE", "FAKE_DETERMINISTIC"),
        ("DESIGN_MODE", "FAKE_DETERMINISTIC"),
        ("FINAL_EVALUATOR_ENABLED", "false"),
        ("PROPOSAL_MODEL_CONFIG_FILE", "different.json"),
    ],
)
def test_explicit_mixed_configuration_fails_instead_of_overriding_it(
    configuration, monkeypatch, variable, value
):
    monkeypatch.setenv("ORCHESTWIN_" + variable, value)
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CONFLICT"):
        build_real_model_runtime(configuration[0])


def test_dotenv_conflicts_and_process_precedence_are_respected(configuration, monkeypatch):
    configuration[0].with_name(".env").write_text(
        "ORCHESTWIN_REQUIREMENTS_MODE=FAKE_DETERMINISTIC\n", encoding="utf-8"
    )
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CONFLICT"):
        build_real_model_runtime(configuration[0])
    monkeypatch.setenv("ORCHESTWIN_REQUIREMENTS_MODE", "MODEL_ADAPTER")
    assert build_real_model_runtime(configuration[0]).requirements.mode.value == "MODEL_ADAPTER"


@pytest.mark.parametrize(
    "change", ["zero_temperature", "missing_token", "stopped_evaluator", "extra_manifest_field"]
)
def test_incomplete_or_incompatible_real_setup_fails_closed(configuration, change):
    manifest, proposal, final = configuration
    value = json.loads(proposal.read_text())
    if change == "zero_temperature":
        value["temperature"] = 0.0
        proposal.write_text(json.dumps(value))
    elif change == "missing_token":
        value["token_file"] = str(proposal.parent / "absent.secret")
        proposal.write_text(json.dumps(value))
    elif change == "stopped_evaluator":
        final.ready_path.with_name("stopped.json").write_text("{}")
    else:
        config = json.loads(manifest.read_text())
        config["secret_extra_field"] = "must-not-appear-in-error"
        manifest.write_text(json.dumps(config))
    with pytest.raises(RealModelRuntimeError) as error:
        build_real_model_runtime(manifest)
    assert "must-not-appear" not in str(error.value)


def test_application_composition_uses_exact_real_ports_with_evidence_store(
    configuration, monkeypatch
):
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:synthetic@127.0.0.1:1/test"
    )
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "synthetic-test-auth-secret-" + "x" * 40)
    runtime = create_default_runtime(
        ApplicationSettings(
            model_runtime_mode=ModelRuntimeMode.REAL_REQUIRED,
            model_runtime_config_file=configuration[0],
            _env_file=None,
        )
    )
    try:
        models = runtime.real_model_runtime
        assert runtime.team_proposal_service._proposal_port is models.team
        assert (
            runtime.user_modeling_services.commands._proposals is models.user_modeling.proposal_port
        )
        for stage in ("requirements", "design"):
            service = getattr(runtime, stage + "_generation_service")
            assert service._proposals is getattr(models, stage).proposal_port
            assert service._proposal_evidence_store is not None
        assert runtime.final_evaluator_runtime is models.final_evaluator
    finally:
        asyncio.run(runtime.close())


def test_real_mode_cannot_silently_become_unconfigured_and_production_cannot_use_fixtures(
    configuration,
):
    with pytest.raises(RealModelRuntimeError, match="REQUIRES_DATABASE_AND_AUTH"):
        create_default_runtime(
            ApplicationSettings(
                model_runtime_mode=ModelRuntimeMode.REAL_REQUIRED,
                model_runtime_config_file=configuration[0],
            )
        )
    with pytest.raises(RealModelRuntimeError, match="PRODUCTION_REQUIRES_REAL"):
        create_default_runtime(ApplicationSettings(environment=RuntimeEnvironment.PRODUCTION))


def proposal_health(runtime):
    return {
        "health_contract_version": 2,
        "schema_decoding": "LLGUIDANCE_JSON_SCHEMA_CANONICAL_BOUNDED_WS_V3",
        "schema_decoder_version": "1.8.0",
        "status": "READY",
        "model_name": runtime.proposal_configuration.model_name,
        "model_identity": runtime.proposal_configuration.identity.to_snapshot(),
        "supported_tasks": sorted(TASKS),
        "max_sequence_length": 16384,
        "max_output_tokens": 8192,
        "completed_generation_count": 0,
        "adapter_loaded": False,
        "adapter_active": False,
        "training_executed": False,
        "fallback_policy": "FAIL_CLOSED_NO_FAKE_FALLBACK",
    }


@pytest.mark.parametrize(
    "change", [None, "identity", "missing_task", "budget", "redirect", "old_health", "old_decoder"]
)
def test_authenticated_live_health_rejects_wrong_identity_or_capability_without_inference(
    configuration, monkeypatch, change
):
    calls = []
    payload = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            body = json.dumps(payload).encode()
            self.send_response(302 if change == "redirect" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proposal = configuration[1]
        config = json.loads(proposal.read_text())
        config["base_url"] = f"http://127.0.0.1:{server.server_port}"
        proposal.write_text(json.dumps(config))
        runtime = build_real_model_runtime(configuration[0])
        payload.update(proposal_health(runtime))
        if change == "identity":
            payload["model_identity"]["runtime_id"] = "foreign"
        if change == "missing_task":
            payload["supported_tasks"] = ["team"]
        if change == "budget":
            payload["max_output_tokens"] = 32
        if change == "old_health":
            payload.pop("health_contract_version")
        if change == "old_decoder":
            payload["schema_decoding"] = "LLGUIDANCE_JSON_SCHEMA_V1"

        async def schema(_):
            return {"revision": "synthetic"}

        monkeypatch.setattr(real_runtime, "_check_schema", schema)
        monkeypatch.setattr("orchestwin.evaluation.final_runtime.check_final_health", health)
        report = asyncio.run(runtime.check_readiness(None))
        assert report["ready"] is (change is None)
        assert report["generation_performed"] is False and report["formal_campaign_ready"] is False
        assert (
            len(calls) == 1
            and calls[0][0] == "/health"
            and calls[0][1].startswith("Bearer proposal-secret-")
        )
        assert "proposal-secret-" not in json.dumps(report)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("target", ["manifest", "proposal", "token"])
def test_changed_configuration_requires_recomposition(configuration, target):
    runtime = build_real_model_runtime(configuration[0])
    path = {
        "manifest": configuration[0],
        "proposal": configuration[1],
        "token": runtime.proposal_configuration.token_file,
    }[target]
    with path.open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CHANGED"):
        asyncio.run(runtime.check_readiness(None))


def test_shared_inference_lock_serializes_calls_and_releases_after_failure():
    active, maximum = 0, 0

    class Port:
        async def generate(self, request):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0)
                if request == "fail":
                    raise ValueError("synthetic")
                return request
            finally:
                active -= 1

    async def scenario():
        lock = asyncio.Lock()
        proposal, evaluator = (
            SerializedGenerationPort(Port(), lock),
            SerializedGenerationPort(Port(), lock),
        )
        return await asyncio.gather(
            proposal.generate("fail"),
            evaluator.generate("evaluate"),
            proposal.generate("propose"),
            return_exceptions=True,
        )

    results = asyncio.run(scenario())
    assert isinstance(results[0], ValueError) and results[1:] == ["evaluate", "propose"]
    assert maximum == 1 and active == 0


def test_database_readiness_cancels_a_stalled_connection(monkeypatch):
    cancelled = []

    class StalledSession:
        async def __aenter__(self):
            try:
                await asyncio.Future()
            finally:
                cancelled.append(True)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(real_runtime, "DATABASE_READINESS_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(RealModelRuntimeError, match="MODEL_DATABASE_SCHEMA_UNAVAILABLE"):
        asyncio.run(real_runtime._check_schema(StalledSession))
    assert cancelled == [True]


def test_cancelled_inference_keeps_slot_until_provider_finishes_and_queue_can_cancel():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        class Port:
            async def generate(self, request):
                calls.append(request)
                if request == "first":
                    entered.set()
                    await release.wait()
                return request

        port = SerializedGenerationPort(Port(), asyncio.Lock())
        first = asyncio.create_task(port.generate("first"))
        await entered.wait()
        first.cancel()
        queued = asyncio.create_task(port.generate("cancelled-in-queue"))
        second = asyncio.create_task(port.generate("second"))
        await asyncio.sleep(0)
        queued.cancel()
        first.cancel()  # Repeated cancellation must not release the active slot.
        await asyncio.sleep(0)
        assert calls == ["first"] and not first.done() and not second.done()
        release.set()
        results = await asyncio.gather(first, queued, second, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[1], asyncio.CancelledError)
        assert results[2] == "second" and calls == ["first", "second"]

    asyncio.run(scenario())


def test_api_stays_available_on_unready_models_and_disposes_resources():
    closed = []

    async def readiness(_):
        return {"ready": False}

    async def dispose():
        closed.append(True)

    runtime = ApplicationRuntime(
        real_model_runtime=SimpleNamespace(check_readiness=readiness),
        database_runtime=SimpleNamespace(session_factory=None, dispose=dispose),
    )
    with TestClient(create_app(runtime=runtime)) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert closed == [True]


def test_readiness_is_authenticated_and_rechecked_after_startup(configuration):
    state = {"ready": True, "mode": "REAL_REQUIRED"}

    async def readiness(_):
        return dict(state)

    async def dispose():
        pass

    runtime = ApplicationRuntime(
        real_model_runtime=SimpleNamespace(check_readiness=readiness),
        database_runtime=SimpleNamespace(session_factory=None, dispose=dispose),
        identity_service=object(),
    )
    app = create_app(runtime=runtime)
    with TestClient(app) as client:
        assert client.get("/api/v1/model-runtime/readiness").status_code == 401
        app.dependency_overrides[current_user_dependency] = _user
        assert client.get("/api/v1/model-runtime/readiness").status_code == 200
        state["ready"] = False
        assert client.get("/api/v1/model-runtime/readiness").status_code == 503
        assert client.get("/api/v1/health").status_code == 200


@pytest.mark.parametrize(
    "value,accepted",
    [
        ("1.8.0", True),
        ("1.7.6", True),
        ("1.9.3", True),
        ("1.6.0", False),
        ("0.7.3", False),
        ("2.0.0", False),
        ("1.8", False),
        (None, False),
    ],
)
def test_compatible_schema_decoder_versions(value, accepted):
    from orchestwin.models.real_runtime import _compatible_schema_decoder

    assert _compatible_schema_decoder(value) is accepted
