from __future__ import annotations

import pytest

from orchestwin.cli.errors import STATUSES, ApiFailure, CliError, api_status

FIXED_CODES = {
    "NOT_SIGNED_IN": 3,
    "SESSION_EXPIRED": 3,
    "STUDIO_UNREACHABLE": 4,
    "STUDIO_ADDRESS_INVALID": 2,
    "STUDIO_NOT_SECURE": 2,
    "SPENDING_REFUSED": 5,
    "GENERATION_BUDGET_EXCEEDED": 5,
    "GENERATION_BUDGET_UNAVAILABLE": 5,
    "PROJECT_NOT_LINKED": 6,
    "PROJECT_ALREADY_LINKED": 1,
    "FOLDER_NOT_VERIFIED": 7,
    "GENERATION_LOST": 1,
    "GENERATION_REJECTED": 1,
    "INPUT_CLOSED": 1,
    "SESSION_FILE_LOCKED": 1,
    "API_FAILURE": 1,
}


@pytest.mark.parametrize(("code", "status"), sorted(FIXED_CODES.items()))
def test_fixed_codes_carry_the_status_of_the_contract(code: str, status: int) -> None:
    assert STATUSES[code] == status
    assert CliError(code).status == status


def test_an_unknown_code_fails_with_status_one_and_an_explicit_status_wins() -> None:
    assert CliError("SOMETHING_NEW").status == 1
    assert CliError("NOT_SIGNED_IN", status=1).status == 1
    assert CliError("GENERATION_INTERRUPTED").status == 130


def test_values_are_kept_read_only_and_the_text_is_only_the_code() -> None:
    values = {"address": "http://127.0.0.1:9", "sent": False}
    error = CliError("STUDIO_UNREACHABLE", values=values)
    values["address"] = "changed"

    assert error.values == {"address": "http://127.0.0.1:9", "sent": False}
    assert str(error) == "STUDIO_UNREACHABLE"
    with pytest.raises(TypeError):
        error.values["address"] = "other"


@pytest.mark.parametrize(
    ("code", "http_status", "status"),
    [
        ("GENERATION_BUDGET_EXCEEDED", 402, 5),
        ("anything", 402, 5),
        ("GENERATION_BUDGET_UNAVAILABLE", 503, 5),
        ("invalid_authentication", 401, 3),
        ("project_not_found", 404, 1),
        ("API_FAILURE", 500, 1),
    ],
)
def test_api_failures_map_the_http_status(code: str, http_status: int, status: int) -> None:
    failure = ApiFailure(code, http_status=http_status, detail={"code": code})

    assert api_status(code, http_status) == status
    assert failure.status == status
    assert failure.http_status == http_status
    assert failure.detail == {"code": code}
    assert failure.values["code"] == code
    assert failure.values["http_status"] == http_status
    assert isinstance(failure, CliError)
