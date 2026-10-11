from __future__ import annotations

import copy
import email.parser
import email.policy
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.visual_catalog import VisualChoices

from .common import _stamp
from .fields import _Fields
from .values import _Answer, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


MAX_SOURCE_NAME = 200
MAX_PROJECT_NAME = 120
PROJECT_MODES = ("GREENFIELD_GENERATION", "BROWNFIELD_ASSESSMENT")
GESTURE_ISSUES = {
    "USER_TWIN_REVISION_PENDING": "REVISION_PENDING",
    "REQUIREMENTS_REVISION_PENDING": "REVISION_PENDING",
    "DESIGN_REVISION_PENDING": "REVISION_PENDING",
    "BRIEF_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "TEAM_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "USER_TWINS_REQUIRED": "UPSTREAM_NOT_READY",
    "USER_TWINS_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "REQUIREMENTS_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
}
SEED_BRIEF = {
    "it": {
        "description": "Una pagina web che calcola la mancia e divide il conto tra i commensali.",
        "problem": "Al tavolo nessuno sa quanto lasciare di mancia e dividere il conto è lento.",
        "goals": ("Calcolare la mancia in pochi secondi", "Dividere il conto in parti uguali"),
        "functional_requirements": (
            "Inserire l'importo del conto",
            "Scegliere la percentuale di mancia",
            "Vedere la quota di ogni persona",
        ),
        "domain": "Ristorazione",
    },
    "en": {
        "description": "A web page that works out the tip and splits the bill among diners.",
        "problem": "At the table nobody knows how much to tip and splitting the bill is slow.",
        "goals": ("Work out the tip in a few seconds", "Split the bill in equal shares"),
        "functional_requirements": (
            "Enter the amount of the bill",
            "Choose the tip percentage",
            "See the share of each person",
        ),
        "domain": "Restaurants",
    },
}


