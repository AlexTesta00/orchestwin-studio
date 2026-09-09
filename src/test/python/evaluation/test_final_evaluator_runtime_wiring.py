from __future__ import annotations

import ast
from pathlib import Path

from orchestwin.evaluation.field_scope_prompt import FIELD_SCOPE_PROMPT_VERSION
from orchestwin.evaluation.final_runtime import (
    FinalEvaluatorSettings,
    build_final_evaluator_runtime,
)

from ..models.final_session_support import make_session


def test_disabled_factory_does_not_read_session_or_generate(monkeypatch):
    def forbidden(_path):
        raise AssertionError("disabled configuration must not read session files")

    monkeypatch.setattr("orchestwin.evaluation.final_runtime.load_final_session", forbidden)
    assert (
        build_final_evaluator_runtime(FinalEvaluatorSettings(enabled=False, _env_file=None)) is None
    )


def test_enabled_factory_returns_new_evaluator_per_call(tmp_path):
    session = make_session(tmp_path)
    runtime = build_final_evaluator_runtime(
        FinalEvaluatorSettings(enabled=True, ready_file=session.ready_path, _env_file=None)
    )
    first, second = runtime.create_evaluator(), runtime.create_evaluator()
    assert first is not second
    assert first.traces is not second.traces
    assert first.configuration.prompt_version_ref == FIELD_SCOPE_PROMPT_VERSION
    assert first.configuration.model_config_ref == first._model_identity.content_hash
    assert first._max_output_tokens == 1024
    assert first._timeout_seconds == 90


def test_application_factory_and_app_state_are_connected():
    # This structural test complements, not replaces, the runtime check on the live repository.
    services = ast.parse(Path("src/orchestwin/api/services.py").read_text())
    app = ast.parse(Path("src/orchestwin/api/app.py").read_text())
    calls = [node for node in ast.walk(services) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "build_final_evaluator_runtime"
        for call in calls
    )
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "ApplicationRuntime"
        and any(item.arg == "final_evaluator_runtime" for item in call.keywords)
        for call in calls
    )
    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "final_evaluator_runtime"
            for target in node.targets
        )
        for node in ast.walk(app)
    )


def test_app_retains_explicit_evaluator_runtime_without_generation(tmp_path, monkeypatch):
    import os

    from orchestwin.api.app import create_app
    from orchestwin.api.auth import AuthApiSettings
    from orchestwin.api.services import ApplicationRuntime
    from orchestwin.config import ApplicationSettings

    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)
    session = make_session(tmp_path)
    factory = build_final_evaluator_runtime(
        FinalEvaluatorSettings(enabled=True, ready_file=session.ready_path, _env_file=None)
    )
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(final_evaluator_runtime=factory),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    assert app.state.final_evaluator_runtime is factory
