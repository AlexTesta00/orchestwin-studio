from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from orchestwin.agents.catalog import all_agent_catalog_entries
from orchestwin.models.design_change import ELEMENT_CODE_PATTERN, SCREEN_CODE_PATTERN
from orchestwin.projects.briefs import ProjectBrief
from orchestwin.projects.progress import ProjectStage
from orchestwin.workflow.gates import HumanGateType

MODEL = "fake-model-not-real"
MAX_OWNER_ASSERTIONS = 20
MAX_OWNER_ASSERTION = 300
STAGES = ("brief", "team", "twins", "requirements", "design")
ACCOUNTS = "ACCOUNTS"
LOCAL_OWNER = "LOCAL_OWNER"
GATE_ACTIONS = ("SUBMIT", "APPROVE", "REJECT", "REQUEST_REVISION", "PAUSE", "RESUME", "CANCEL")
DECISION_ACTIONS = GATE_ACTIONS[1:]
GATE_TYPES = {
    "brief": HumanGateType.PROJECT_BRIEF,
    "team": HumanGateType.AGENT_TEAM,
    "twins": HumanGateType.USER_MODELING,
    "requirements": HumanGateType.REQUIREMENTS,
    "design": HumanGateType.DESIGN,
}
AGENT_ORDER = tuple(entry.agent_id.value for entry in all_agent_catalog_entries())
TEMPLATE_PARAMETER = re.compile(r"\{([a-z_]+)\}")
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
REQUIREMENT_CODE = re.compile(r"\bREQ-[0-9]{3,6}\b")
LOCALE_PATTERN = re.compile(r"[a-z]{2,3}(-[A-Z]{2})?")
MAX_LOCALE_LENGTH = 20
DEFAULT_LOCALE = "it-IT"
SECTION_STAGES = {
    "BRIEF": "brief",
    "TEAM": "team",
    "USER_TWINS": "twins",
    "REQUIREMENTS": "requirements",
    "DESIGN": "design",
}
FOLDER_SECTIONS = {stage: ProjectStage(key) for key, stage in SECTION_STAGES.items()}
ALIGNMENT_REASON = "Aligned to the current upstream versions with unchanged content."
CUT_MARK = "…"
SEED_FILE = {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}
SEED_DIFF = "diff --git a/src/app.js b/src/app.js\n+// REQ-003 splits the bill\n"
SCREEN_CODE = re.compile(SCREEN_CODE_PATTERN)
ELEMENT_CODE = re.compile(ELEMENT_CODE_PATTERN)
DISCLAIMER = (
    "This is simulated feedback based on the available profile, evidence, and project "
    "artifacts. It is a design hypothesis and not empirical evidence of real-user behavior."
)
APPROACHES = {
    "it": ("Schermate essenziali con esempi realistici.", "Modifica limitata a quanto richiesto."),
    "en": ("Essential screens with realistic examples.", "Change limited to what was asked."),
}


class _Refusal(Exception):
    def __init__(
        self, status: int, detail: object, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(status)
        self.status = status
        self.detail = detail
        self.headers = dict(headers or {})


class _Invalid(Exception):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__("invalid_request")
        self.errors = errors


class _JobFailure(Exception):
    def __init__(
        self,
        code: str,
        *,
        rejected: bool = False,
        reasons: Sequence[Mapping[str, object]] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.rejected = rejected
        self.reasons = [dict(reason) for reason in reasons]


@dataclass(slots=True)
class _Answer:
    status: int
    body: object = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    content_type: str = "application/json"

    def content(self) -> bytes:
        if self.raw is not None:
            return self.raw
        if self.status == 204:
            return b""
        return json.dumps(
            self.body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")


@dataclass(slots=True)
class _Account:
    id: str
    email: str
    password: str = field(repr=False)
    created_at: datetime


@dataclass(slots=True)
class _AccessToken:
    account: str
    expires_at: datetime


@dataclass(slots=True)
class _RefreshSession:
    token: str = field(repr=False)
    account: str
    family: str
    expires_at: datetime
    rotated: bool = False
    revoked: bool = False


@dataclass(slots=True)
class _Job:
    id: str
    owner: str
    project_id: str
    kind: str
    operation: str
    key: str
    alternative_id: str | None
    started_at: datetime
    work: Callable[[_Job], object]
    status: str = "RUNNING"
    stage: str | None = "GENERATING"
    attempt: int = 1
    finished_at: datetime | None = None
    result: object = None
    failure: object = None
    response: object = None
    polls: int = 0
    lost: bool = False

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.owner, self.project_id, self.kind, self.key)

    def payload(self) -> dict[str, object]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "operation": self.operation,
            "status": self.status,
            "stage": self.stage,
            "attempt": self.attempt,
            "started_at": _iso(self.started_at),
            "finished_at": None if self.finished_at is None else _iso(self.finished_at),
            "alternative_id": self.alternative_id,
            "result": self.result,
            "failure": self.failure,
            "response": self.response,
        }


@dataclass(slots=True)
class _BriefVersion:
    payload: dict[str, object]
    brief: ProjectBrief

    @property
    def id(self) -> str:
        return str(self.payload["id"])

    @property
    def number(self) -> int:
        return int(self.payload["version_number"])

    @property
    def content_hash(self) -> str:
        return str(self.payload["content_hash"])


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _domain_refusal(message: str) -> _Refusal:
    return _Refusal(
        422,
        {
            "code": "invalid_request",
            "errors": [{"loc": ["body"], "type": "value_error", "msg": message}],
        },
    )
