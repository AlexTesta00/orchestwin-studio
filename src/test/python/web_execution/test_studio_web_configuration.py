"""Local Web configuration selects real runners without executing or promoting them."""

import json

import pytest

from orchestwin.api.governed_web_context import (
    CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY,
    GovernedWebSettings,
)
from scripts import studio_runtime


def network():
    return {
        "name": "qualification-internal",
        "network_id": "a" * 64,
        "policy_hash": CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY.content_hash,
        "proxy_host": "restricted-proxy",
        "proxy_port": 3128,
    }


def write_configuration(tmp_path, **changes):
    values = {
        "enabled": True,
        "runner_manifest": str(tmp_path / "runner-manifest.json"),
        "workspaces_root": str(tmp_path / "workspaces"),
        **changes,
    }
    path = tmp_path / "web.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_absent_optional_configuration_disables_web_and_clears_stale_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    environment = {
        "ORCHESTWIN_GOVERNED_WEB_ENABLED": "true",
        "ORCHESTWIN_GOVERNED_WEB_RUNNER_MANIFEST": str(tmp_path / "old.json"),
        "ORCHESTWIN_GOVERNED_WEB_WORKSPACES_ROOT": str(tmp_path / "old-work"),
        "ORCHESTWIN_GOVERNED_WEB_CONTROLLED_NETWORK": json.dumps(network()),
        "ORCHESTWIN_MODEL_RUNTIME_CONFIG_FILE": "existing-model.json",
    }
    monkeypatch.setattr(studio_runtime.os, "environ", environment)

    studio_runtime.configure_web()

    settings = GovernedWebSettings(_env_file=None)
    assert not settings.enabled
    assert settings.repo_root == tmp_path
    assert (
        settings.runner_manifest is settings.workspaces_root is settings.controlled_network is None
    )
    assert environment["ORCHESTWIN_MODEL_RUNTIME_CONFIG_FILE"] == "existing-model.json"
    assert "ORCHESTWIN_GOVERNED_WEB_CONTROLLED_NETWORK" not in environment


def test_controlled_network_round_trips_through_the_actual_environment_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(studio_runtime.os, "environ", {})
    path = write_configuration(tmp_path, controlled_network=network())

    studio_runtime.configure_web(path)

    settings = GovernedWebSettings(_env_file=None)
    assert settings.enabled
    assert settings.repo_root == tmp_path
    assert settings.runner_manifest == tmp_path / "runner-manifest.json"
    assert settings.workspaces_root == tmp_path / "workspaces"
    assert settings.controlled_network.network_id == network()["network_id"]
    assert settings.controlled_network.proxy_port == 3128
    assert (
        json.loads(studio_runtime.os.environ["ORCHESTWIN_GOVERNED_WEB_CONTROLLED_NETWORK"])
        == network()
    )


def test_explicit_null_network_removes_an_inherited_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(
        studio_runtime.os,
        "environ",
        {"ORCHESTWIN_GOVERNED_WEB_CONTROLLED_NETWORK": json.dumps(network())},
    )
    studio_runtime.configure_web(write_configuration(tmp_path, controlled_network=None))

    settings = GovernedWebSettings(_env_file=None)
    assert settings.enabled and settings.controlled_network is None
    assert "ORCHESTWIN_GOVERNED_WEB_CONTROLLED_NETWORK" not in studio_runtime.os.environ


@pytest.mark.parametrize("payload", [{"unknown_setting": "value"}, [], {"enabled": True}])
def test_invalid_configuration_cannot_partially_replace_environment(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    original = {"ORCHESTWIN_GOVERNED_WEB_ENABLED": "true"}
    monkeypatch.setattr(studio_runtime.os, "environ", original.copy())
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        studio_runtime.configure_web(path)

    assert studio_runtime.os.environ == original


def test_missing_explicit_configuration_fails_without_disabling_the_running_selection(
    tmp_path, monkeypatch
):
    original = {"ORCHESTWIN_GOVERNED_WEB_ENABLED": "true"}
    monkeypatch.setattr(studio_runtime.os, "environ", original.copy())
    with pytest.raises(ValueError, match="WEB_RUNTIME_CONFIGURATION_NOT_FOUND"):
        studio_runtime.configure_web(tmp_path / "missing.json")
    assert studio_runtime.os.environ == original


def test_native_launcher_loads_web_alongside_the_selected_real_models(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(studio_runtime.os, "environ", {})
    monkeypatch.setattr(
        studio_runtime,
        "dotenv_values",
        lambda path: {
            "ORCHESTWIN_POSTGRES_PASSWORD": "test-only-password",
            "ORCHESTWIN_AUTH_JWT_SECRET": "test-only-secret",
        },
    )
    models = tmp_path / "models.json"
    web = write_configuration(tmp_path, controlled_network=None)

    studio_runtime.configure(models, web)

    assert GovernedWebSettings(_env_file=None).enabled
    assert studio_runtime.os.environ["ORCHESTWIN_MODEL_RUNTIME_MODE"] == "REAL_REQUIRED"
    assert studio_runtime.os.environ["ORCHESTWIN_MODEL_RUNTIME_CONFIG_FILE"] == str(
        models.resolve()
    )
