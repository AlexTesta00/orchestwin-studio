from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

USAGE_STATUS: Final = 2
SIGN_IN_STATUS: Final = 3
UNREACHABLE_STATUS: Final = 4
SPENDING_STATUS: Final = 5
NOT_LINKED_STATUS: Final = 6
NOT_VERIFIED_STATUS: Final = 7
INTERRUPTED_STATUS: Final = 130
BUDGET_CODES: Final = frozenset({"GENERATION_BUDGET_EXCEEDED", "GENERATION_BUDGET_UNAVAILABLE"})
STATUSES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "NOT_SIGNED_IN": SIGN_IN_STATUS,
        "SESSION_EXPIRED": SIGN_IN_STATUS,
        "STUDIO_UNREACHABLE": UNREACHABLE_STATUS,
        "STUDIO_NOT_RECOGNIZED": UNREACHABLE_STATUS,
        "STUDIO_ADDRESS_INVALID": USAGE_STATUS,
        "STUDIO_NOT_SECURE": USAGE_STATUS,
        "SPENDING_REFUSED": SPENDING_STATUS,
        "GENERATION_BUDGET_EXCEEDED": SPENDING_STATUS,
        "GENERATION_BUDGET_UNAVAILABLE": SPENDING_STATUS,
        "PROJECT_NOT_LINKED": NOT_LINKED_STATUS,
        "PROJECT_LINK_INVALID": NOT_LINKED_STATUS,
        "PROJECT_ALREADY_LINKED": 1,
        "FOLDER_NOT_VERIFIED": NOT_VERIFIED_STATUS,
        "FOLDER_SWAP_FAILED": 1,
        "FOLDER_NOT_PUBLISHED": 1,
        "GENERATION_LOST": 1,
        "GENERATION_REJECTED": 1,
        "GENERATION_STILL_RUNNING": 1,
        "GENERATION_INTERRUPTED": INTERRUPTED_STATUS,
        "INPUT_CLOSED": 1,
        "ANSWER_NOT_VALID": 1,
        "SESSION_FILE_LOCKED": 1,
        "API_FAILURE": 1,
        "BROWSER_NOT_FOUND": 1,
        "BROWSER_NOT_STARTED": 1,
        "BROWSER_PROTOCOL_ERROR": 1,
        "PAGE_NOT_LOADED": 1,
        "ACTION_FAILED": 1,
    }
)


class CliError(Exception):
    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        values: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = STATUSES.get(code, 1) if status is None else status
        self.values: Mapping[str, object] = MappingProxyType(dict(values or {}))


class ApiFailure(CliError):
    def __init__(
        self,
        code: str,
        *,
        http_status: int,
        detail: object = None,
        status: int | None = None,
        values: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            code,
            status=api_status(code, http_status) if status is None else status,
            values={"code": code, "http_status": http_status, **(values or {})},
        )
        self.http_status = http_status
        self.detail = detail


def api_status(code: str, http_status: int) -> int:
    if http_status == 402 or code in BUDGET_CODES:
        return SPENDING_STATUS
    if http_status == 401:
        return SIGN_IN_STATUS
    return 1
