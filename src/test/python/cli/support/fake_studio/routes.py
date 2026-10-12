from __future__ import annotations

import re
import socketserver
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from uuid import UUID

from .common import _error
from .values import TEMPLATE_PARAMETER, _Invalid

if TYPE_CHECKING:
    from .studio import FakeStudio


PREFIX = "/api/v1"


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    path: str
    query: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    template: str
    action: str
    authenticated: bool = True


ROUTES: tuple[Route, ...] = (
    Route("GET", "/health", "health", authenticated=False),
    Route("POST", "/auth/login", "login", authenticated=False),
    Route("POST", "/auth/register", "register", authenticated=False),
    Route("POST", "/auth/refresh", "refresh", authenticated=False),
    Route("POST", "/auth/logout", "logout", authenticated=False),
    Route("GET", "/auth/mode", "access_mode", authenticated=False),
    Route("GET", "/auth/me", "me"),
    Route("GET", "/model-runtime/budget", "budget"),
    Route("GET", "/model-runtime/readiness", "readiness"),
    Route("GET", "/agent-catalog", "agent_catalog"),
    Route("POST", "/project-imports", "import_project"),
    Route("GET", "/projects", "list_projects"),
    Route("POST", "/projects", "create_project"),
    Route("GET", "/projects/{project_id}", "get_project"),
    Route("PATCH", "/projects/{project_id}", "rename_project"),
    Route("GET", "/projects/{project_id}/sections", "sections"),
    Route("GET", "/projects/{project_id}/workflow-inputs", "workflow_inputs"),
    Route("GET", "/projects/{project_id}/provided-prototypes/state", "provided_state"),
    Route("GET", "/projects/{project_id}/provided-prototypes/current", "provided_current"),
    Route("GET", "/projects/{project_id}/provided-prototypes/gate/current", "provided_gate"),
    Route(
        "GET",
        "/projects/{project_id}/provided-prototypes/{prototype_id}/document",
        "provided_document",
    ),
    Route("POST", "/projects/{project_id}/sections/alignment", "align_sections"),
    Route("GET", "/projects/{project_id}/brief-versions", "brief_history"),
    Route("POST", "/projects/{project_id}/brief-versions", "create_brief"),
    Route("GET", "/projects/{project_id}/brief-versions/current", "current_brief"),
    Route("GET", "/projects/{project_id}/brief-versions/{version_number}", "brief_version"),
    Route("GET", "/projects/{project_id}/brief-dialogue", "dialogue_current"),
    Route("POST", "/projects/{project_id}/brief-dialogue", "dialogue_start"),
    Route("POST", "/projects/{project_id}/brief-dialogue/answers", "dialogue_answer"),
    Route("POST", "/projects/{project_id}/brief-dialogue/questions", "dialogue_question"),
    Route("POST", "/projects/{project_id}/brief-dialogue/synthesis", "dialogue_synthesis"),
    Route("POST", "/projects/{project_id}/brief-dialogue/close", "dialogue_close"),
    Route("GET", "/projects/{project_id}/brief-assumptions", "assumptions"),
    Route("POST", "/projects/{project_id}/brief-assumptions/accept-all", "accept_all"),
    Route(
        "POST",
        "/projects/{project_id}/brief-assumptions/{assumption_id}/accept",
        "accept_assumption",
    ),
    Route(
        "POST",
        "/projects/{project_id}/brief-assumptions/{assumption_id}/reject",
        "reject_assumption",
    ),
    Route("POST", "/projects/{project_id}/gates/project-brief/submit", "brief_gate_submit"),
    Route("GET", "/projects/{project_id}/gates/project-brief/current", "brief_gate_current"),
    Route("POST", "/projects/{project_id}/gates/project-brief/decisions", "brief_gate_decision"),
    Route(
        "GET", "/projects/{project_id}/gates/project-brief/{gate_id}/events", "brief_gate_events"
    ),
    Route("POST", "/projects/{project_id}/team-proposals", "team_proposal"),
    Route("GET", "/projects/{project_id}/team-proposals", "team_history"),
    Route("GET", "/projects/{project_id}/team-proposals/current", "team_current"),
    Route("PATCH", "/projects/{project_id}/team-proposals/current", "team_edit"),
    Route("GET", "/projects/{project_id}/readiness", "team_readiness"),
    Route("GET", "/projects/{project_id}/team/context-alignment", "team_alignment"),
    Route("POST", "/projects/{project_id}/team/context-alignment", "realign_team"),
    Route("POST", "/projects/{project_id}/gates/agent-team/submit", "team_gate_submit"),
    Route("GET", "/projects/{project_id}/gates/agent-team/current", "team_gate_current"),
    Route("POST", "/projects/{project_id}/gates/agent-team/decisions", "team_gate_decision"),
    Route("GET", "/projects/{project_id}/gates/agent-team/{gate_id}/events", "team_gate_events"),
    Route("GET", "/projects/{project_id}/user-modeling/personas", "personas"),
    Route("GET", "/projects/{project_id}/user-modeling/archetypes", "archetypes"),
    Route("POST", "/projects/{project_id}/user-modeling/archetypes", "archetype_create"),
    Route(
        "PATCH", "/projects/{project_id}/user-modeling/archetypes/{persona_id}", "archetype_edit"
    ),
    Route(
        "DELETE",
        "/projects/{project_id}/user-modeling/archetypes/{persona_id}",
        "archetype_archive",
    ),
    Route("POST", "/projects/{project_id}/user-modeling/personas/proposals", "persona_proposals"),
    Route(
        "POST",
        "/projects/{project_id}/user-modeling/personas/{persona_id}/decision",
        "persona_decision",
    ),
    Route("POST", "/projects/{project_id}/user-modeling/snapshots/generate", "twins_generate"),
    Route("GET", "/projects/{project_id}/user-modeling/snapshots/current", "snapshot_current"),
    Route("GET", "/projects/{project_id}/user-modeling/snapshots", "snapshot_history"),
    Route("GET", "/projects/{project_id}/user-modeling/readiness", "modeling_readiness"),
    Route("POST", "/projects/{project_id}/user-modeling/gate/submit", "twins_gate_submit"),
    Route("POST", "/projects/{project_id}/user-modeling/gate/decision", "twins_gate_decision"),
    Route("GET", "/projects/{project_id}/user-modeling/gate", "twins_gate_current"),
    Route("GET", "/projects/{project_id}/user-modeling/gate/events", "twins_gate_events"),
    Route("GET", "/projects/{project_id}/user-modeling/context-alignment", "twins_alignment"),
    Route("POST", "/projects/{project_id}/user-modeling/context-alignment", "realign_twins"),
    Route(
        "POST", "/projects/{project_id}/user-modeling/twins/{twin_id}/revisions", "twin_revision"
    ),
    Route(
        "POST",
        "/projects/{project_id}/user-modeling/revisions/{diff_id}/decision",
        "twin_revision_decision",
    ),
    Route("GET", "/projects/{project_id}/user-twins/{twin_id}/conversation", "conversation"),
    Route(
        "POST",
        "/projects/{project_id}/user-twins/{twin_id}/conversation/turns",
        "conversation_turn",
    ),
    Route("POST", "/projects/{project_id}/requirements/proposals", "requirements_proposal"),
    Route("GET", "/projects/{project_id}/requirements/current", "requirements_current"),
    Route("GET", "/projects/{project_id}/requirements", "requirements_history"),
    Route("GET", "/projects/{project_id}/requirements/readiness", "requirements_readiness"),
    Route("POST", "/projects/{project_id}/requirements/change-requests", "requirements_change"),
    Route("POST", "/projects/{project_id}/requirements/revisions", "requirements_revise"),
    Route("GET", "/projects/{project_id}/requirements/revisions", "requirements_revisions"),
    Route(
        "GET", "/projects/{project_id}/requirements/revisions/{diff_id}", "requirements_revision"
    ),
    Route(
        "POST",
        "/projects/{project_id}/requirements/revisions/{diff_id}/decision",
        "requirements_revision_decision",
    ),
    Route("POST", "/projects/{project_id}/requirements/gate/submit", "requirements_gate_submit"),
    Route(
        "POST", "/projects/{project_id}/requirements/gate/decision", "requirements_gate_decision"
    ),
    Route("GET", "/projects/{project_id}/requirements/gate", "requirements_gate_current"),
    Route("GET", "/projects/{project_id}/requirements/gate/events", "requirements_gate_events"),
    Route("GET", "/projects/{project_id}/requirements/twin-alignment", "requirements_alignment"),
    Route("POST", "/projects/{project_id}/requirements/twin-alignment", "realign_requirements"),
    Route("POST", "/projects/{project_id}/design/proposals", "design_proposal"),
    Route("POST", "/projects/{project_id}/design/regenerations", "design_regeneration"),
    Route("GET", "/projects/{project_id}/design/current", "design_current"),
    Route("GET", "/projects/{project_id}/design", "design_history"),
    Route("GET", "/projects/{project_id}/design/readiness", "design_readiness"),
    Route("GET", "/projects/{project_id}/design/distance", "design_distance"),
    Route("POST", "/projects/{project_id}/design/revisions", "design_revision"),
    Route("GET", "/projects/{project_id}/design/revisions", "design_revisions"),
    Route("GET", "/projects/{project_id}/design/revisions/{diff_id}", "design_revision_view"),
    Route(
        "POST",
        "/projects/{project_id}/design/revisions/{diff_id}/decision",
        "design_revision_decision",
    ),
    Route("POST", "/projects/{project_id}/design/revisions/restore", "design_restore"),
    Route("POST", "/projects/{project_id}/design/change-requests", "design_change"),
    Route("POST", "/projects/{project_id}/design/gate/submit", "design_gate_submit"),
    Route("POST", "/projects/{project_id}/design/gate/decision", "design_gate_decision"),
    Route("GET", "/projects/{project_id}/design/gate", "design_gate_current"),
    Route("GET", "/projects/{project_id}/design/gate/events", "design_gate_events"),
    Route("GET", "/projects/{project_id}/design/requirements-alignment", "design_alignment"),
    Route("POST", "/projects/{project_id}/design/requirements-alignment", "realign_design"),
    Route("POST", "/projects/{project_id}/design/mockups", "mockup_generate"),
    Route("GET", "/projects/{project_id}/design/mockups", "mockup_latest"),
    Route("GET", "/projects/{project_id}/design/mockups/capabilities", "mockup_capabilities"),
    Route("POST", "/projects/{project_id}/design/mockups/jobs", "mockup_job"),
    Route("GET", "/projects/{project_id}/design/mockups/jobs/{job_id}", "mockup_job_view"),
    Route("GET", "/projects/{project_id}/design/mockups/document", "mockup_document"),
    Route("POST", "/projects/{project_id}/design/iterations/jobs", "iteration_job"),
    Route("GET", "/projects/{project_id}/design/iterations/jobs/{job_id}", "iteration_job_view"),
    Route("GET", "/projects/{project_id}/design/iterations", "iterations"),
    Route("POST", "/projects/{project_id}/design/evaluations", "evaluation"),
    Route("GET", "/projects/{project_id}/design/evaluations", "evaluations"),
    Route("GET", "/projects/{project_id}/design/evaluations/comparison", "comparison"),
    Route("GET", "/projects/{project_id}/design/evaluations/{run_id}/pins", "review_pins"),
    Route("GET", "/projects/{project_id}/design/evaluations/{run_id}/document", "review_document"),
    Route("POST", "/projects/{project_id}/design/opinions", "opinion"),
    Route("GET", "/projects/{project_id}/design/opinions", "opinions"),
    Route("POST", "/projects/{project_id}/design/critiques/sources", "critique_upload"),
    Route("GET", "/projects/{project_id}/design/critiques/sources", "critique_sources"),
    Route(
        "GET",
        "/projects/{project_id}/design/critiques/sources/{source_id}/shots/{code}",
        "critique_shot",
    ),
    Route("POST", "/projects/{project_id}/design/critiques", "critique_run"),
    Route("GET", "/projects/{project_id}/design/critiques", "critique_runs"),
    Route("GET", "/projects/{project_id}/generation-jobs", "jobs"),
    Route("GET", "/projects/{project_id}/generation-jobs/{job_id}", "job"),
    Route("POST", "/projects/{project_id}/knowledge-packages", "publish"),
    Route("GET", "/projects/{project_id}/knowledge-packages", "package_history"),
    Route(
        "GET",
        "/projects/{project_id}/knowledge-packages/{version_number}/archive",
        "package_archive",
    ),
    Route("GET", "/projects/{project_id}/import", "import_origin"),
    Route("GET", "/projects/{project_id}/model-usage", "usage"),
    Route("GET", "/projects/{project_id}/alignment", "alignment"),
    Route("POST", "/projects/{project_id}/code-changes", "record_change"),
    Route("GET", "/projects/{project_id}/code-changes", "changes"),
    Route("GET", "/projects/{project_id}/code-changes/{commit}", "change"),
    Route("POST", "/projects/{project_id}/code-changes/{commit}/reviews", "review_change"),
    Route("GET", "/projects/{project_id}/code-changes/{commit}/reviews", "change_reviews"),
    Route("POST", "/projects/{project_id}/code-changes/{commit}/decision", "decide_change"),
    Route("POST", "/projects/{project_id}/alignment/runs", "alignment_run"),
    Route("GET", "/projects/{project_id}/alignment/runs", "alignment_runs"),
    Route("GET", "/projects/{project_id}/alignment/runs/{run_id}", "alignment_run_view"),
    Route("GET", "/projects/{project_id}/alignment/proposals", "alignment_proposals"),
    Route("POST", "/projects/{project_id}/alignment/proposals/{code}/apply", "apply_proposal"),
    Route("POST", "/projects/{project_id}/alignment/proposals/{code}/skip", "skip_proposal"),
    Route("GET", "/projects/{project_id}/acceptance-tests", "acceptance_tests"),
    Route("POST", "/projects/{project_id}/test-plans", "plan_tests"),
    Route("GET", "/projects/{project_id}/test-plans", "test_plans"),
    Route("GET", "/projects/{project_id}/test-plans/{plan_id}", "test_plan"),
    Route("POST", "/projects/{project_id}/test-runs", "record_test_run"),
    Route("GET", "/projects/{project_id}/test-runs", "test_runs"),
    Route("GET", "/projects/{project_id}/test-runs/{run_id}", "test_run"),
    Route("POST", "/projects/{project_id}/test-runs/{run_id}/reviews", "review_test_run"),
    Route("GET", "/projects/{project_id}/test-runs/{run_id}/reviews", "test_run_reviews"),
    Route("GET", "/projects/{project_id}/code-tasks", "code_tasks"),
    Route("POST", "/projects/{project_id}/code-tasks", "create_tasks"),
    Route("POST", "/projects/{project_id}/code-tasks/{code}/status", "task_status"),
    Route("GET", "/projects/{project_id}/twin-learning", "twin_learning"),
    Route("GET", "/projects/{project_id}/artifacts/why", "why"),
    Route("GET", "/projects/{project_id}/validation", "validation"),
    Route("GET", "/projects/{project_id}/validation/walkthrough", "validation_walkthrough"),
    Route("GET", "/projects/{project_id}/artifacts/why/document", "why_document"),
    Route("GET", "/projects/{project_id}/evidence", "evidence_list"),
    Route("POST", "/projects/{project_id}/evidence", "evidence_add"),
    Route("GET", "/projects/{project_id}/evidence/{evidence_id}", "evidence_show"),
    Route("POST", "/projects/{project_id}/evidence/{evidence_id}/versions", "evidence_revise"),
    Route("POST", "/projects/{project_id}/evidence/{evidence_id}/retire", "evidence_retire"),
    Route("DELETE", "/projects/{project_id}/evidence/{evidence_id}/text", "evidence_delete"),
    Route("PUT", "/projects/{project_id}/evidence/{evidence_id}/text", "evidence_associate"),
    Route("POST", "/projects/{project_id}/user-twins/{twin_id}/updates", "propose_update"),
    Route("GET", "/projects/{project_id}/twin-updates/{update_id}", "twin_update"),
    Route("POST", "/projects/{project_id}/twin-updates/{update_id}/decision", "decide_update"),
    Route("POST", "/projects/{project_id}/user-twins/{twin_id}/observations", "learn"),
    Route(
        "POST",
        "/projects/{project_id}/user-twins/{twin_id}/observations/{code}/retire",
        "retire_observation",
    ),
    Route("GET", "/projects/{project_id}/activity", "activity"),
    Route("GET", "/projects/{project_id}/activity/session", "activity_session"),
    Route("POST", "/projects/{project_id}/activity/sessions", "activity_start"),
    Route("POST", "/projects/{project_id}/activity/sessions/{session_code}/end", "activity_end"),
    Route("POST", "/projects/{project_id}/activity/events", "activity_events"),
)


