from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.http import Reply

TWIN_LEARNING_KIND: Final = "orchestwin.twin-learning"
FEEDBACK_LEARNING: Final = "twins/feedback/learned.json"
TWIN_CRITIQUE: Final = "TWIN_CRITIQUE"
OWNER: Final = "OWNER"
LEARNING_SOURCES: Final = (TWIN_CRITIQUE, OWNER)
PROPOSED: Final = "PROPOSED"
APPROVED: Final = "APPROVED"
REJECTED: Final = "REJECTED"
EMPTY: Final = "EMPTY"
UPDATE_STATUSES: Final = (PROPOSED, APPROVED, REJECTED, EMPTY)
APPROVE: Final = "APPROVE"
REJECT: Final = "REJECT"
UPDATE_DECISIONS: Final = (APPROVE, REJECT)
DECIDED: Final = "DECIDED"
LEARNED: Final = "LEARNED"
RETIRED: Final = "RETIRED"
OBSERVATION_CODE_PREFIX: Final = "OBS"
MAX_LEARNED_OBSERVATIONS: Final = 20
MAX_UPDATE_OBSERVATIONS: Final = 6
MAX_OBSERVATION_LENGTH: Final = 400
MAX_BASIS_LENGTH: Final = 300
MAX_UPDATE_COMMENT_LENGTH: Final = 600
MAX_UPDATE_CHANGES: Final = 8
MAX_UPDATE_TESTS: Final = 4
MAX_REASON_LENGTH: Final = 300
UPDATE_OPERATION: Final = "TWIN_UPDATE"
PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
USER_TWIN_NOT_FOUND: Final = "USER_TWIN_NOT_FOUND"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"
UPDATE_PENDING: Final = "TWIN_UPDATE_PENDING"
NOTHING_NEW: Final = "TWIN_UPDATE_NOTHING_NEW"
NO_UPDATE_MODEL: Final = "TWIN_UPDATE_MODEL_NOT_CONFIGURED"
UPDATE_NOT_FOUND: Final = "TWIN_UPDATE_NOT_FOUND"
ALREADY_DECIDED: Final = "TWIN_UPDATE_ALREADY_DECIDED"
CONTEXT_CHANGED: Final = "TWIN_UPDATE_CONTEXT_CHANGED"
OBSERVATIONS_LIMIT: Final = "TWIN_OBSERVATIONS_LIMIT"
OBSERVATION_NOT_FOUND: Final = "TWIN_OBSERVATION_NOT_FOUND"
MISSING_ROUTE: Final = frozenset({404, 405})
SERVER_ERROR: Final = 500
OBSERVATION_CODE: Final = re.compile(rf"{OBSERVATION_CODE_PREFIX}-([0-9]{{3,6}})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Kept:
    index: int
    statement: str | None = None

    def document(self) -> dict[str, object]:
        return {"index": self.index, "statement": self.statement}


@dataclass(frozen=True, slots=True)
class Learning:
    entries: tuple[Mapping[str, object], ...] = ()
    update_available: bool = False

    def entry(self, twin_id: str) -> Mapping[str, object] | None:
        return next((item for item in self.entries if item.get("twin_id") == twin_id), None)

    def learned_anything(self) -> bool:
        return any(learned_anything(item) for item in self.entries)


def learning_path(project_id: str) -> str:
    return f"/projects/{project_id}/twin-learning"


def twin_path(project_id: str, twin_id: str) -> str:
    return f"/projects/{project_id}/user-twins/{twin_id}"


def propose_path(project_id: str, twin_id: str) -> str:
    return f"{twin_path(project_id, twin_id)}/updates"


def update_path(project_id: str, update_id: str) -> str:
    return f"/projects/{project_id}/twin-updates/{update_id}"


def decision_path(project_id: str, update_id: str) -> str:
    return f"{update_path(project_id, update_id)}/decision"


def observations_path(project_id: str, twin_id: str) -> str:
    return f"{twin_path(project_id, twin_id)}/observations"


def retire_path(project_id: str, twin_id: str, code: str) -> str:
    return f"{observations_path(project_id, twin_id)}/{code}/retire"


def propose_body(locale: str) -> dict[str, object]:
    return {"locale": locale}


def decision_body(
    decision: str, kept: Sequence[Kept] = (), reason: str | None = None
) -> dict[str, object]:
    return {
        "decision": decision,
        "kept": [item.document() for item in kept],
        "reason": reason,
    }


def learn_body(statement: str, about: Mapping[str, object] | None = None) -> dict[str, object]:
    return {"statement": statement, "about": None if about is None else dict(about)}


def retire_body(reason: str | None = None) -> dict[str, object]:
    return {"reason": reason}


def overview(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    try:
        document = client.get(learning_path(project_id))
    except ApiFailure as failure:
        if failure.code != PROJECT_NOT_FOUND and (
            failure.http_status in MISSING_ROUTE or failure.http_status >= SERVER_ERROR
        ):
            return None
        raise
    return _mapping_of(document, 200)


def update_of(client: StudioClient, project_id: str, update_id: str) -> Mapping[str, object]:
    return _answer(client.request("GET", update_path(project_id, update_id)))


def decide(
    client: StudioClient,
    project_id: str,
    update_id: str,
    decision: str,
    *,
    kept: Sequence[Kept] = (),
    reason: str | None = None,
) -> Mapping[str, object]:
    body = decision_body(decision, kept, reason)
    return _answer(client.request("POST", decision_path(project_id, update_id), body=body))


def learn(
    client: StudioClient,
    project_id: str,
    twin_id: str,
    statement: str,
    *,
    about: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    body = learn_body(statement, about)
    reply = client.request("POST", observations_path(project_id, twin_id), body=body)
    return _twin_answer(reply)


def retire(
    client: StudioClient,
    project_id: str,
    twin_id: str,
    code: str,
    *,
    reason: str | None = None,
) -> Mapping[str, object]:
    body = retire_body(reason)
    reply = client.request("POST", retire_path(project_id, twin_id, code), body=body)
    return _twin_answer(reply)


def learning_of(document: object) -> Learning:
    if not isinstance(document, Mapping):
        return Learning()
    return Learning(
        entries=tuple(mappings(document.get("twins"))),
        update_available=document.get("update_available") is True,
    )


def proposal_of(document: object) -> Mapping[str, object] | None:
    update = document.get("update") if isinstance(document, Mapping) else None
    return update if isinstance(update, Mapping) else None


def twin_of(document: object) -> Mapping[str, object] | None:
    twin = document.get("twin") if isinstance(document, Mapping) else None
    return twin if isinstance(twin, Mapping) else None


def label_of(entry: Mapping[str, object] | None, version: int | None = None) -> str:
    label = entry.get("label") if isinstance(entry, Mapping) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return "-" if version is None else str(version)


def development_version(entry: Mapping[str, object] | None) -> int:
    value = entry.get("development_version_number") if isinstance(entry, Mapping) else None
    return value if _integer(value) and value >= 0 else 0


def active_observations(entry: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    return mappings(entry.get("observations")) if isinstance(entry, Mapping) else []


def retired_observations(entry: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    return mappings(entry.get("retired")) if isinstance(entry, Mapping) else []


def learned_count(entry: Mapping[str, object] | None) -> int:
    return len(active_observations(entry))


def learned_anything(entry: Mapping[str, object] | None) -> bool:
    return (
        development_version(entry) > 0
        or bool(active_observations(entry))
        or bool(retired_observations(entry))
    )


def pending_update(entry: Mapping[str, object] | None) -> Mapping[str, object] | None:
    update = entry.get("pending_update") if isinstance(entry, Mapping) else None
    return update if isinstance(update, Mapping) else None


def new_material(entry: Mapping[str, object] | None) -> tuple[int, int]:
    material = entry.get("new_material") if isinstance(entry, Mapping) else None
    return _counts(material)


def has_new_material(entry: Mapping[str, object] | None) -> bool:
    return sum(new_material(entry)) > 0


def update_id_of(update: Mapping[str, object]) -> str:
    value = update.get("id")
    return value if isinstance(value, str) else ""


def update_status(update: Mapping[str, object]) -> str:
    value = update.get("status")
    return value if isinstance(value, str) else ""


def update_comment(update: Mapping[str, object]) -> str:
    return _text(update.get("comment"))


def update_material(update: Mapping[str, object]) -> tuple[int, int]:
    return _counts(update.get("material"))


def proposed_observations(update: Mapping[str, object]) -> list[Mapping[str, object]]:
    return mappings(update.get("observations"))


def update_cost(update: Mapping[str, object]) -> int:
    value = update.get("cost_microusd")
    return value if _integer(value) and value >= 0 else 0


def observation_index(observation: Mapping[str, object], fallback: int) -> int:
    value = observation.get("index")
    return value if _integer(value) and value >= 0 else fallback


def observation_about(observation: Mapping[str, object]) -> tuple[str | None, str | None]:
    about = observation.get("about")
    about = about if isinstance(about, Mapping) else {}
    requirement = about.get("requirement")
    screen = about.get("screen")
    return (
        requirement if isinstance(requirement, str) and requirement else None,
        screen if isinstance(screen, str) and screen else None,
    )


def learned_codes(entry: Mapping[str, object] | None, update_id: str) -> list[str]:
    return [
        str(item["code"])
        for item in active_observations(entry)
        if isinstance(item.get("code"), str) and update_id and item.get("update_id") == update_id
    ]


def observation_codes(entry: Mapping[str, object] | None) -> list[str]:
    return [
        str(item["code"])
        for item in active_observations(entry)
        if isinstance(item.get("code"), str)
    ]


def observation_code(value: str) -> str | None:
    found = OBSERVATION_CODE.fullmatch(value.strip())
    return None if found is None else f"{OBSERVATION_CODE_PREFIX}-{found.group(1)}"


def code_number(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    found = OBSERVATION_CODE.fullmatch(value.strip())
    return None if found is None else int(found.group(1))


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


def failure(status: int, document: object) -> ApiFailure:
    detail = document.get("detail") if isinstance(document, Mapping) else document
    values: dict[str, object] = {}
    update_id = detail.get("update_id") if isinstance(detail, Mapping) else None
    if isinstance(update_id, str) and update_id:
        values["update_id"] = update_id
    return ApiFailure(
        code_of(document) or "API_FAILURE", http_status=status, detail=detail, values=values
    )


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _answer(reply: Reply) -> Mapping[str, object]:
    body = reply_body(reply)
    if reply.status >= 400:
        raise failure(reply.status, body)
    return _mapping_of(body, reply.status)


def _twin_answer(reply: Reply) -> Mapping[str, object]:
    twin = twin_of(_answer(reply))
    if twin is None:
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return twin


def _mapping_of(document: object, status: int) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document


def _counts(value: object) -> tuple[int, int]:
    found = value if isinstance(value, Mapping) else {}
    changes = found.get("changes")
    tests = found.get("tests")
    return (
        changes if _integer(changes) and changes > 0 else 0,
        tests if _integer(tests) and tests > 0 else 0,
    )


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
