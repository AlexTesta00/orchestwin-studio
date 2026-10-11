from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.http import Reply

MISSING_ROUTE: Final = frozenset({404, 405})
SERVER_ERROR: Final = 500


def send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)


def mapping_answer(reply: Reply, *, kind: str | None = None) -> Mapping[str, object]:
    document = reply_body(reply)
    if reply.status >= 400:
        raise refusal(reply.status, document)
    if not isinstance(document, Mapping) or (kind is not None and document.get("kind") != kind):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document


def refusal(
    status: int, document: object, values: Mapping[str, object] | None = None
) -> ApiFailure:
    detail = document.get("detail") if isinstance(document, Mapping) else None
    code = detail.get("code") if isinstance(detail, Mapping) else detail
    return ApiFailure(
        code if isinstance(code, str) else "API_FAILURE", http_status=status, values=values
    )


def route_missing_or_down(failure: ApiFailure) -> bool:
    return failure.http_status in MISSING_ROUTE or failure.http_status >= SERVER_ERROR


def code_of(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str) and detail["code"]:
        return str(detail["code"])
    if isinstance(detail, str) and detail:
        return detail
    job_failure = document.get("failure")
    found = job_failure.get("code") if isinstance(job_failure, Mapping) else None
    return found if isinstance(found, str) and found else None
