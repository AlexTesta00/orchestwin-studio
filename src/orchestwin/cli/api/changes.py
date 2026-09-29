from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.client import payload
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.folder import StateSummary

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

NO_REVIEW_MODEL: Final = "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"
REVIEW_EXISTS: Final = "CODE_CHANGE_REVIEW_EXISTS"
CHANGE_NOT_FOUND: Final = "CODE_CHANGE_NOT_FOUND"
RECORDED: Final = "RECORDED"
ALREADY_RECORDED: Final = "ALREADY_RECORDED"
REVIEWED: Final = "REVIEWED"
DECIDED: Final = "DECIDED"
ALIGNED: Final = "ALIGNED"
CODE_DRIFT: Final = "CODE_DRIFT"
DESIGN_OUTDATED: Final = "DESIGN_OUTDATED"
REQUIREMENTS_OUTDATED: Final = "REQUIREMENTS_OUTDATED"
VERDICTS: Final = (ALIGNED, CODE_DRIFT, DESIGN_OUTDATED, REQUIREMENTS_OUTDATED)
DESIGN_CHANGE: Final = "DESIGN_CHANGE"
REQUIREMENTS_CHANGE: Final = "REQUIREMENTS_CHANGE"
CODE_TASKS: Final = "CODE_TASKS"
DISMISSED: Final = "DISMISSED"
DECISIONS: Final = (ALIGNED, DESIGN_CHANGE, REQUIREMENTS_CHANGE, CODE_TASKS, DISMISSED)
FINE: Final = "FINE"
CONCERN: Final = "CONCERN"
DRIFT: Final = "DRIFT"
CRITIQUE_VERDICTS: Final = (FINE, CONCERN, DRIFT)
SEVERITIES: Final = ("LOW", "MEDIUM", "HIGH")
OPEN: Final = "OPEN"
REVIEW_OPERATION: Final = "CODE_CHANGE_REVIEW"
ALIGNMENT_OPERATION: Final = "CODE_ALIGNMENT"
MAX_TASKS: Final = 10
MAX_TASK_LENGTH: Final = 300
MAX_NOTE_LENGTH: Final = 2000
MAX_DESIGN_REQUEST: Final = 1000
MAX_REQUIREMENTS_REQUEST: Final = 2000
MISSING_ROUTE: Final = frozenset({404, 405})


def changes_path(project_id: str) -> str:
    return f"/projects/{project_id}/code-changes"


def change_path(project_id: str, commit: str) -> str:
    return f"{changes_path(project_id)}/{commit}"


def review_path(project_id: str, commit: str) -> str:
    return f"{change_path(project_id, commit)}/reviews"


def decision_path(project_id: str, commit: str) -> str:
    return f"{change_path(project_id, commit)}/decision"


def review_body(locale: str, again: bool) -> dict[str, object]:
    return {"locale": locale, "again": bool(again)}


def alignment(client: StudioClient, project_id: str) -> Mapping[str, object]:
    return _mapping_of(client.get(f"/projects/{project_id}/alignment"))


def record(
    client: StudioClient, project_id: str, body: Mapping[str, object]
) -> tuple[int, Mapping[str, object]]:
    reply = client.request("POST", changes_path(project_id), body=dict(body))
    return reply.status, _mapping_of(payload(reply), reply.status)


def changes(
    client: StudioClient, project_id: str, *, pending: bool = False
) -> list[Mapping[str, object]]:
    path = changes_path(project_id)
    document = client.get(f"{path}?pending=true" if pending else path)
    return _items(document)


def change(client: StudioClient, project_id: str, commit: str) -> Mapping[str, object] | None:
    document = client.get(change_path(project_id, commit), optional=True)
    return document if isinstance(document, Mapping) else None


def reviews(client: StudioClient, project_id: str, commit: str) -> list[Mapping[str, object]]:
    return _items(client.get(review_path(project_id, commit)))


def decide(
    client: StudioClient,
    project_id: str,
    commit: str,
    kind: str,
    *,
    note: str | None = None,
    tasks: Sequence[str] = (),
) -> Mapping[str, object]:
    written = [" ".join(str(task).split()) for task in tasks]
    stripped = note.strip() if isinstance(note, str) else ""
    body = {
        "kind": kind,
        "note": stripped or None,
        "tasks": [task for task in written if task],
    }
    return _mapping_of(client.post(decision_path(project_id, commit), body))


def summary(client: StudioClient, project_id: str) -> StateSummary | None:
    try:
        document = alignment(client, project_id)
        items = changes(client, project_id)
    except ApiFailure as failure:
        if failure.http_status in MISSING_ROUTE or failure.http_status >= 500:
            return None
        raise
    return summary_of(document, len(items))


def summary_of(document: Mapping[str, object], recorded: int) -> StateSummary:
    point = aligned(document)
    commit = None if point is None else point.get("commit")
    return StateSummary(
        changes=recorded,
        pending_changes=pending_count(document),
        aligned_commit=commit if isinstance(commit, str) and commit else None,
        open_tasks=len(open_tasks(document)),
    )


def reference(document: Mapping[str, object], stage: str) -> Mapping[str, object] | None:
    parts = document.get("reference")
    value = parts.get(stage) if isinstance(parts, Mapping) else None
    return value if isinstance(value, Mapping) else None


def aligned(document: Mapping[str, object]) -> Mapping[str, object] | None:
    value = document.get("aligned")
    return value if isinstance(value, Mapping) else None


def open_tasks(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = document.get("tasks")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping) and item.get("status") == OPEN]


def pending_count(document: Mapping[str, object]) -> int:
    value = document.get("pending_changes")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def review_available(document: Mapping[str, object]) -> bool:
    return document.get("review_available") is True


def verdict_of(change_document: Mapping[str, object]) -> str | None:
    review = change_document.get("review")
    value = review.get("verdict") if isinstance(review, Mapping) else None
    return value if isinstance(value, str) else None


def decision_of(change_document: Mapping[str, object]) -> str | None:
    decision = change_document.get("decision")
    value = decision.get("kind") if isinstance(decision, Mapping) else None
    return value if isinstance(value, str) else None


def run_alignment(run: Mapping[str, object]) -> Mapping[str, object]:
    value = run.get("alignment")
    return value if isinstance(value, Mapping) else {}


def run_status(run: Mapping[str, object]) -> str | None:
    value = run_alignment(run).get("status")
    return value if isinstance(value, str) else None


def code_of(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    if isinstance(detail, str) and detail:
        return detail
    return None


def failure(status: int, document: object) -> ApiFailure:
    detail = document.get("detail") if isinstance(document, Mapping) else document
    return ApiFailure(code_of(document) or "API_FAILURE", http_status=status, detail=detail)


def _items(document: object) -> list[Mapping[str, object]]:
    items = document.get("items") if isinstance(document, Mapping) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _mapping_of(document: object, status: int = 200) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document
