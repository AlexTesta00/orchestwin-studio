import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "studio_runtime.py"
CREDENTIALS = {
    "ORCHESTWIN_POSTGRES_PASSWORD": "database-password-for-tests",
    "ORCHESTWIN_AUTH_JWT_SECRET": "jwt-secret-for-tests",
}
ALWAYS_WRITTEN = {
    "ORCHESTWIN_DATABASE_URL",
    "ORCHESTWIN_AUTH_JWT_SECRET",
    "ORCHESTWIN_CORS_ALLOWED_ORIGINS",
    "ORCHESTWIN_ACCESS_MODE",
}
LOCAL_API = [
    "api",
    "--models",
    "models.json",
    "--access",
    "local",
    "--local-owner",
    "owner@example.com",
]


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("studio_runtime_access41", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def environment(runtime: ModuleType, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    written: dict[str, str] = {}
    monkeypatch.setattr(runtime, "dotenv_values", lambda path: dict(CREDENTIALS))
    monkeypatch.setattr(runtime, "os", SimpleNamespace(environ=written))
    return written


def test_the_parser_takes_the_local_access_and_its_owner(runtime: ModuleType) -> None:
    arguments = runtime.parse_arguments(LOCAL_API)

    assert (arguments.action, arguments.models) == ("api", Path("models.json"))
    assert (arguments.access, arguments.local_owner) == ("local", "owner@example.com")


@pytest.mark.parametrize(
    "arguments",
    [
        ["api", "--models", "models.json"],
        ["check", "--models", "models.json", "--access", "accounts"],
        ["migrate"],
    ],
)
def test_the_parser_keeps_accounts_by_default(runtime: ModuleType, arguments: list[str]) -> None:
    parsed = runtime.parse_arguments(arguments)

    assert (parsed.access, parsed.local_owner) == ("accounts", None)


def test_local_access_without_an_owner_is_accepted(runtime: ModuleType) -> None:
    parsed = runtime.parse_arguments(["check", "--models", "models.json", "--access", "local"])

    assert (parsed.access, parsed.local_owner) == ("local", None)


@pytest.mark.parametrize(
    "arguments",
    [
        ["api", "--models", "models.json", "--local-owner", "owner@example.com"],
        [
            "api",
            "--models",
            "models.json",
            "--access",
            "accounts",
            "--local-owner",
            "owner@example.com",
        ],
        ["migrate", "--local-owner", "owner@example.com"],
    ],
)
def test_the_parser_refuses_an_owner_without_local_access(
    runtime: ModuleType,
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        runtime.parse_arguments(arguments)

    assert stopped.value.code == 2
    assert "--local-owner requires --access local" in capsys.readouterr().err


@pytest.mark.parametrize("access", ["open", "LOCAL", "LOCAL_OWNER"])
def test_the_parser_refuses_an_unknown_access(
    runtime: ModuleType,
    access: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        runtime.parse_arguments(["api", "--models", "models.json", "--access", access])

    assert stopped.value.code == 2
    assert "--access" in capsys.readouterr().err


def test_local_access_writes_the_mode_and_the_owner(
    runtime: ModuleType,
    environment: dict[str, str],
) -> None:
    runtime.configure(None, "local", "owner@example.com")

    assert set(environment) == ALWAYS_WRITTEN | {"ORCHESTWIN_LOCAL_OWNER_EMAIL"}
    assert environment["ORCHESTWIN_ACCESS_MODE"] == "LOCAL_OWNER"
    assert environment["ORCHESTWIN_LOCAL_OWNER_EMAIL"] == "owner@example.com"


def test_local_access_without_an_owner_writes_only_the_mode(
    runtime: ModuleType,
    environment: dict[str, str],
) -> None:
    runtime.configure(None, "local")

    assert set(environment) == ALWAYS_WRITTEN
    assert environment["ORCHESTWIN_ACCESS_MODE"] == "LOCAL_OWNER"


def test_accounts_access_writes_no_local_owner(
    runtime: ModuleType,
    environment: dict[str, str],
) -> None:
    runtime.configure(None)
    default = dict(environment)
    environment.clear()
    runtime.configure(None, "accounts")

    assert environment == default
    assert set(environment) == ALWAYS_WRITTEN
    assert environment["ORCHESTWIN_ACCESS_MODE"] == "ACCOUNTS"


def test_the_api_starts_with_the_access_options(
    runtime: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(runtime, "configure", lambda *arguments: calls.append(arguments))
    monkeypatch.setattr(os, "chdir", lambda path: calls.append(path))
    monkeypatch.setattr("orchestwin.api.server.main", lambda arguments: calls.append(arguments))
    monkeypatch.setattr(sys, "argv", ["studio_runtime.py", *LOCAL_API])

    runtime.main()

    assert calls == [
        runtime.ROOT,
        (Path("models.json"), "local", "owner@example.com"),
        [],
    ]
