from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli import project as project_module
from orchestwin.cli.errors import CliError
from orchestwin.cli.session import (
    LOCK_FILE,
    SessionStore,
    StudioAddress,
    StudioSession,
    config_folder,
)

from .support.terminal import (
    START,
    TEST_ACCESS_TOKEN,
    TEST_EMAIL,
    TEST_REFRESH_TOKEN,
    Terminal,
    terminal,
)
from .support.transports import NoNetwork

LOCAL = StudioAddress.parse("http://127.0.0.1:8000")
OTHER = StudioAddress.parse("https://studio.example.test")


def bundle_for(tmp_path: Path, **options: object) -> Terminal:
    return terminal(tmp_path, transport=NoNetwork(), **options)


def session(**changes: object) -> StudioSession:
    base = StudioSession(
        email=TEST_EMAIL,
        refresh_token=TEST_REFRESH_TOKEN,
        access_token=TEST_ACCESS_TOKEN,
        access_expires_at=START + timedelta(minutes=15),
        saved_at=START,
    )
    return replace(base, **changes)


def test_the_configuration_folder_follows_the_variable_first(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen"
    bundle = bundle_for(tmp_path, variables={"ORCHESTWIN_CONFIG_DIR": str(chosen)})

    assert config_folder(bundle.environment) == chosen
    assert SessionStore(bundle.environment).folder == chosen


@pytest.mark.parametrize(
    ("platform", "variables", "parts"),
    [
        ("win32", {"APPDATA": "appdata"}, ("appdata", "orchestwin")),
        ("win32", {}, ("home", "AppData", "Roaming", "orchestwin")),
        ("darwin", {}, ("home", "Library", "Application Support", "orchestwin")),
        ("linux", {"XDG_CONFIG_HOME": "xdg"}, ("xdg", "orchestwin")),
        ("linux", {}, ("home", ".config", "orchestwin")),
    ],
)
def test_the_configuration_folder_by_platform(
    tmp_path: Path, platform: str, variables: dict[str, str], parts: tuple[str, ...]
) -> None:
    absolute = {name: str(tmp_path / value) for name, value in variables.items()}
    bundle = bundle_for(tmp_path, platform=platform, variables=absolute)
    chosen = dict(bundle.environment.variables)
    del chosen["ORCHESTWIN_CONFIG_DIR"]

    folder = config_folder(replace(bundle.environment, variables=chosen))

    assert folder == tmp_path.joinpath(*parts)


def test_a_relative_xdg_folder_is_ignored(tmp_path: Path) -> None:
    bundle = bundle_for(tmp_path, variables={"XDG_CONFIG_HOME": "relative"})
    chosen = {"XDG_CONFIG_HOME": "relative"}

    folder = config_folder(replace(bundle.environment, variables=chosen))

    assert folder == tmp_path / "home" / ".config" / "orchestwin"


@pytest.mark.parametrize(
    ("value", "origin", "prefix"),
    [
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000", "/api/v1"),
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000", "/api/v1"),
        ("http://127.0.0.1:8000/api/v1", "http://127.0.0.1:8000", "/api/v1"),
        (" http://127.0.0.1:8000/api/v1/ ", "http://127.0.0.1:8000", "/api/v1"),
        ("HTTP://LocalHost:9000", "http://localhost:9000", "/api/v1"),
        ("http://studio.localhost", "http://studio.localhost", "/api/v1"),
        ("http://[::1]:8000", "http://[::1]:8000", "/api/v1"),
        (
            "https://studio.example.test:443/team/api/v1",
            "https://studio.example.test",
            "/team/api/v1",
        ),
        ("https://studio.example.test:8443", "https://studio.example.test:8443", "/api/v1"),
    ],
)
def test_addresses_of_the_studio_that_are_accepted(value: str, origin: str, prefix: str) -> None:
    address = StudioAddress.parse(value)

    assert (address.origin, address.api_prefix) == (origin, prefix)
    assert address.url("/health") == f"{origin}{prefix}/health"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "127.0.0.1:8000",
        "ftp://127.0.0.1",
        "http://",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:8000/other",
        "http://user:secret@127.0.0.1:8000",
        "http://127.0.0.1:8000/?next=1",
    ],
)
def test_addresses_that_are_not_valid(value: str) -> None:
    with pytest.raises(CliError) as caught:
        StudioAddress.parse(value)

    assert caught.value.code == "STUDIO_ADDRESS_INVALID"
    assert caught.value.status == 2


def test_plain_http_towards_another_computer_is_refused() -> None:
    with pytest.raises(CliError) as caught:
        StudioAddress.parse("http://studio.example.test")

    assert caught.value.code == "STUDIO_NOT_SECURE"
    assert caught.value.status == 2
    assert caught.value.values["address"] == "http://studio.example.test"


def test_a_session_is_saved_read_and_made_default(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)

    store.save(LOCAL, session(), make_default=True)
    store.save(OTHER, session(email="other@example.test"))

    assert store.read(LOCAL) == session()
    assert store.read(OTHER) == session(email="other@example.test")
    assert store.default_studio() == LOCAL
    document = json.loads(store.path.read_text(encoding="utf-8"))
    assert list(document) == ["schema_version", "default_studio", "sessions"]
    assert document["schema_version"] == 1
    assert document["default_studio"] == "http://127.0.0.1:8000"
    assert document["sessions"]["http://127.0.0.1:8000"] == {
        "api_prefix": "/api/v1",
        "email": TEST_EMAIL,
        "cookie_name": "orchestwin_refresh",
        "refresh_token": TEST_REFRESH_TOKEN,
        "access_token": TEST_ACCESS_TOKEN,
        "access_expires_at": "2026-09-29T09:15:00+00:00",
        "saved_at": "2026-09-29T09:00:00+00:00",
    }
    assert sorted(path.name for path in store.folder.iterdir()) == ["sessions.json"]


