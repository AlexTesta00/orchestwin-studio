from __future__ import annotations

import contextlib
import json
import os
import secrets
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import CliError
from orchestwin.cli.http import is_loopback
from orchestwin.cli.project import json_bytes, write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.environment import Environment

DEFAULT_STUDIO: Final = "http://127.0.0.1:8000"
DEFAULT_API_PREFIX: Final = "/api/v1"
DEFAULT_COOKIE: Final = "orchestwin_refresh"
CONFIG_VARIABLE: Final = "ORCHESTWIN_CONFIG_DIR"
CONFIG_NAME: Final = "orchestwin"
SESSIONS_FILE: Final = "sessions.json"
UNREADABLE_FILE: Final = "sessions.unreadable.json"
LOCK_FILE: Final = "sessions.lock"
SCHEMA_VERSION: Final = 1
LOCK_WAIT_SECONDS: Final = 10.0
LOCK_POLL_SECONDS: Final = 0.05
LOCK_STALE_SECONDS: Final = 30.0
FOLDER_PERMISSIONS: Final = 0o700
FILE_PERMISSIONS: Final = 0o600
LOCK_FLAGS: Final = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
DEFAULT_PORTS: Final = {"http": 80, "https": 443}


@dataclass(frozen=True, slots=True)
class StudioAddress:
    origin: str
    api_prefix: str = DEFAULT_API_PREFIX

    def url(self, path: str) -> str:
        return f"{self.origin}{self.api_prefix}{path}"

    @classmethod
    def parse(cls, value: str) -> StudioAddress:
        text = value.strip() if isinstance(value, str) else ""
        invalid = CliError("STUDIO_ADDRESS_INVALID", values={"address": text or str(value)})
        try:
            parts = urllib.parse.urlsplit(text)
            port = parts.port
        except ValueError:
            raise invalid from None
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        if (
            scheme not in DEFAULT_PORTS
            or not host
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise invalid
        prefix = _api_prefix(parts.path)
        if prefix is None:
            raise invalid
        if scheme == "http" and not is_loopback(host):
            raise CliError("STUDIO_NOT_SECURE", values={"address": text})
        shown = f"[{host}]" if ":" in host else host
        if port is not None and port != DEFAULT_PORTS[scheme]:
            shown = f"{shown}:{port}"
        return cls(origin=f"{scheme}://{shown}", api_prefix=prefix)


def _api_prefix(path: str) -> str | None:
    cleaned = path.rstrip("/")
    if not cleaned:
        return DEFAULT_API_PREFIX
    if cleaned.endswith(DEFAULT_API_PREFIX) and "//" not in cleaned:
        return cleaned
    return None


@dataclass(frozen=True, slots=True)
class StudioSession:
    email: str
    cookie_name: str = DEFAULT_COOKIE
    refresh_token: str | None = field(default=None, repr=False)
    access_token: str | None = field(default=None, repr=False)
    access_expires_at: datetime | None = None
    saved_at: datetime | None = None
    api_prefix: str = DEFAULT_API_PREFIX

    @property
    def signed_in(self) -> bool:
        return bool(self.refresh_token) or bool(self.access_token)

    def without_tokens(self) -> StudioSession:
        return replace(self, refresh_token=None, access_token=None, access_expires_at=None)


def config_folder(environment: Environment) -> Path:
    variables = environment.variables
    override = variables.get(CONFIG_VARIABLE, "").strip()
    if override:
        return Path(override)
    if environment.platform == "win32":
        roaming = variables.get("APPDATA", "").strip()
        base = Path(roaming) if roaming else environment.home / "AppData" / "Roaming"
    elif environment.platform == "darwin":
        base = environment.home / "Library" / "Application Support"
    else:
        configured = variables.get("XDG_CONFIG_HOME", "").strip()
        base = (
            Path(configured)
            if configured and Path(configured).is_absolute()
            else environment.home / ".config"
        )
    return base / CONFIG_NAME


class SessionStore:
    def __init__(self, environment: Environment) -> None:
        self._environment = environment
        self._folder = config_folder(environment)
        self._depth = 0

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def path(self) -> Path:
        return self._folder / SESSIONS_FILE

    def read(self, studio: StudioAddress) -> StudioSession | None:
        document = self._document()
        if document is None:
            return None
        return session_from(document["sessions"].get(studio.origin))

    def default_studio(self) -> StudioAddress | None:
        document = self._document()
        if document is None or not isinstance(document.get("default_studio"), str):
            return None
        try:
            address = StudioAddress.parse(document["default_studio"])
        except CliError:
            return None
        session = session_from(document["sessions"].get(address.origin))
        return address if session is None else replace(address, api_prefix=session.api_prefix)

    def save(
        self,
        studio: StudioAddress,
        session: StudioSession,
        *,
        make_default: bool = False,
    ) -> None:
        with self.locked():
            document = self._document()
            if document is None:
                self._set_aside()
                document = {
                    "schema_version": SCHEMA_VERSION,
                    "default_studio": None,
                    "sessions": {},
                }
            document["sessions"][studio.origin] = session_entry(
                replace(session, api_prefix=studio.api_prefix)
            )
            if make_default:
                document["default_studio"] = studio.origin
            self._write(document)

    def forget(self, studio: StudioAddress) -> None:
        with self.locked():
            document = self._document()
            if document is None or studio.origin not in document["sessions"]:
                return
            del document["sessions"][studio.origin]
            self._write(document)

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        token = self._acquire()
        self._depth = 1
        try:
            yield
        finally:
            self._depth = 0
            self._release(token)

    def _document(self) -> dict | None:
        try:
            document = json.loads(self.path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RecursionError):
            return None
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != SCHEMA_VERSION
            or not isinstance(document.get("sessions"), dict)
            or not all(isinstance(key, str) for key in document["sessions"])
        ):
            return None
        default = document.get("default_studio")
        if default is not None and not isinstance(default, str):
            return None
        return {
            "schema_version": SCHEMA_VERSION,
            "default_studio": default,
            "sessions": dict(document["sessions"]),
        }

    def _set_aside(self) -> None:
        if self.path.exists():
            with contextlib.suppress(OSError):
                os.replace(self.path, self._folder / UNREADABLE_FILE)

    def _write(self, document: dict) -> None:
        self._prepare_folder()
        permissions = None if self._environment.platform == "win32" else FILE_PERMISSIONS
        write_atomically(self.path, json_bytes(document), permissions=permissions)

    def _prepare_folder(self) -> None:
        self._folder.mkdir(parents=True, exist_ok=True, mode=FOLDER_PERMISSIONS)
        if self._environment.platform != "win32":
            with contextlib.suppress(OSError):
                os.chmod(self._folder, FOLDER_PERMISSIONS)

    def _acquire(self) -> str:
        environment = self._environment
        self._prepare_folder()
        lock = self._folder / LOCK_FILE
        stamp = environment.now().astimezone(UTC).isoformat(timespec="seconds")
        token = f"{os.getpid()}\n{stamp}\n{secrets.token_hex(8)}\n"
        deadline = environment.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                descriptor = os.open(lock, LOCK_FLAGS, FILE_PERMISSIONS)
            except (FileExistsError, PermissionError):
                pass
            else:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(token.encode("utf-8"))
                return token
            if self._stale(lock) and _removed(lock):
                continue
            if environment.monotonic() >= deadline:
                raise CliError("SESSION_FILE_LOCKED", values={"path": str(lock)})
            environment.sleep(LOCK_POLL_SECONDS)

    def _stale(self, lock: Path) -> bool:
        created = _lock_time(lock)
        if created is None:
            return False
        age = self._environment.now().astimezone(UTC) - created
        return age.total_seconds() > LOCK_STALE_SECONDS

    def _release(self, token: str) -> None:
        lock = self._folder / LOCK_FILE
        try:
            current = lock.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if current == token:
            _removed(lock)


