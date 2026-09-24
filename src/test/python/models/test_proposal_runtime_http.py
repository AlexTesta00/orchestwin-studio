"""Local HTTP boundary tests with a synthetic server; no model inference."""

import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.services import ApplicationRuntime
from orchestwin.models.proposal_generation import (
    DirectProposalTransport,
    ProposalGenerationError,
)

from .test_model_proposals import make_generator


@pytest.mark.parametrize(
    "stage,adapter",
    [
        ("team", "ModelTeamProposalAdapter"),
        ("user_modeling", "ModelUserModelingAdapter"),
        ("requirements", "ModelRequirementsAdapter"),
        ("design", "ModelDesignAdapter"),
    ],
)
def test_each_application_factory_resolves_explicit_model_config(tmp_path, stage, adapter):
    generator, _ = make_generator(tmp_path, {})
    config = generator.configuration
    config.token_file.write_text("t" * 48, encoding="ascii")
    path = tmp_path / "runtime.json"
    path.write_text(config.model_dump_json(), encoding="utf-8")
    module = importlib.import_module(
        f"orchestwin.models.{'runtime' if stage == 'team' else stage + '_runtime'}"
    )
    prefix = (
        "TeamProposal" if stage == "team" else "".join(word.title() for word in stage.split("_"))
    )
    options = {"model_config_file": path}
    options.update(
        {"provider": "MODEL_ADAPTER", "_env_file": None}
        if stage == "team"
        else {"mode": "MODEL_ADAPTER"}
    )
    settings = getattr(module, prefix + "RuntimeSettings")(**options)
    factory = getattr(
        module, "create_team_proposal_port" if stage == "team" else f"build_{stage}_proposal_port"
    )
    port = factory(settings)
    assert type(port).__name__ == adapter
    assert port.generator.configuration.identity == config.identity


def test_direct_http_does_not_follow_redirects_or_use_environment_proxy(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", "/should-never-be-called")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        from orchestwin.models.openai_compatible import OpenAICompatibleTransportError

        with pytest.raises(OpenAICompatibleTransportError):
            asyncio.run(
                DirectProposalTransport().post_json(
                    url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    payload={},
                    headers={"Authorization": "Bearer test-token"},
                    timeout_seconds=2,
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert requests == [("/v1/chat/completions", "Bearer test-token")]


@pytest.mark.parametrize(
    "code,status",
    [("TIMEOUT", 503), ("INVALID_PROVIDER_OUTPUT", 502), ("CONTEXT_BUDGET_EXCEEDED", 422)],
)
def test_api_maps_model_failure_without_exposing_prompts(code, status):
    app = create_app(runtime=ApplicationRuntime())

    @app.get("/test-model-failure")
    def fail():
        raise ProposalGenerationError(code, request={"private": "secret-prompt"})

    with TestClient(app) as client:
        response = client.get("/test-model-failure")
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "stage": "MODEL_PROPOSAL"}}
    assert "secret-prompt" not in json.dumps(response.json())
