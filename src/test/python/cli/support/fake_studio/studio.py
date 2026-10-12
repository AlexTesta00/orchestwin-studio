from __future__ import annotations

import contextlib
import hashlib
import re
import secrets
import threading
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from orchestwin.identity.domain import InvalidEmailAddress, NormalizedEmail
from orchestwin.projects.progress import (
    CURRENT_CATALOG,
    ArtifactVersion,
    CatalogVersion,
    GateState,
    ProjectProgressFacts,
    TeamState,
    UserTwinsState,
    project_progress,
)
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    create_human_gate,
    mark_human_gate_stale,
    next_human_gate_iteration,
    transition_human_gate,
)

from .acceptance import _AcceptanceRoutes
from .activity import _ActivityRoutes
from .alignment import _AlignmentRoutes
from .auth import _AuthRoutes, _email_key
from .brief import EXTRA_QUESTIONS, _BriefRoutes
from .changes import _ChangeRoutes
from .common import _artifact_version, _digest, _error, _event_payload, _reference_version
from .critiques import _CritiqueRoutes
from .design import DESIGNER, _DesignRoutes
from .evaluations import _EvaluationRoutes
from .evidence import _EvidenceRoutes
from .fields import _Call
from .learning import _LearningRoutes
from .mockups import _MockupRoutes
from .opinions import _OpinionRoutes
from .packages import _PackageRoutes
from .project import FakeProject
from .projects import MAX_PROJECT_NAME, PROJECT_MODES, _ProjectRoutes
from .requirements import _RequirementRoutes
from .routes import (
    PREFIX,
    ROUTES,
    RecordedRequest,
    _bearer_token,
    _compile,
    _path_parameters,
    _prefers_async,
    _Server,
)
from .sections import _SectionRoutes
from .seeding import ALWAYS_PRESENT, ESSENTIAL, OPERATIONS, _Seeding
from .tasks import _TaskRoutes
from .team import _TeamRoutes
from .texts import COSTS, PURPOSES, TASKS
from .twins import _TwinRoutes
from .values import (
    ACCOUNTS,
    AGENT_ORDER,
    GATE_TYPES,
    LOCAL_OWNER,
    MODEL,
    STAGES,
    TEMPLATE_PARAMETER,
    _Account,
    _Answer,
    _Invalid,
    _iso,
    _Job,
    _JobFailure,
    _Refusal,
)

if TYPE_CHECKING:
    from .routes import Route
    from .values import _AccessToken, _RefreshSession


EPOCH = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
MAX_RUNNING_JOBS = 4
MAX_TWINS = 8
LANGUAGES = ("it", "en")
JOB_STATUSES = ("RUNNING", "SUCCEEDED", "REJECTED", "FAILED")
BILLINGS = ("SUBSCRIPTION", "API", "MIXED")
ACCESS_MODES = (ACCOUNTS, LOCAL_OWNER)
LOCAL_OWNER_EMAIL = "local-owner@example.com"
NEW_ARTIFACT_REQUIRED = {
    "brief": "NEW_BRIEF_REQUIRED",
    "team": "NEW_PROPOSAL_REQUIRED",
    "twins": "NEW_SNAPSHOT_REQUIRED",
    "requirements": "NEW_SPECIFICATION_REQUIRED",
    "design": "NEW_PACKAGE_REQUIRED",
}
REJECTION = {"it": "la schermata non supera il controllo", "en": "the screen fails the check"}


@dataclass(slots=True)
class _FailureRule:
    method: str
    pattern: re.Pattern[str]
    status: int
    body: object
    headers: dict[str, str]
    remaining: int


@dataclass(slots=True)
class _JobRule:
    code: str
    status: int
    rejected: bool