class _ProjectRoutes:
    def _project_payload(self, project: FakeProject) -> dict[str, object]:
        stage, action = self._progress(project)
        return {
            "id": project.id,
            "display_name": project.name,
            "mode": project.mode,
            "current_brief_version": len(project.briefs),
            "is_archived": False,
            "created_at": _stamp(project.created_at),
            "updated_at": _stamp(project.updated_at),
            "current_stage": stage,
            "next_action": action,
        }

    def _route_list_projects(self, call: _Call) -> _Answer:
        owned = [
            project for project in self._projects.values() if project.account.id == call.account.id
        ]
        owned.sort(key=lambda project: (-project.created_at.timestamp(), project.id))
        return _Answer(200, [self._project_payload(project) for project in owned])

    def _route_create_project(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("display_name", "mode"))
        name = fields.text("display_name", minimum=1, maximum=MAX_PROJECT_NAME)
        mode = fields.choice("mode", PROJECT_MODES)
        fields.check()
        normalized = " ".join((name or "").split())
        if not normalized:
            raise _Refusal(422, "invalid_project")
        project = self._new_project(call.account, normalized, mode or PROJECT_MODES[0])
        return _Answer(201, self._project_payload(project))

    def _route_get_project(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, self._project_payload(project))

    def seed_workflow_inputs(
        self, project, *, decisions=(), prototypes=(), gate=None, context_current=True
    ):
        from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
        from orchestwin.workflow_inputs import workflow_records

        envelope = workflow_records(project.id, decisions=decisions, prototypes=prototypes)
        for item in envelope["prototypes"]:
            provided_prototype_from_snapshot(item)
        project.workflow_decisions = copy.deepcopy(envelope["decisions"])
        project.provided_prototypes = copy.deepcopy(envelope["prototypes"])
        project.provided_gate = copy.deepcopy(gate)
        project.provided_context_current = context_current

    def _workflow_inputs(self, project):
        from orchestwin.workflow_inputs import workflow_records

        return workflow_records(project.id, project.workflow_decisions, project.provided_prototypes)

    def _provided_guard(self, call, action):
        from orchestwin.workflow_inputs import (
            PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE,
            PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
            PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
            PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE,
        )

        if "project_id" not in call.params:
            return
        project = self._owned(call)
        if project is None or not project.provided_prototypes:
            return
        code = None
        if action == "validation_walkthrough":
            code = PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE
        elif call.method != "GET" and "/design/" in call.path:
            if action == "evaluation":
                code = PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE
            elif action.startswith("design_revision"):
                code = PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE
            else:
                code = PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE
        if code is not None:
            raise _Refusal(409, {"code": code})

    def _route_workflow_inputs(self, call):
        return _Answer(200, self._workflow_inputs(self._code_project(call)))

    def _route_provided_state(self, call):
        project = self._code_project(call)
        if not project.provided_prototypes:
            return _Answer(
                200,
                {
                    "source": "EXPLORATION" if project.design else "NONE",
                    "approved": False,
                    "context_current": True,
                    "limits": [],
                },
            )
        return _Answer(
            200,
            {
                "source": "PROVIDED_PROTOTYPE",
                "prototype": copy.deepcopy(project.provided_prototypes[-1]),
                "gate": copy.deepcopy(project.provided_gate),
                "approved": bool(
                    project.provided_gate and project.provided_gate.get("status") == "APPROVED"
                ),
                "context_current": project.provided_context_current,
                "limits": self._workflow_inputs(project)["limits"],
            },
        )

    def _route_provided_current(self, call):
        project = self._code_project(call)
        if not project.provided_prototypes:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_NOT_FOUND"})
        return _Answer(200, copy.deepcopy(project.provided_prototypes[-1]))

    def _route_provided_gate(self, call):
        project = self._code_project(call)
        if project.provided_gate is None:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_GATE_NOT_FOUND"})
        return _Answer(200, copy.deepcopy(project.provided_gate))

    def _route_provided_document(self, call):
        from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
        from orchestwin.artifacts.visual_catalog import resolve_visual_tokens

        project = self._code_project(call)
        snapshot = next(
            (
                item
                for item in reversed(project.provided_prototypes)
                if item["id"] == call.params["prototype_id"]
            ),
            None,
        )
        if snapshot is None:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_NOT_FOUND"})
        prototype = provided_prototype_from_snapshot(snapshot)
        document = mockup_document(
            prototype.mockup.mockup,
            tokens=resolve_visual_tokens(VisualChoices.from_snapshot(prototype.visual_choices)),
            language="en",
            entry_screen=call.query.get("entry_screen", ["SCR-001"])[0],
        )
        return _Answer(200, {"html": document, "title": prototype.title})

    def _route_rename_project(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("display_name",))
        name = fields.text("display_name", minimum=1, maximum=MAX_PROJECT_NAME)
        fields.check()
        normalized = " ".join((name or "").split())
        if not normalized:
            raise _Refusal(422, "invalid_project")
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        project.name = normalized
        project.updated_at = self._now()
        return _Answer(200, self._project_payload(project))


def _gesture_issue(code: str) -> str:
    return GESTURE_ISSUES.get(code, code)


def _alignment_result(
    key: str,
    outcome: str,
    *,
    issue: str | None = None,
    version_number: int | None = None,
    codes: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "outcome": outcome,
        "issue": issue,
        "version_number": version_number,
        "codes": list(codes),
    }


def _gesture_status(results: Sequence[Mapping[str, object]]) -> str:
    outcomes = [result["outcome"] for result in results]
    if "ALIGNED" not in outcomes:
        return "NOTHING_TO_ALIGN"
    return "PARTIAL" if "BLOCKED" in outcomes else "ALIGNED"


def _refusal_code(refusal: _Refusal) -> tuple[str, list[str]]:
    detail = refusal.detail
    if isinstance(detail, Mapping):
        return str(detail.get("code")), [str(code) for code in detail.get("missing_codes", ())]
    return str(detail), []


def _multipart(content_type: str, body: bytes) -> dict[str, tuple[str | None, bytes]]:
    if not content_type.lower().startswith("multipart/form-data"):
        return {}
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        return {}
    fields: dict[str, tuple[str | None, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True)
        fields[name] = (part.get_filename(), payload if isinstance(payload, bytes) else b"")
    return fields
