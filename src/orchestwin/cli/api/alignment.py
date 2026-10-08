from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

OPERATION: Final = "KNOWLEDGE_ALIGNMENT"
REQUIREMENTS: Final = "REQUIREMENTS"
DESIGN: Final = "DESIGN"
TESTS: Final = "TESTS"
SECTIONS: Final = (REQUIREMENTS, DESIGN, TESTS)
PROPOSED: Final = "PROPOSED"
APPLIED: Final = "APPLIED"
SKIPPED: Final = "SKIPPED"
WAITING: Final = "waiting"
ALL: Final = "all"
APPLY_OPERATIONS: Final[Mapping[str, str]] = MappingProxyType(
    {REQUIREMENTS: "REQUIREMENTS_CHANGE", DESIGN: "DESIGN_CHANGE"}
)
MAX_REQUEST: Final[Mapping[str, int]] = MappingProxyType(
    {REQUIREMENTS: 2000, DESIGN: 1000, TESTS: 600}
)
MAX_REASON: Final = 300
MAX_COMMITS: Final = 50
PROPOSAL_DECIDED: Final = "ALIGNMENT_PROPOSAL_DECIDED"
PROPOSAL_NOT_FOUND: Final = "ALIGNMENT_PROPOSAL_NOT_FOUND"
NO_MODEL: Final = "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED"
REVISION_PENDING: Final = "REVISION_PENDING"
UNCHANGED: Final = "UNCHANGED"
LATEST_RUN_KEYS: Final = (
    "id",
    "from_commit",
    "to_commit",
    "created_at",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
)


def alignment_path(project_id: str) -> str:
    return f"/projects/{project_id}/alignment"


def runs_path(project_id: str) -> str:
    return f"{alignment_path(project_id)}/runs"


def run_path(project_id: str, run_id: str) -> str:
    return f"{runs_path(project_id)}/{run_id}"


def proposals_path(project_id: str, *, status: str | None = None) -> str:
    path = f"{alignment_path(project_id)}/proposals"
    return path if status is None else f"{path}?status={status}"


def apply_path(project_id: str, code: str) -> str:
    return f"{proposals_path(project_id)}/{code}/apply"


def skip_path(project_id: str, code: str) -> str:
    return f"{proposals_path(project_id)}/{code}/skip"


def run_body(locale: str, commits: Sequence[str], since: str | None) -> dict[str, object]:
    return {
        "locale": locale,
        "from_commit": since,
        "to_commit": commits[-1],
        "commits": list(commits),
    }


def apply_body(locale: str, text: str | None) -> dict[str, object]:
    return {"locale": locale, "text": text}


def skip_body(reason: str | None) -> dict[str, object]:
    stripped = " ".join(reason.split()) if isinstance(reason, str) else ""
    return {"reason": stripped[:MAX_REASON] or None}


def proposals(
    client: StudioClient, project_id: str, *, status: str = WAITING
) -> Mapping[str, object]:
    return _mapping_of(client.get(proposals_path(project_id, status=status)))


def run(client: StudioClient, project_id: str, run_id: str) -> Mapping[str, object] | None:
    document = client.get(run_path(project_id, run_id), optional=True)
    found = document.get("run") if isinstance(document, Mapping) else None
    return found if isinstance(found, Mapping) else None


def apply(
    client: StudioClient, project_id: str, code: str, body: Mapping[str, object]
) -> Mapping[str, object]:
    return _mapping_of(client.post(apply_path(project_id, code), dict(body)))


def skip(
    client: StudioClient, project_id: str, code: str, reason: str | None
) -> Mapping[str, object]:
    return _mapping_of(client.post(skip_path(project_id, code), skip_body(reason)))


def latest_run(document: Mapping[str, object]) -> Mapping[str, object] | None:
    found = document.get("latest_run")
    return found if isinstance(found, Mapping) and isinstance(found.get("id"), str) else None


def waiting(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [item for item in _items(document.get("items")) if status_of(item) == PROPOSED]


def proposals_of(run_document: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _items(run_document.get("proposals"))


def proposal_of(document: Mapping[str, object]) -> Mapping[str, object]:
    found = document.get("proposal")
    if not isinstance(found, Mapping):
        raise ApiFailure("API_FAILURE", http_status=200)
    return found


def code_of(proposal: Mapping[str, object]) -> str:
    value = proposal.get("code")
    return value if isinstance(value, str) else "-"


def section_of(proposal: Mapping[str, object]) -> str:
    value = proposal.get("section")
    return value if isinstance(value, str) else ""


def status_of(proposal: Mapping[str, object]) -> str:
    value = proposal.get("status")
    return value if isinstance(value, str) else ""


def text_of(proposal: Mapping[str, object], key: str) -> str:
    value = proposal.get(key)
    return value.strip() if isinstance(value, str) else ""


def origin_of(proposal: Mapping[str, object]) -> Mapping[str, object]:
    value = proposal.get("origin")
    return value if isinstance(value, Mapping) else {}


def subjects_of(proposal: Mapping[str, object]) -> Mapping[str, object]:
    value = proposal.get("subjects")
    return value if isinstance(value, Mapping) else {}


def texts(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str) and item]


def pending_code(code: str) -> bool:
    return code.endswith(REVISION_PENDING)


def unchanged_code(code: str) -> bool:
    return code.endswith(UNCHANGED)


def by_section(items: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    order = {section: index for index, section in enumerate(SECTIONS)}
    return sorted(items, key=lambda item: (order.get(section_of(item), len(order)), code_of(item)))


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_of(document: object, status: int = 200) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document
