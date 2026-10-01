from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.client import api_failure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

MICRO_USD: Final = 1_000_000
BUDGET_PATH: Final = "/model-runtime/budget"
NO_BUDGET_CODES: Final = frozenset(
    {"REAL_MODEL_RUNTIME_NOT_CONFIGURED", "GENERATION_BUDGET_NOT_CONFIGURED"}
)
SUBSCRIPTION_BILLING: Final = "SUBSCRIPTION"
API_BILLING: Final = "API"
MIXED_BILLING: Final = "MIXED"
BILLINGS: Final = frozenset({SUBSCRIPTION_BILLING, API_BILLING, MIXED_BILLING})


def budget(client: StudioClient) -> Mapping[str, object] | None:
    reply = client.request("GET", BUDGET_PATH)
    if reply.status == 404:
        return None
    if reply.status >= 400:
        failure = api_failure(reply)
        if reply.status == 503 and failure.code in NO_BUDGET_CODES:
            return None
        raise failure
    document = reply.json()
    if not isinstance(document, dict) or not _amount(document.get("total_microusd")):
        return None
    return document


def project_usage(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"/projects/{project_id}/model-usage", optional=True)
    return document if isinstance(document, dict) else None


def billing(document: object) -> str:
    value = document.get("billing") if isinstance(document, Mapping) else None
    return value if isinstance(value, str) and value in BILLINGS else API_BILLING


def on_subscription(document: object) -> bool:
    return billing(document) == SUBSCRIPTION_BILLING


def remaining_usd(document: Mapping[str, object]) -> float | None:
    value = document.get("remaining_total_microusd")
    return value / MICRO_USD if _amount(value) else None


def spent_usd(document: Mapping[str, object]) -> float | None:
    totals = document.get("totals")
    value = totals.get("cost_microusd") if isinstance(totals, Mapping) else None
    return value / MICRO_USD if _amount(value) else None


def _amount(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
