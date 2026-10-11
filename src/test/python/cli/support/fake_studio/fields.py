from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.knowledge.state import FILE_KINDS, MAX_FILES, MAX_PATH_LENGTH

from .common import _changed_path, _error, _lax_boolean
from .values import _Invalid, _Refusal

if TYPE_CHECKING:
    from .values import _Account


HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


class _Sentinel:
    pass


NO_BODY = _Sentinel()
NOT_JSON = _Sentinel()


@dataclass(slots=True)
class _Call:
    method: str
    path: str
    user: _Account | None
    params: dict[str, str]
    query: dict[str, list[str]]
    headers: dict[str, str]
    raw: bytes
    prefer_async: bool

    @property
    def project_id(self) -> str:
        return self.params["project_id"]

    @property
    def account(self) -> _Account:
        if self.user is None:
            raise _Refusal(401, "invalid_authentication", {"WWW-Authenticate": "Bearer"})
        return self.user

    def json(self) -> object:
        if not self.raw:
            return NO_BODY
        content_type = self.headers.get("content-type")
        if content_type is not None and not _json_media_type(content_type):
            return NOT_JSON
        try:
            return json.loads(self.raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise _Invalid([_error(("body", 0), "json_invalid")]) from error

    def value(self, name: str) -> str | None:
        values = self.query.get(name)
        return values[0] if values else None

    def cookie(self, name: str) -> str:
        header = self.headers.get("cookie")
        if not header:
            return ""
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(header)
        except CookieError:
            return ""
        morsel = jar.get(name)
        return "" if morsel is None else morsel.value


class _Fields:
    def __init__(
        self,
        body: object,
        allowed: Sequence[str],
        *,
        optional: bool = False,
        location: Sequence[object] = ("body",),
    ) -> None:
        self.errors: list[dict[str, object]] = []
        self.absent = False
        self.location = tuple(location)
        if body is NO_BODY or body is None:
            self.absent = True
            if not optional:
                self.errors.append(_error(self.location, "missing"))
            body = {}
        elif body is NOT_JSON or not isinstance(body, dict):
            self.absent = True
            self.errors.append(_error(self.location, "model_attributes_type"))
            body = {}
        self.body: dict[str, object] = body
        self.errors.extend(
            _error((*self.location, name), "extra_forbidden")
            for name in body
            if name not in allowed
        )

    def _get(self, name: str, required: bool) -> tuple[bool, object]:
        if self.absent or name not in self.body:
            if required and not self.absent:
                self.errors.append(_error((*self.location, name), "missing"))
            return False, None
        return True, self.body[name]

    def _fail(self, name: str, kind: str) -> None:
        self.errors.append(_error((*self.location, name), kind))

    def text(
        self,
        name: str,
        *,
        required: bool = True,
        minimum: int = 0,
        maximum: int | None = None,
        nullable: bool = False,
        default: str | None = None,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            self._fail(name, "string_type")
            return default
        if len(value) < minimum:
            self._fail(name, "string_too_short")
            return default
        if maximum is not None and len(value) > maximum:
            self._fail(name, "string_too_long")
            return default
        return value

    def choice(
        self,
        name: str,
        options: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
        literal: bool = False,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if value is None and nullable:
            return None
        if not isinstance(value, str) or value not in options:
            self._fail(name, "literal_error" if literal else "enum")
            return None
        return value

    def integer(
        self,
        name: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
        required: bool = True,
    ) -> int | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail(name, "int_type")
            return None
        if minimum is not None and value < minimum:
            self._fail(name, "greater_than_equal")
            return None
        if maximum is not None and value > maximum:
            self._fail(name, "less_than_equal")
            return None
        return value

    def whole(self, name: str, *, minimum: int | None = None) -> int | None:
        present, value = self._get(name, True)
        if not present:
            return None
        kind, number = _lax_integer(value)
        if kind is not None:
            self._fail(name, kind)
            return None
        if minimum is not None and number < minimum:
            self._fail(name, "greater_than_equal")
            return None
        return number

    def texts(
        self,
        name: str,
        *,
        required: bool = False,
        nullable: bool = True,
        minimum_items: int = 0,
        maximum_items: int | None = None,
        default: list[str] | None = None,
        item_minimum: int = 0,
        item_maximum: int | None = None,
        item_pattern: re.Pattern[str] | None = None,
    ) -> list[str] | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return default
        if len(value) < minimum_items:
            self._fail(name, "too_short")
            return default
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return default
        checked = [
            (index, _text_error(item, item_minimum, item_maximum, item_pattern))
            for index, item in enumerate(value)
        ]
        wrong = [(index, kind) for index, kind in checked if kind is not None]
        self.errors.extend(_error((*self.location, name, index), kind) for index, kind in wrong)
        return default if wrong else list(value)

    def identifier(self, name: str, *, required: bool = True, nullable: bool = False) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            self._fail(name, "uuid_type")
            return None
        try:
            return str(UUID(value))
        except ValueError:
            self._fail(name, "uuid_parsing")
            return None

    def digest(self, name: str) -> str | None:
        value = self.text(name)
        if value is not None and HASH_PATTERN.fullmatch(value) is None:
            self._fail(name, "string_pattern_mismatch")
            return None
        return value

    def value(self, name: str, *, required: bool = True) -> object:
        present, value = self._get(name, required)
        return value if present else None

    def pattern(
        self,
        name: str,
        expression: re.Pattern[str],
        *,
        required: bool = True,
        nullable: bool = False,
        minimum: int = 0,
        maximum: int | None = None,
        default: str | None = None,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        kind = _text_error(value, minimum, maximum)
        if kind is None and expression.fullmatch(str(value)) is None:
            kind = "string_pattern_mismatch"
        if kind is not None:
            self._fail(name, kind)
            return default
        return str(value)

    def normalized(
        self, name: str, value: object, normalizer: Callable[[object], object]
    ) -> object:
        try:
            return normalizer(value)
        except ValueError:
            self._fail(name, "value_error")
            return None

    def moment(self, name: str) -> datetime | None:
        present, value = self._get(name, True)
        if not present:
            return None
        if not isinstance(value, str):
            self._fail(name, "datetime_type")
            return None
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            self._fail(name, "datetime_from_date_parsing")
            return None
        if moment.tzinfo is None or moment.utcoffset() is None:
            self._fail(name, "timezone_aware")
            return None
        return moment

    def flag(self, name: str, *, default: bool = False) -> bool:
        present, value = self._get(name, False)
        if not present:
            return default
        parsed = _lax_boolean(value)
        if parsed is None:
            self._fail(
                name, "bool_parsing" if isinstance(value, str | int | float) else "bool_type"
            )
            return default
        return parsed

    def changed_files(self, name: str) -> list[dict[str, object]]:
        present, value = self._get(name, False)
        if not present:
            return []
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if len(value) > MAX_FILES:
            self._fail(name, "too_long")
            return []
        files = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                self.errors.append(_error((*self.location, name, index), "model_attributes_type"))
                continue
            nested = _Fields(
                item, ("path", "kind", "added", "removed"), location=(*self.location, name, index)
            )
            path = nested.text("path", minimum=1, maximum=MAX_PATH_LENGTH)
            if path is not None:
                path = nested.normalized("path", path, _changed_path)
            kind = nested.choice("kind", FILE_KINDS)
            added = nested.integer("added", minimum=0)
            removed = nested.integer("removed", minimum=0)
            self.errors.extend(nested.errors)
            files.append({"path": path, "kind": kind, "added": added, "removed": removed})
        return files

    def number(
        self, name: str, *, minimum: float | None = None, maximum: float | None = None
    ) -> int | float | None:
        present, value = self._get(name, True)
        if not present:
            return None
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                self._fail(name, "float_parsing")
                return None
        if not isinstance(value, int | float):
            self._fail(name, "float_type")
            return None
        if not math.isfinite(value):
            self._fail(name, "finite_number")
            return None
        if minimum is not None and value < minimum:
            self._fail(name, "greater_than_equal")
            return None
        if maximum is not None and value > maximum:
            self._fail(name, "less_than_equal")
            return None
        return value

    def identifiers(self, name: str, *, maximum_items: int | None = None) -> list[str]:
        present, value = self._get(name, False)
        if not present:
            return []
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return []
        found = []
        for index, item in enumerate(value):
            location = (*self.location, name, index)
            if not isinstance(item, str):
                self.errors.append(_error(location, "uuid_type"))
                continue
            try:
                found.append(str(UUID(item)))
            except ValueError:
                self.errors.append(_error(location, "uuid_parsing"))
        return found

    def child(
        self,
        name: str,
        allowed: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
    ) -> _Fields | None:
        present, value = self._get(name, required)
        if not present or (value is None and nullable):
            return None
        if not isinstance(value, dict):
            self._fail(name, "model_attributes_type")
            return None
        return _Fields(value, allowed, location=(*self.location, name))

    def children(
        self,
        name: str,
        allowed: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
        minimum_items: int = 0,
        maximum_items: int | None = None,
    ) -> list[_Fields] | None:
        present, value = self._get(name, required)
        if not present or (value is None and nullable):
            return None
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if len(value) < minimum_items:
            self._fail(name, "too_short")
            return []
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return []
        found = []
        for index, item in enumerate(value):
            location = (*self.location, name, index)
            if not isinstance(item, dict):
                self.errors.append(_error(location, "model_attributes_type"))
                continue
            found.append(_Fields(item, allowed, location=location))
        return found

    def adopt(self, child: _Fields) -> None:
        self.errors.extend(child.errors)

    def check(self) -> None:
        if self.errors:
            raise _Invalid(self.errors)


def _text_error(
    item: object,
    minimum: int,
    maximum: int | None,
    expression: re.Pattern[str] | None = None,
) -> str | None:
    if not isinstance(item, str):
        return "string_type"
    if len(item) < minimum:
        return "string_too_short"
    if maximum is not None and len(item) > maximum:
        return "string_too_long"
    if expression is not None and expression.fullmatch(item) is None:
        return "string_pattern_mismatch"
    return None


def _lax_integer(value: object) -> tuple[str | None, int]:
    if isinstance(value, bool | int):
        return None, int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "finite_number", 0
        return (None, int(value)) if value.is_integer() else ("int_from_float", 0)
    if isinstance(value, str):
        try:
            return None, int(value.strip())
        except ValueError:
            return "int_parsing", 0
    return "int_type", 0


def _json_media_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    main, _, sub = media.partition("/")
    return main == "application" and (sub == "json" or sub.endswith("+json"))


def _gate_decision(
    call: _Call, actions: Sequence[str], *, literal: bool, maximum: int | None
) -> tuple[str, str | None]:
    fields = _Fields(call.json(), ("action", "reason"))
    action = fields.choice("action", actions, literal=literal)
    reason = fields.text("reason", required=False, nullable=True, maximum=maximum)
    fields.check()
    return str(action), reason