class FakeStudio(
    _AuthRoutes,
    _ProjectRoutes,
    _BriefRoutes,
    _TeamRoutes,
    _TwinRoutes,
    _RequirementRoutes,
    _DesignRoutes,
    _MockupRoutes,
    _EvaluationRoutes,
    _OpinionRoutes,
    _CritiqueRoutes,
    _SectionRoutes,
    _PackageRoutes,
    _ChangeRoutes,
    _AlignmentRoutes,
    _TaskRoutes,
    _AcceptanceRoutes,
    _LearningRoutes,
    _EvidenceRoutes,
    _ActivityRoutes,
    _Seeding,
):
    def __init__(
        self,
        *,
        language: str = "it",
        twins: int = 2,
        hosted: bool = True,
        budget_usd: float | None = 60.0,
        spent_usd: float = 0.0,
        billing: str | None = None,
        job_polls: int = 2,
        now: Callable[[], datetime] | None = None,
        directions: bool = False,
        design_system: bool = False,
        landmarks: bool = False,
        corrections: Sequence[Mapping[str, object]] = (),
        access_mode: str = ACCOUNTS,
        local_owner_email: str = LOCAL_OWNER_EMAIL,
    ) -> None:
        if language not in LANGUAGES:
            raise ValueError("language must be it or en")
        if access_mode not in ACCESS_MODES:
            raise ValueError("access_mode must be ACCOUNTS or LOCAL_OWNER")
        if directions and not hosted:
            raise ValueError("directions need a hosted model")
        if design_system and not directions:
            raise ValueError("a design system needs the directions")
        if isinstance(twins, bool) or not isinstance(twins, int) or not 1 <= twins <= MAX_TWINS:
            raise ValueError(f"twins must be between 1 and {MAX_TWINS}")
        if isinstance(job_polls, bool) or not isinstance(job_polls, int) or job_polls < 0:
            raise ValueError("job_polls must be a non-negative integer")
        if budget_usd is not None and budget_usd <= 0:
            raise ValueError("budget_usd must be positive or None")
        if spent_usd < 0:
            raise ValueError("spent_usd must not be negative")
        if billing is not None and billing not in BILLINGS:
            raise ValueError("billing must be SUBSCRIPTION, API, MIXED or None")
        self.language = language
        self.twins = twins
        self.hosted = hosted
        self.directions = directions
        self.design_system = design_system
        self.landmarks = landmarks
        self.corrections = tuple(dict(item) for item in corrections)
        self.billing = billing
        self.job_polls = job_polls
        self.requests: list[RecordedRequest] = []
        self.errors: list[str] = []
        self._budget = None if budget_usd is None else round(budget_usd * 1_000_000)
        self._spent = round(spent_usd * 1_000_000)
        self._clock = now
        self._moment = EPOCH if now is None else datetime.min.replace(tzinfo=UTC)
        self._counter = 0
        self._tokens = 0
        self._lock = threading.RLock()
        self._accounts: dict[str, _Account] = {}
        self._accounts_by_id: dict[str, _Account] = {}
        self._access: dict[str, _AccessToken] = {}
        self._sessions: dict[str, _RefreshSession] = {}
        self._projects: dict[str, FakeProject] = {}
        self._jobs: dict[str, _Job] = {}
        self._failures: list[_FailureRule] = []
        self._job_rules: dict[str, list[_JobRule]] = {}
        self._lost: dict[str, int] = {}
        self._extra_fields: list[str] = []
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._routes = tuple((route, _compile(route.template)) for route in ROUTES)
        self.access_mode = access_mode
        self.local_owner_email = _registered_email(local_owner_email)
        if access_mode == LOCAL_OWNER:
            self.add_account(self.local_owner_email, secrets.token_urlsafe(48))

    @property
    def address(self) -> str:
        if self._server is None:
            raise RuntimeError("the fake studio is not running")
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def spent_microusd(self) -> int:
        with self._lock:
            return self._spent

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def __enter__(self) -> FakeStudio:
        if self._server is not None:
            raise RuntimeError("the fake studio is already running")
        server = _Server(self)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.02},
            name="fake-studio",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None or thread is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()
            thread.join()

    def now(self) -> datetime:
        with self._lock:
            return self._now()

    def add_account(self, email: str, password: str) -> None:
        key = _registered_email(email)
        if not password:
            raise ValueError("password must not be empty")
        with self._lock:
            if key in self._accounts:
                raise ValueError("the account already exists")
            account = _Account(self._new_id(), key, password, self._now())
            self._accounts[key] = account
            self._accounts_by_id[account.id] = account

    def ask_after_essentials(self, *fields: str) -> None:
        if not fields:
            raise ValueError("name at least one field of the brief")
        for name in fields:
            if name in ESSENTIAL:
                raise ValueError(f"{name} is an essential field of the brief")
            if name not in EXTRA_QUESTIONS[self.language]:
                raise ValueError(f"{name} is not a field that the fake can ask")
        with self._lock:
            self._extra_fields.extend(name for name in fields if name not in self._extra_fields)

    def fail_next(
        self,
        method: str,
        path_pattern: str,
        *,
        status: int,
        body: object,
        times: int = 1,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 100 <= status <= 599:
            raise ValueError("status must be an HTTP status")
        if times < 1:
            raise ValueError("times must be positive")
        pattern = re.compile(TEMPLATE_PARAMETER.sub("[^/]+", path_pattern))
        with self._lock:
            self._failures.append(
                _FailureRule(method.upper(), pattern, status, body, dict(headers or {}), times)
            )

    def fail_job(
        self, operation: str, *, code: str, status: int = 503, rejected: bool = False
    ) -> None:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation}")
        with self._lock:
            self._job_rules.setdefault(operation, []).append(_JobRule(code, status, rejected))

    def lose_job(self, operation: str) -> None:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation}")
        with self._lock:
            self._lost[operation] = self._lost.get(operation, 0) + 1

    def expire_access_tokens(self) -> None:
        with self._lock:
            self._access.clear()

    def project(self, project_id: str) -> FakeProject:
        with self._lock:
            return self._projects[str(UUID(project_id))]

    def seed_project(
        self,
        *,
        owner: str,
        name: str,
        through: str,
        team_without: Sequence[str] = (),
        requirements_schema_version: int = 2,
    ) -> FakeProject:
        if type(requirements_schema_version) is not int or requirements_schema_version not in (
            1,
            2,
        ):
            raise ValueError("requirements_schema_version must be 1 or 2")
        if isinstance(team_without, str):
            raise ValueError("team_without must be a sequence of agent identifiers")
        dropped = tuple(dict.fromkeys(team_without))
        unknown = [agent for agent in dropped if agent not in AGENT_ORDER]
        if unknown:
            raise ValueError(f"unknown agents: {', '.join(unknown)}")
        fixed = [agent for agent in dropped if agent in ALWAYS_PRESENT]
        if fixed:
            raise ValueError(f"agents always present in every team: {', '.join(fixed)}")
        with self._lock:
            account = self._accounts.get(_email_key(owner) or "")
            if account is None:
                raise ValueError("the owner has no account")
            if through not in STAGES:
                raise ValueError(f"through must be one of {', '.join(STAGES)}")
            if dropped and through == "brief":
                raise ValueError("team_without needs a seed through the team or a later step")
            if DESIGNER in dropped and through == "design":
                raise ValueError("a team without the UX/UI designer never reaches the design")
            normalized = " ".join(name.split())
            if not 1 <= len(normalized) <= MAX_PROJECT_NAME:
                raise ValueError("the project name is not valid")
            project = self._new_project(account, normalized, PROJECT_MODES[0])
            self._seed(
                project,
                through,
                approve=True,
                dropped=dropped,
                requirements_schema_version=requirements_schema_version,
            )
            return project

    def sections(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).sections()

    def alignments(self, project_id: str) -> list[dict[str, object]]:
        return self.project(project_id).alignments()

    def seed_perspective_change(self, project_id: str, agent_id: str) -> dict[str, object]:
        return self.project(project_id).seed_perspective_change(agent_id)

    def seed_requirements_change(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_requirements_change()

    def seed_brief_change(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_brief_change()

    def seed_requirement_removed(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_requirement_removed()

    def seed_design_revision(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_design_revision()

    def seed_alignment_run(
        self, project_id: str, proposals: Sequence[object] | None = None
    ) -> dict[str, object]:
        return self.project(project_id).seed_alignment_run(proposals)

    def alignment_runs(self, project_id: str) -> list[dict[str, object]]:
        return self.project(project_id).alignment_runs()

    def alignment_proposals(self, project_id: str) -> list[dict[str, object]]:
        return self.project(project_id).alignment_proposals()

    def _now(self) -> datetime:
        if self._clock is None:
            moment = self._moment
            self._moment = moment + timedelta(seconds=1)
            return moment
        moment = self._clock()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("the clock of the fake studio must be timezone-aware")
        moment = max(moment.astimezone(UTC), self._moment)
        self._moment = moment
        return moment

    def _new_id(self) -> str:
        self._counter += 1
        digest = hashlib.sha256(f"orchestwin-fake-studio:{self._counter}".encode()).digest()
        return str(UUID(bytes=digest[:16], version=4))

    def _handle(self, method: str, target: str, headers: dict[str, str], raw: bytes) -> _Answer:
        with self._lock:
            parts = urlsplit(target)
            self.requests.append(
                RecordedRequest(
                    method, parts.path, parts.query, MappingProxyType(dict(headers)), raw
                )
            )
            try:
                return self._dispatch(method, parts.path, parts.query, headers, raw)
            except Exception:
                self.errors.append(traceback.format_exc())
                return _Answer(
                    500,
                    raw=b"Internal Server Error",
                    content_type="text/plain; charset=utf-8",
                )

    def _record_error(self, text: str) -> None:
        with self._lock:
            self.errors.append(text)

    def _dispatch(
        self, method: str, path: str, query: str, headers: dict[str, str], raw: bytes
    ) -> _Answer:
        relative = path[len(PREFIX) :] if path.startswith(PREFIX + "/") else None
        failure = self._failure(method, path, relative)
        if failure is not None:
            return failure
        if relative is None:
            return _Answer(404, {"detail": "Not Found"})
        matched: tuple[Route, dict[str, str]] | None = None
        allowed: list[str] = []
        for route, pattern in self._routes:
            found = pattern.fullmatch(relative)
            if found is None:
                continue
            if route.method == method:
                matched = (route, found.groupdict())
                break
            allowed.append(route.method)
        if matched is None:
            if allowed:
                return _Answer(
                    405, {"detail": "Method Not Allowed"}, headers={"Allow": ", ".join(allowed)}
                )
            return _Answer(404, {"detail": "Not Found"})
        route, parameters = matched
        user = None
        if route.authenticated:
            header = headers.get("authorization")
            user = self._bearer(header)
            if user is None and self.access_mode == LOCAL_OWNER and not _bearer_token(header):
                user = self._local_owner()
            if user is None:
                return _Answer(
                    401,
                    {"detail": "invalid_authentication"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        call = _Call(
            method=method,
            path=relative,
            user=user,
            params={},
            query=parse_qs(query, keep_blank_values=True),
            headers=headers,
            raw=raw,
            prefer_async=_prefers_async(headers.get("prefer")),
        )
        try:
            call.params = _path_parameters(parameters)
            self._provided_guard(call, route.action)
            return getattr(self, f"_route_{route.action}")(call)
        except _Invalid as invalid:
            detail = "invalid_authentication" if relative == "/auth/login" else "invalid_request"
            return _Answer(422, {"detail": detail, "errors": invalid.errors})
        except _Refusal as refusal:
            return _Answer(refusal.status, {"detail": refusal.detail}, headers=refusal.headers)

    def _failure(self, method: str, path: str, relative: str | None) -> _Answer | None:
        for rule in self._failures:
            if rule.remaining < 1 or rule.method != method:
                continue
            if rule.pattern.fullmatch(path) is None and (
                relative is None or rule.pattern.fullmatch(relative) is None
            ):
                continue
            rule.remaining -= 1
            if isinstance(rule.body, bytes):
                return _Answer(
                    rule.status,
                    raw=rule.body,
                    headers=dict(rule.headers),
                    content_type="text/plain; charset=utf-8",
                )
            return _Answer(rule.status, rule.body, headers=dict(rule.headers))
        return None

    def _bearer(self, header: str | None) -> _Account | None:
        token = _bearer_token(header)
        if token is None:
            return None
        access = self._access.get(token)
        if access is None or access.expires_at <= self._now():
            return None
        return self._accounts_by_id.get(access.account)

    def _local_owner(self) -> _Account:
        return self._accounts[self.local_owner_email]

    def _owned(self, call: _Call) -> FakeProject | None:
        project = self._projects.get(call.project_id)
        if project is None or project.account.id != call.account.id:
            return None
        return project

    def _new_project(self, account: _Account, name: str, mode: str) -> FakeProject:
        project = FakeProject(self, account, self._new_id(), name, mode, self._now())
        self._projects[project.id] = project
        return project

    def _record(self, project: FakeProject | None, operation: str) -> str:
        identifier = self._new_id()
        if not self.hosted:
            return identifier
        cost = COSTS[operation]
        if self._budget is not None and self._spent + cost > self._budget:
            raise _Refusal(402, {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"})
        self._spent += cost
        if project is not None:
            project.usage.insert(
                0,
                {
                    "generation_id": identifier,
                    "recorded_at": _iso(self._now()),
                    "task": TASKS[operation],
                    "purpose": PURPOSES[operation],
                    "provider_kind": "ANTHROPIC_HOSTED",
                    "model": MODEL,
                    "status": "SUCCEEDED",
                    "failure_code": None,
                    "input_tokens": cost // 10,
                    "output_tokens": cost // 50,
                    "reasoning_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "cost_microusd": cost,
                    "latency_milliseconds": 1000 + cost // 1000,
                },
            )
        return identifier

    def _require_budget(self, project: FakeProject | None) -> None:
        if not self.hosted or self._budget is None:
            return
        spent = 0 if project is None else sum(int(item["cost_microusd"]) for item in project.usage)
        if self._spent >= self._budget or spent >= self._budget:
            raise _Refusal(402, {"code": "GENERATION_BUDGET_EXCEEDED"})

    def _later(
        self,
        call: _Call,
        operation: str,
        body: Mapping[str, object],
        work: Callable[[], _Answer],
    ) -> _Answer:
        if not call.prefer_async:
            return work()
        parameters = [
            f"{name}={value}" for name, value in sorted(call.params.items()) if name != "project_id"
        ]
        key = ":".join((operation, *parameters, _digest(dict(body))))
        job = self._start_job(
            call,
            kind="REQUEST",
            operation=operation,
            key=key,
            alternative_id=None,
            work=lambda _job: work(),
        )
        return _Answer(202, job.payload(), headers={"Preference-Applied": "respond-async"})

    def _start_job(
        self,
        call: _Call,
        *,
        kind: str,
        operation: str,
        key: str,
        alternative_id: str | None,
        work: Callable[[_Job], object],
    ) -> _Job:
        owner = call.account.id
        wanted = (owner, call.project_id, kind, key)
        for job in self._jobs.values():
            if job.status == "RUNNING" and not job.lost and job.identity == wanted:
                return job
        running = sum(
            1
            for job in self._jobs.values()
            if job.status == "RUNNING" and not job.lost and job.owner == owner
        )
        if running >= MAX_RUNNING_JOBS:
            raise _Refusal(429, {"code": "TOO_MANY_GENERATIONS"})
        job = _Job(
            id=self._new_id(),
            owner=owner,
            project_id=call.project_id,
            kind=kind,
            operation=operation,
            key=key,
            alternative_id=alternative_id,
            started_at=self._now(),
            work=work,
        )
        self._jobs[job.id] = job
        return job

    def _read_job(self, call: _Call, kind: str | None) -> _Answer:
        job = self._jobs.get(call.params["job_id"])
        if (
            job is None
            or job.lost
            or job.owner != call.account.id
            or job.project_id != call.project_id
            or (kind is not None and job.kind != kind)
        ):
            raise _Refusal(404, {"code": "GENERATION_JOB_NOT_FOUND"})
        if self._lost.get(job.operation, 0) > 0:
            self._lost[job.operation] -= 1
            job.lost = True
            raise _Refusal(404, {"code": "GENERATION_JOB_NOT_FOUND"})
        if job.status == "RUNNING":
            job.polls += 1
            if job.polls > self.job_polls:
                self._finish(job)
            elif job.kind != "REQUEST" and job.polls * 2 > self.job_polls:
                job.stage = "VALIDATING"
        return _Answer(200, job.payload())

    def _finish(self, job: _Job) -> None:
        rules = self._job_rules.get(job.operation)
        project = self._projects.get(job.project_id)
        if rules:
            rule = rules.pop(0)
            if job.kind == "REQUEST":
                job.status = "FAILED"
                job.response = {
                    "status_code": rule.status,
                    "body": {"detail": {"code": rule.code, "stage": "MODEL_PROPOSAL"}},
                }
            else:
                if rule.rejected and project is not None:
                    with contextlib.suppress(_Refusal):
                        self._record(project, job.operation)
                self._fail_job(job, rule.code, rule.rejected)
        elif job.kind == "REQUEST":
            answer = self._request_answer(lambda: job.work(job))
            job.response = {"status_code": answer.status, "body": answer.body}
            job.status = "SUCCEEDED" if answer.status < 400 else "FAILED"
        else:
            try:
                job.result = job.work(job)
                job.status = "SUCCEEDED"
            except _JobFailure as failure:
                self._fail_job(job, failure.code, failure.rejected, failure.reasons)
        job.stage = None
        job.finished_at = self._now()

    def _fail_job(
        self,
        job: _Job,
        code: str,
        rejected: bool,
        reasons: Sequence[Mapping[str, object]] = (),
    ) -> None:
        details = [dict(reason) for reason in reasons]
        if rejected and not details:
            details = [{"code": code, "screen_code": "SCR-001", "detail": REJECTION[self.language]}]
        job.status = "REJECTED" if rejected else "FAILED"
        job.failure = {"code": code, "reasons": details}
        if rejected:
            job.attempt = 2
        if job.operation == "ITERATION":
            project = self._projects.get(job.project_id)
            if project is not None:
                for record in project.iterations:
                    if record["job_id"] == job.id:
                        record["failed"] = job.status

    def _request_answer(self, work: Callable[[], object]) -> _Answer:
        try:
            answer = work()
        except _Refusal as refusal:
            return _Answer(refusal.status, {"detail": refusal.detail})
        except _Invalid as invalid:
            return _Answer(422, {"detail": "invalid_request", "errors": invalid.errors})
        except Exception:
            self.errors.append(traceback.format_exc())
            return _Answer(500, "Internal Server Error")
        if not isinstance(answer, _Answer):
            raise TypeError("a request job must answer")
        return answer

    def _progress(self, project: FakeProject) -> tuple[str, str]:
        progress = project_progress(self._facts(project), sections=self._project_sections(project))
        return progress.current_stage.value, progress.next_action.value

    def _facts(self, project: FakeProject) -> ProjectProgressFacts:
        team = project.team
        snapshot = project.snapshot
        return ProjectProgressFacts(
            brief=_version(project.artifact("brief")),
            brief_gate=_gate_state(project.gates.get("brief")),
            team=None
            if team is None
            else TeamState(
                artifact=_artifact_version(team),
                brief=ArtifactVersion(
                    UUID(str(team["brief_version_id"])),
                    int(team["brief_version_number"]),
                    str(team["brief_content_hash"]),
                ),
                catalog=CatalogVersion(
                    int(team["catalog_version"]), str(team["catalog_content_hash"])
                ),
            ),
            team_gate=_gate_state(project.gates.get("team")),
            user_twins=None
            if snapshot is None
            else UserTwinsState(
                artifact=_artifact_version(snapshot),
                brief=_reference_version(snapshot["snapshot"]["project_brief_reference"]),
                team=_reference_version(snapshot["snapshot"]["agent_team_reference"]),
                catalog=CatalogVersion(
                    int(snapshot["snapshot"]["catalog_version"]),
                    str(snapshot["snapshot"]["catalog_content_hash"]),
                ),
            ),
            user_twins_gate=_gate_state(project.gates.get("twins")),
            requirements=_version(project.specification),
            requirements_gate=_gate_state(project.gates.get("requirements")),
            design=_version(project.design),
            design_gate=_gate_state(project.gates.get("design")),
        )

    def _approvals(self, project: FakeProject | None) -> dict[str, bool]:
        if project is None:
            return dict.fromkeys(STAGES, False)
        facts = self._facts(project)
        brief = _approves(facts.brief_gate, facts.brief)
        team_state = facts.team
        twins_state = facts.user_twins
        team = (
            brief
            and team_state is not None
            and team_state.brief == facts.brief
            and _approves(facts.team_gate, team_state.artifact)
        )
        twins = (
            brief
            and team_state is not None
            and twins_state is not None
            and _approves(facts.team_gate, team_state.artifact)
            and team_state.catalog == CURRENT_CATALOG
            and twins_state.brief == facts.brief
            and twins_state.team == team_state.artifact
            and twins_state.catalog == team_state.catalog
            and _approves(facts.user_twins_gate, twins_state.artifact)
            and self._archetypes_current(project, project.snapshot)
        )
        return {
            "brief": brief,
            "team": bool(team),
            "twins": bool(twins),
            "requirements": _approves(facts.requirements_gate, facts.requirements),
            "design": _approves(facts.design_gate, facts.design),
        }

    def _reference(self, project: FakeProject, stage: str) -> GateArtifactReference | None:
        artifact = project.artifact(stage)
        if artifact is None:
            return None
        return GateArtifactReference(
            project_id=UUID(project.id),
            gate_type=GATE_TYPES[stage],
            artifact_id=UUID(str(artifact["id"])),
            version=int(artifact["version_number"]),
            content_hash=str(artifact["content_hash"]),
        )

    def _save_gate(self, project: FakeProject, stage: str, gate: HumanGate, event: HumanGateEvent):
        project.gates[stage] = gate
        project.gate_events.setdefault(str(gate.id), []).append(event)

    def _submit_gate(
        self, project: FakeProject, stage: str, reference: GateArtifactReference
    ) -> tuple[str, HumanGate | None, list[HumanGateEvent], str | None]:
        moment = self._now()
        owner = UUID(project.account.id)
        latest = project.gates.get(stage)
        if latest is not None and latest.artifact == reference:
            if latest.status is HumanGateStatus.PENDING_APPROVAL:
                return "ALREADY_PENDING", latest, [], None
            if latest.status is HumanGateStatus.APPROVED:
                return "ALREADY_APPROVED", latest, [], None
            if latest.status is HumanGateStatus.DRAFT:
                result = transition_human_gate(
                    latest,
                    action=HumanGateAction.SUBMIT,
                    actor_user_id=owner,
                    occurred_at=moment,
                    event_id=UUID(self._new_id()),
                )
                if result.status is not HumanGateTransitionStatus.APPLIED or result.event is None:
                    return "TRANSITION_REJECTED", latest, [], _issue(result.issue)
                self._save_gate(project, stage, result.gate, result.event)
                return "SUBMITTED", result.gate, [result.event], None
            if latest.status in {
                HumanGateStatus.PAUSED,
                HumanGateStatus.CANCELLED,
                HumanGateStatus.PAUSED_NEEDS_HUMAN,
            }:
                return "GATE_BLOCKED", latest, [], None
            return NEW_ARTIFACT_REQUIRED[stage], latest, [], None
        events: list[HumanGateEvent] = []
        if latest is not None:
            if latest.status in {HumanGateStatus.CANCELLED, HumanGateStatus.PAUSED_NEEDS_HUMAN}:
                return "GATE_BLOCKED", latest, [], None
            if latest.status is not HumanGateStatus.STALE:
                stale = mark_human_gate_stale(
                    latest,
                    current_artifact=reference,
                    occurred_at=moment,
                    event_id=UUID(self._new_id()),
                )
                if stale.status is HumanGateTransitionStatus.REJECTED:
                    return "TRANSITION_REJECTED", latest, [], _issue(stale.issue)
                if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                    self._save_gate(project, stage, stale.gate, stale.event)
                    events.append(stale.event)
                    latest = stale.gate
            budget = next_human_gate_iteration(latest, project.gate_events.get(str(latest.id), ()))
            if budget is None:
                return "ITERATION_LIMIT_REACHED", latest, events, None
            iteration, limit = budget
        else:
            iteration, limit = 1, DEFAULT_GATE_ITERATION_LIMIT
        draft = create_human_gate(
            gate_id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=owner,
            gate_type=GATE_TYPES[stage],
            artifact=reference,
            iteration=iteration,
            max_iterations=limit,
            created_at=moment,
        )
        submitted = transition_human_gate(
            draft,
            action=HumanGateAction.SUBMIT,
            actor_user_id=owner,
            occurred_at=moment,
            event_id=UUID(self._new_id()),
        )
        if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
            return "TRANSITION_REJECTED", draft, events, _issue(submitted.issue)
        self._save_gate(project, stage, submitted.gate, submitted.event)
        return "SUBMITTED", submitted.gate, [*events, submitted.event], None

    def _decide_gate(
        self,
        project: FakeProject,
        stage: str,
        reference: GateArtifactReference,
        action: str,
        reason: str | None,
    ) -> tuple[str, HumanGate | None, HumanGateEvent | None, str | None]:
        gate = project.gates.get(stage)
        if gate is None:
            return "GATE_NOT_FOUND", None, None, None
        if action == "SUBMIT":
            return "REJECTED", gate, None, "INVALID_TRANSITION"
        moment = self._now()
        if gate.artifact != reference:
            stale = mark_human_gate_stale(
                gate, current_artifact=reference, occurred_at=moment, event_id=UUID(self._new_id())
            )
            if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                self._save_gate(project, stage, stale.gate, stale.event)
                return "ARTIFACT_STALE", stale.gate, stale.event, None
            if stale.status is HumanGateTransitionStatus.NO_CHANGE:
                return "ARTIFACT_STALE", gate, None, None
            return "REJECTED", gate, None, _issue(stale.issue)
        result = transition_human_gate(
            gate,
            action=HumanGateAction(action),
            actor_user_id=UUID(project.account.id),
            occurred_at=moment,
            reason=reason,
            event_id=UUID(self._new_id()),
        )
        if result.status is not HumanGateTransitionStatus.APPLIED or result.event is None:
            return "REJECTED", gate, None, _issue(result.issue)
        self._save_gate(project, stage, result.gate, result.event)
        return "APPLIED", result.gate, result.event, None

    def _approve(self, project: FakeProject, stage: str) -> None:
        reference = self._reference(project, stage)
        if reference is None:
            raise RuntimeError(f"nothing to approve at {stage}")
        self._submit_gate(project, stage, reference)
        status, _, _, issue = self._decide_gate(project, stage, reference, "APPROVE", None)
        if status != "APPLIED":
            raise RuntimeError(f"the seed could not approve {stage}: {status} {issue}")

    def _approval_issue(self, project: FakeProject, stage: str, reason: str | None) -> str | None:
        reference = self._require_reference(project, stage)
        submitted, _, _, problem = self._submit_gate(project, stage, reference)
        if submitted not in ("SUBMITTED", "ALREADY_PENDING"):
            return problem or submitted
        status, _, _, issue = self._decide_gate(project, stage, reference, "APPROVE", reason)
        return None if status == "APPLIED" else issue or status

    def _seed_approval(self, project: FakeProject, stage: str) -> None:
        issue = self._approval_issue(project, stage, None)
        if issue is not None:
            raise ValueError(f"the fake studio refuses to approve {stage}: {issue}")

    def _gate_approved(self, project: FakeProject, stage: str) -> bool:
        artifact = project.artifact(stage)
        return artifact is not None and _approves(
            _gate_state(project.gates.get(stage)), _artifact_version(artifact)
        )

    def _gate_events(self, project: FakeProject | None, stage: str, gate_id: str) -> list:
        if project is None:
            return []
        gate = project.gates.get(stage)
        known = {str(gate.id)} if gate is not None else set()
        known.update(
            identifier
            for identifier, events in project.gate_events.items()
            if events and events[0].artifact.gate_type is GATE_TYPES[stage]
        )
        if gate_id not in known:
            return []
        return [_event_payload(event) for event in project.gate_events.get(gate_id, [])]

    def _route_jobs(self, call: _Call) -> _Answer:
        status = call.value("status")
        if status is not None and status not in JOB_STATUSES:
            raise _Invalid([_error(("query", "status"), "enum")])
        jobs = [
            job
            for job in self._jobs.values()
            if job.owner == call.account.id
            and job.project_id == call.project_id
            and not job.lost
            and (status is None or job.status == status)
        ]
        jobs.sort(key=lambda job: job.started_at)
        return _Answer(200, {"items": [job.payload() for job in jobs]})

    def _route_job(self, call: _Call) -> _Answer:
        return self._read_job(call, None)


def _registered_email(email: str) -> str:
    if not isinstance(email, str) or not 3 <= len(email) <= 320:
        raise ValueError("the real Studio registers only e-mail addresses of 3 to 320 characters")
    try:
        return NormalizedEmail.parse(email).value
    except InvalidEmailAddress as error:
        reason = error.__cause__ if error.__cause__ is not None else error
        raise ValueError(
            f"the real Studio refuses {email!r} at the registration: {reason}"
        ) from error


def _issue(issue: object) -> str | None:
    return None if issue is None else str(getattr(issue, "value", issue))


def _version(artifact: Mapping[str, object] | None) -> ArtifactVersion | None:
    return None if artifact is None else _artifact_version(artifact)


def _gate_state(gate: HumanGate | None) -> GateState | None:
    if gate is None:
        return None
    return GateState(
        status=gate.status,
        artifact=ArtifactVersion(
            gate.artifact.artifact_id, gate.artifact.version, gate.artifact.content_hash
        ),
    )


def _approves(gate: GateState | None, artifact: ArtifactVersion | None) -> bool:
    return gate is not None and gate.approves(artifact)