def test_forget_removes_only_that_studio(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)
    store.save(LOCAL, session(), make_default=True)
    store.save(OTHER, session())

    store.forget(LOCAL)
    store.forget(StudioAddress.parse("http://127.0.0.1:9"))

    assert store.read(LOCAL) is None
    assert store.read(OTHER) == session()


def test_nothing_is_signed_in_without_a_file(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)

    assert store.read(LOCAL) is None
    assert store.default_studio() is None
    store.forget(LOCAL)
    assert not store.path.exists()


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"[]",
        b'{"schema_version": 2, "sessions": {}}',
        b'{"schema_version": 1, "sessions": []}',
        b'{"schema_version": 1, "default_studio": 3, "sessions": {}}',
        b"\xff\xfe",
    ],
)
def test_a_broken_file_counts_as_signed_out_and_is_not_deleted(
    tmp_path: Path, content: bytes
) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)
    store.folder.mkdir(parents=True)
    store.path.write_bytes(content)

    assert store.read(LOCAL) is None
    assert store.default_studio() is None
    assert store.path.read_bytes() == content

    store.save(LOCAL, session())

    assert store.read(LOCAL) == session()
    assert (store.folder / "sessions.unreadable.json").read_bytes() == content


def test_a_broken_entry_counts_as_signed_out(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)
    store.save(LOCAL, session())
    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["sessions"]["http://127.0.0.1:8000"]["access_expires_at"] = "yesterday"
    store.path.write_text(json.dumps(document), encoding="utf-8")

    assert store.read(LOCAL) is None


def test_the_write_is_atomic_and_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)
    store.save(LOCAL, session())
    before = store.path.read_bytes()

    def refuse(source: object, target: object) -> None:
        raise PermissionError(13, "refused", str(target))

    monkeypatch.setattr(project_module.os, "replace", refuse)
    with pytest.raises(PermissionError):
        store.save(LOCAL, session(email="changed@example.test"))

    assert store.path.read_bytes() == before
    assert sorted(path.name for path in store.folder.iterdir()) == ["sessions.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX permissions")
def test_the_folder_and_the_file_are_private(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)

    store.save(LOCAL, session())

    assert stat.S_IMODE(os.stat(store.folder).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_no_token_appears_in_the_representation() -> None:
    shown = [repr(session()), str(session())]

    assert all(TEST_ACCESS_TOKEN not in text for text in shown)
    assert all(TEST_REFRESH_TOKEN not in text for text in shown)
    assert TEST_EMAIL in shown[0]


def test_a_session_without_tokens_is_not_signed_in() -> None:
    assert session().signed_in
    assert not session().without_tokens().signed_in
    assert session(refresh_token=None).signed_in


def test_the_lock_writes_the_process_and_the_time_and_is_released(tmp_path: Path) -> None:
    store = SessionStore(bundle_for(tmp_path).environment)
    lock = store.folder / LOCK_FILE

    with store.locked():
        lines = lock.read_text(encoding="utf-8").splitlines()
        with store.locked():
            assert lock.exists()

    assert lines[0] == str(os.getpid())
    assert lines[1] == "2026-09-29T09:00:00+00:00"
    assert not lock.exists()


def test_the_lock_waits_for_another_command(tmp_path: Path) -> None:
    bundle = bundle_for(tmp_path)
    store = SessionStore(bundle.environment)
    store.folder.mkdir(parents=True)
    lock = store.folder / LOCK_FILE
    lock.write_text("4242\n2026-09-29T09:00:00+00:00\nother\n", encoding="utf-8")
    calls = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        bundle.clock.sleep(seconds)
        if len(calls) == 3:
            lock.unlink()

    waiting = SessionStore(replace(bundle.environment, sleep=sleep))
    with waiting.locked():
        assert "4242" not in lock.read_text(encoding="utf-8")

    assert calls == [0.05, 0.05, 0.05]
    assert not lock.exists()


def test_a_stale_lock_is_removed(tmp_path: Path) -> None:
    bundle = bundle_for(tmp_path)
    store = SessionStore(bundle.environment)
    store.folder.mkdir(parents=True)
    lock = store.folder / LOCK_FILE
    lock.write_text("4242\n2026-09-29T08:59:29+00:00\nother\n", encoding="utf-8")

    with store.locked():
        assert lock.read_text(encoding="utf-8").startswith(f"{os.getpid()}\n")

    assert bundle.clock.slept == 0
    assert not lock.exists()


def test_the_lock_gives_up_after_ten_seconds(tmp_path: Path) -> None:
    bundle = bundle_for(tmp_path)
    store = SessionStore(bundle.environment)
    store.folder.mkdir(parents=True)
    lock = store.folder / LOCK_FILE
    lock.write_text("4242\n2026-09-29T09:00:00+00:00\nother\n", encoding="utf-8")

    with pytest.raises(CliError) as caught, store.locked():
        pytest.fail("the lock of another command was taken")

    assert caught.value.code == "SESSION_FILE_LOCKED"
    assert caught.value.values["path"] == str(lock)
    assert bundle.clock.slept == pytest.approx(10.0, abs=0.06)
    assert lock.read_text(encoding="utf-8").startswith("4242\n")