def _lock_time(lock: Path) -> datetime | None:
    try:
        content = lock.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        content = ""
    lines = content.splitlines()
    if len(lines) >= 2:
        with contextlib.suppress(ValueError):
            moment = datetime.fromisoformat(lines[1].strip())
            if moment.tzinfo is not None:
                return moment.astimezone(UTC)
    try:
        return datetime.fromtimestamp(lock.stat().st_mtime, UTC)
    except OSError:
        return None


def _removed(lock: Path) -> bool:
    try:
        lock.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def session_entry(session: StudioSession) -> dict[str, object]:
    return {
        "api_prefix": session.api_prefix,
        "email": session.email,
        "cookie_name": session.cookie_name,
        "refresh_token": session.refresh_token,
        "access_token": session.access_token,
        "access_expires_at": _moment_text(session.access_expires_at),
        "saved_at": _moment_text(session.saved_at),
    }


def session_from(entry: object) -> StudioSession | None:
    if not isinstance(entry, dict):
        return None
    email = entry.get("email")
    cookie = entry.get("cookie_name", DEFAULT_COOKIE)
    prefix = entry.get("api_prefix", DEFAULT_API_PREFIX)
    refresh = entry.get("refresh_token")
    access = entry.get("access_token")
    if not isinstance(email, str) or not isinstance(cookie, str) or not cookie:
        return None
    if not isinstance(prefix, str) or not all(
        token is None or isinstance(token, str) for token in (refresh, access)
    ):
        return None
    expires = parse_moment(entry.get("access_expires_at"))
    saved = parse_moment(entry.get("saved_at"))
    if (entry.get("access_expires_at") is not None and expires is None) or (
        entry.get("saved_at") is not None and saved is None
    ):
        return None
    return StudioSession(
        email=email,
        cookie_name=cookie,
        refresh_token=refresh or None,
        access_token=access or None,
        access_expires_at=expires,
        saved_at=saved,
        api_prefix=prefix,
    )


def parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.astimezone(UTC)


def _moment_text(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds")