def route_table() -> tuple[tuple[str, str], ...]:
    return tuple((route.method, PREFIX + route.template) for route in ROUTES)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    block_on_close = True

    def __init__(self, studio: FakeStudio) -> None:
        self.studio = studio
        super().__init__(("127.0.0.1", 0), _Handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def handle_error(self, request: object, client_address: object) -> None:
        self.studio._record_error(traceback.format_exc())


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeStudio/1"
    sys_version = ""
    timeout = 30

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _serve(self) -> None:
        length = self.headers.get("Content-Length", "0")
        size = int(length) if length.isdecimal() else 0
        raw = self.rfile.read(size) if size > 0 else b""
        headers = {name.lower(): value for name, value in self.headers.items()}
        studio = self.server.studio
        answer = studio._handle(self.command, self.path, headers, raw)
        content = answer.content()
        self.send_response(answer.status)
        self.send_header("Content-Type", answer.content_type)
        if answer.status != 204:
            self.send_header("Content-Length", str(len(content)))
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if content:
            self.wfile.write(content)
        self.close_connection = True

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve


def _compile(template: str) -> re.Pattern[str]:
    return re.compile(TEMPLATE_PARAMETER.sub(r"(?P<\1>[^/]+)", template))


def _path_parameters(values: Mapping[str, str]) -> dict[str, str]:
    errors = []
    parsed: dict[str, str] = {}
    for name, value in values.items():
        if name == "version_number":
            if re.fullmatch(r"[+-]?[0-9]+", value) is None:
                errors.append(_error(("path", name), "int_parsing"))
            else:
                parsed[name] = str(int(value))
            continue
        if name in ("commit", "code", "session_code"):
            parsed[name] = value
            continue
        try:
            parsed[name] = str(UUID(value))
        except ValueError:
            errors.append(_error(("path", name), "uuid_parsing"))
    if errors:
        raise _Invalid(errors)
    return parsed


def _prefers_async(header: str | None) -> bool:
    if not header:
        return False
    return any(
        item.split(";", 1)[0].split("=", 1)[0].strip().lower() == "respond-async"
        for item in header.split(",")
    )


def _bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    return token
