from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.projects.brief_dialogue import (
    ACTIVE_STATUSES,
    MAX_ANSWER_CHARACTERS,
    MAX_ANSWER_ITEMS,
    MAX_DIALOGUE_QUESTIONS,
    MAX_STATEMENT_CHARACTERS,
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
    DialogueAnswerKind,
    normalized_block,
)
from orchestwin.projects.briefs import LIST_FIELDS, BriefField, ProjectBrief, create_project_brief
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    accept_brief_assumption,
    create_brief_assumption,
    reject_brief_assumption,
)

from .common import _error, _event_payload, _gate_payload, _stamp, _submission_status
from .fields import _Fields, _gate_decision
from .values import DECISION_ACTIONS, _Answer, _BriefVersion, _Invalid, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account


QUESTIONS = {
    "it": {
        "description": "Come descriveresti il prodotto in una frase?",
        "problem": "Quale problema risolve il progetto?",
        "target_users": "Chi userà il prodotto?",
        "goals": "Quali risultati vuoi ottenere?",
        "functional_requirements": "Che cosa deve permettere di fare il prodotto?",
    },
    "en": {
        "description": "How would you describe the product in one sentence?",
        "problem": "Which problem does the project solve?",
        "target_users": "Who will use the product?",
        "goals": "Which results do you want to reach?",
        "functional_requirements": "What must the product let people do?",
    },
}
DIALOGUE_FIELDS = ("description", "problem", "target_users", "goals", "functional_requirements")
PROPOSED_FIELDS = ("non_functional_requirements", "definition_of_done")
EXTRA_QUESTIONS = {
    "it": {
        "domain": "In quale ambito lavorerà il prodotto?",
        "technical_constraints": "Ci sono vincoli tecnici da rispettare?",
        "temporal_constraints": "Entro quando deve essere pronto?",
        "budget": "Quale budget hai a disposizione?",
        "non_functional_requirements": "Quali qualità deve avere il prodotto, per esempio "
        "velocità o sicurezza?",
        "risks": "Quali rischi vedi?",
        "stakeholders": "Chi altro è coinvolto nel progetto?",
        "available_artifacts": "Hai già materiale da condividere?",
        "definition_of_done": "Quando considererai il lavoro finito?",
    },
    "en": {
        "domain": "In which domain will the product work?",
        "technical_constraints": "Are there technical constraints to respect?",
        "temporal_constraints": "By when must it be ready?",
        "budget": "Which budget is available?",
        "non_functional_requirements": "Which qualities must the product have, for example "
        "speed or security?",
        "risks": "Which risks do you see?",
        "stakeholders": "Who else is involved in the project?",
        "available_artifacts": "Do you already have material to share?",
        "definition_of_done": "When will you consider the work done?",
    },
}
ASSUMPTIONS = {
    "it": {
        "problem": "Al tavolo serve sapere in fretta quanto lasciare di mancia.",
        "target_users": "Chi paga il conto a fine cena.",
        "goals": "Calcolare la mancia in pochi secondi.",
        "functional_requirements": "Inserire l'importo e vedere subito la mancia.",
        "non_functional_requirements": "La pagina si apre in meno di due secondi da telefono.",
        "definition_of_done": "Il calcolo è verificato con tre conti reali.",
    },
    "en": {
        "problem": "At the table people need to know quickly how much to tip.",
        "target_users": "Whoever pays the bill after dinner.",
        "goals": "Work out the tip in a few seconds.",
        "functional_requirements": "Enter the amount and see the tip at once.",
        "non_functional_requirements": "The page opens in less than two seconds on a phone.",
        "definition_of_done": "The calculation is checked against three real bills.",
    },
}


class _BriefRoutes:
    def _append_brief(
        self, project: FakeProject, brief: ProjectBrief, account: _Account
    ) -> _BriefVersion:
        body: dict[str, object] = {}
        for item in BriefField:
            value = brief.value_for(item)
            body[item.value] = list(value) if isinstance(value, tuple) else value
        body["provided_fields"] = sorted(item.value for item in brief.provided_fields)
        body["unknown_fields"] = sorted(item.value for item in brief.unknown_fields)
        body["missing_fields"] = sorted(item.value for item in brief.missing_fields)
        version = _BriefVersion(
            {
                "id": self._new_id(),
                "project_id": project.id,
                "version_number": len(project.briefs) + 1,
                "schema_version": brief.SCHEMA_VERSION,
                "content_hash": brief.content_hash,
                "created_by_user_id": account.id,
                "created_at": _stamp(self._now()),
                "brief": body,
            },
            brief,
        )
        project.briefs.append(version)
        project.updated_at = self._now()
        return version

    def _route_brief_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, [version.payload for version in project.briefs])

    def _route_create_brief(self, call: _Call) -> _Answer:
        text_fields = [item.value for item in BriefField if item not in LIST_FIELDS]
        list_fields = [item.value for item in BriefField if item in LIST_FIELDS]
        fields = _Fields(call.json(), (*text_fields, *list_fields, "unknown_fields"))
        values: dict[str, object] = {}
        for name in text_fields:
            values[name] = fields.text(name, required=False, nullable=True)
        for name in list_fields:
            values[name] = fields.texts(name)
        unknown = fields.texts("unknown_fields", nullable=False, default=[]) or []
        known = {item.value for item in BriefField}
        for index, name in enumerate(unknown):
            if name not in known:
                fields.errors.append(_error(("body", "unknown_fields", index), "enum"))
        fields.check()
        if any(values.get(name) not in (None, "", []) for name in unknown):
            raise _Invalid([_error(("body",), "value_error")])
        try:
            brief = create_project_brief(
                **values, unknown_fields={BriefField(name) for name in unknown}
            )
        except (TypeError, ValueError) as error:
            raise _Refusal(422, "invalid_project_brief") from error
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        current = project.brief
        if current is not None and current.content_hash == brief.content_hash:
            return _Answer(200, current.payload)
        return _Answer(201, self._append_brief(project, brief, call.account).payload)

    def _route_current_brief(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, project.brief.payload)

    def _route_brief_version(self, call: _Call) -> _Answer:
        number = int(call.params["version_number"])
        project = self._owned(call)
        if project is None or not 1 <= number <= len(project.briefs):
            raise _Refusal(404, "project_not_found")
        return _Answer(200, project.briefs[number - 1].payload)

    def _require_dialogue_model(self) -> None:
        if not self.hosted:
            raise _Refusal(503, {"code": "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"})

    def _dialogue_answer(
        self,
        status_code: int,
        outcome: str,
        dialogue: BriefDialogue,
        version: _BriefVersion | None,
        assumptions: Sequence[BriefAssumption] = (),
    ) -> _Answer:
        brief = None if version is None else version.brief
        return _Answer(
            status_code,
            {
                "status": outcome,
                "snapshot": dialogue.to_snapshot(),
                "progress": {
                    "questions_asked": dialogue.question_count,
                    "question_limit": MAX_DIALOGUE_QUESTIONS,
                    "open_fields": []
                    if brief is None
                    else [item.value for item in dialogue.open_fields(brief)],
                    "open_essential_fields": []
                    if brief is None
                    else [item.value for item in dialogue.open_essential_fields(brief)],
                },
                "brief_version": None if version is None else version.payload,
                "assumptions": [_assumption_payload(item) for item in assumptions],
            },
        )

    def _active_dialogue(
        self, call: _Call, expected: int
    ) -> tuple[FakeProject, _BriefVersion, BriefDialogue]:
        project = self._owned(call)
        dialogue = project.dialogues[-1] if project is not None and project.dialogues else None
        if project is None or dialogue is None:
            raise _Refusal(404, {"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        version = project.brief
        if (
            dialogue.status not in ACTIVE_STATUSES
            or version is None
            or expected != dialogue.question_count
        ):
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        return project, version, dialogue

    def _ask(
        self,
        project: FakeProject,
        dialogue: BriefDialogue,
        version: _BriefVersion,
        outcome: str,
    ) -> _Answer:
        open_fields = {item.value for item in dialogue.open_fields(version.brief)}
        name = next((item for item in DIALOGUE_FIELDS if item in open_fields), None)
        if name is None:
            name = next((item for item in self._extra_fields if item in open_fields), None)
        if dialogue.questions_remaining <= 0 or name is None:
            ready = dialogue.as_ready()
            project.dialogues[-1] = ready
            return self._dialogue_answer(201, "BRIEF_DIALOGUE_READY", ready, version)
        generation = self._record(project, "BRIEF_QUESTION")
        turn = BriefDialogueTurn(
            id=UUID(self._new_id()),
            dialogue_id=dialogue.id,
            ordinal=dialogue.question_count + 1,
            field=BriefField(name),
            question={**QUESTIONS[self.language], **EXTRA_QUESTIONS[self.language]}[name],
            model_generation_id=UUID(generation),
            asked_at=self._now(),
        )
        asked = dialogue.with_question(turn)
        project.dialogues[-1] = asked
        return self._dialogue_answer(201, outcome, asked, version)

    def _route_dialogue_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or not project.dialogues:
            raise _Refusal(404, {"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        return self._dialogue_answer(
            200, "BRIEF_DIALOGUE_CURRENT", project.dialogues[-1], project.brief
        )

    def _route_dialogue_start(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("statement",))
        statement = fields.text("statement", minimum=1, maximum=MAX_STATEMENT_CHARACTERS)
        fields.check()
        self._require_dialogue_model()
        try:
            statement = normalized_block(statement, maximum=MAX_STATEMENT_CHARACTERS)
        except ValueError as error:
            raise _Refusal(422, {"code": "BRIEF_STATEMENT_INVALID"}) from error
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        latest = project.dialogues[-1] if project.dialogues else None
        if latest is not None and latest.status in ACTIVE_STATUSES:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_ACTIVE"})
        version = project.brief
        if version is None:
            version = self._append_brief(
                project, create_project_brief(description=statement), call.account
            )
        dialogue = BriefDialogue(
            id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(call.account.id),
            source_brief_version_number=version.number,
            statement=statement,
            status=BriefDialogueStatus.OPEN,
            created_at=self._now(),
        )
        project.dialogues.append(dialogue)
        return self._ask(project, dialogue, version, "BRIEF_DIALOGUE_STARTED")

    def _route_dialogue_answer(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count", "kind", "text", "items"))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        kind = fields.choice("kind", ("TEXT", "ITEM_LIST", "UNKNOWN"), literal=True)
        text = fields.text("text", required=False, nullable=True, maximum=MAX_ANSWER_CHARACTERS)
        items = fields.texts("items", maximum_items=MAX_ANSWER_ITEMS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is None:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        try:
            if kind == "TEXT":
                answer = DialogueAnswer.text_answer(text)
            elif kind == "ITEM_LIST":
                answer = DialogueAnswer.item_list(items if items is not None else [])
            else:
                answer = DialogueAnswer.unknown()
            answered = dialogue.with_answer(answer, answered_at=self._now())
        except ValueError as error:
            raise _Refusal(422, {"code": "BRIEF_ANSWER_INVALID"}) from error
        project.dialogues[-1] = answered
        return self._ask(project, answered, version, "BRIEF_QUESTION_ASKED")

    def _route_dialogue_question(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is not None:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        return self._ask(project, dialogue, version, "BRIEF_QUESTION_ASKED")

    def _route_dialogue_synthesis(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        generation = self._record(project, "BRIEF_SYNTHESIS")
        brief, proposals = self._synthesized(project, version.brief, dialogue)
        if brief.content_hash == version.content_hash:
            raise _Refusal(409, {"code": "BRIEF_SYNTHESIS_UNCHANGED"})
        created = self._append_brief(project, brief, call.account)
        moment = self._now()
        recorded = [
            create_brief_assumption(
                assumption_id=UUID(self._new_id()),
                project_id=UUID(project.id),
                brief_version_number=created.number,
                field=item,
                statement=statement,
                source=BriefAssumptionSource.MODEL_PROPOSED,
                created_by_user_id=UUID(call.account.id),
                created_at=moment,
            )
            for item, statement in proposals
        ]
        project.assumptions.extend(recorded)
        synthesized = dialogue.as_synthesized(
            resulting_brief_version_number=created.number,
            synthesis_generation_id=UUID(generation),
            completed_at=moment,
        )
        project.dialogues[-1] = synthesized
        return self._dialogue_answer(201, "BRIEF_SYNTHESIZED", synthesized, created, recorded)

    def _route_dialogue_close(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        closed = dialogue.as_closed(completed_at=self._now())
        project.dialogues[-1] = closed
        return self._dialogue_answer(200, "BRIEF_DIALOGUE_CLOSED", closed, version)

    def _synthesized(
        self, project: FakeProject, brief: ProjectBrief, dialogue: BriefDialogue
    ) -> tuple[ProjectBrief, list[tuple[BriefField, str]]]:
        answers = {
            turn.field: turn.answer
            for turn in dialogue.answered_turns
            if turn.field is not None and turn.answer is not None
        }
        texts = ASSUMPTIONS[self.language]
        values: dict[str, object] = {}
        unknown: set[BriefField] = set()
        proposals: list[tuple[BriefField, str]] = []
        for item in BriefField:
            current = brief.value_for(item)
            answer = answers.get(item)
            if item is BriefField.NAME:
                values[item.value] = current if current is not None else project.name
            elif answer is not None and answer.kind is DialogueAnswerKind.UNKNOWN:
                if current is not None:
                    values[item.value] = current
                else:
                    unknown.add(item)
                    if item.value in texts:
                        proposals.append((item, texts[item.value]))
            elif answer is not None and answer.kind is DialogueAnswerKind.TEXT:
                values[item.value] = answer.text
            elif answer is not None and answer.kind is DialogueAnswerKind.ITEM_LIST:
                values[item.value] = answer.items
            elif current is not None:
                values[item.value] = current
            else:
                unknown.add(item)
                if item.value in PROPOSED_FIELDS:
                    proposals.append((item, texts[item.value]))
        synthesized = create_project_brief(**values, unknown_fields=unknown)
        missing = synthesized.missing_fields
        if missing:
            synthesized = create_project_brief(**values, unknown_fields=unknown | missing)
        return synthesized, proposals

    def _route_assumptions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(200, [])
        return _Answer(200, [_assumption_payload(item) for item in project.assumptions])

    def _find_assumption(
        self, project: FakeProject | None, identifier: str
    ) -> tuple[int, BriefAssumption] | None:
        if project is None:
            return None
        for index, item in enumerate(project.assumptions):
            if str(item.id) == identifier:
                return index, item
        return None

    def _route_accept_assumption(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        reason = _decision_reason(reason)
        project = self._owned(call)
        found = self._find_assumption(project, call.params["assumption_id"])
        if project is None or project.brief is None or found is None:
            raise _Refusal(404, "brief_assumption_not_found")
        index, assumption = found
        current = project.brief
        if assumption.status is not BriefAssumptionStatus.PROPOSED:
            return _Answer(
                409,
                {
                    "status": "ASSUMPTION_NOT_PROPOSED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        if assumption.field in current.brief.provided_fields:
            return _Answer(
                409,
                {
                    "status": "FIELD_ALREADY_PROVIDED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        accepted = accept_brief_assumption(
            assumption,
            decided_by_user_id=UUID(call.account.id),
            decided_at=self._now(),
            reason=reason,
        )
        project.assumptions[index] = accepted
        version = self._append_brief(
            project, _with_assumption(current.brief, accepted), call.account
        )
        return _Answer(
            200,
            {
                "status": "ACCEPTED",
                "assumption": _assumption_payload(accepted),
                "brief_version": version.payload,
            },
        )

    def _route_reject_assumption(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", minimum=1, maximum=2000)
        fields.check()
        normalized = _decision_reason(reason)
        if normalized is None:
            raise _Invalid([_error(("body", "reason"), "value_error")])
        project = self._owned(call)
        found = self._find_assumption(project, call.params["assumption_id"])
        if project is None or found is None:
            raise _Refusal(404, "brief_assumption_not_found")
        index, assumption = found
        if assumption.status is not BriefAssumptionStatus.PROPOSED:
            return _Answer(
                409,
                {
                    "status": "ASSUMPTION_NOT_PROPOSED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        rejected = reject_brief_assumption(
            assumption,
            decided_by_user_id=UUID(call.account.id),
            reason=normalized,
            decided_at=self._now(),
        )
        project.assumptions[index] = rejected
        return _Answer(
            200,
            {
                "status": "REJECTED",
                "assumption": _assumption_payload(rejected),
                "brief_version": None,
            },
        )

    def _route_accept_all(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",), optional=True)
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        reason = _decision_reason(reason)
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_not_found")
        current = project.brief
        proposed = sorted(
            (
                (index, item)
                for index, item in enumerate(project.assumptions)
                if item.status is BriefAssumptionStatus.PROPOSED
            ),
            key=lambda pair: (pair[1].created_at, pair[1].field.value),
        )
        provided = current.brief.provided_fields
        updated = current.brief
        selected: list[tuple[int, BriefAssumption]] = []
        skipped: list[BriefAssumption] = []
        for index, item in proposed:
            if item.field in provided or (
                item.field not in LIST_FIELDS and item.field in updated.provided_fields
            ):
                skipped.append(item)
                continue
            updated = _with_assumption(updated, item)
            selected.append((index, item))
        if not selected:
            return _Answer(
                409,
                {
                    "status": "NOTHING_TO_ACCEPT",
                    "accepted": [],
                    "skipped": [_assumption_payload(item) for item in skipped],
                    "brief_version": None,
                },
            )
        moment = self._now()
        accepted = []
        for index, item in selected:
            decided = accept_brief_assumption(
                item, decided_by_user_id=UUID(call.account.id), decided_at=moment, reason=reason
            )
            project.assumptions[index] = decided
            accepted.append(decided)
        version = self._append_brief(project, updated, call.account)
        return _Answer(
            200,
            {
                "status": "ACCEPTED",
                "accepted": [_assumption_payload(item) for item in accepted],
                "skipped": [_assumption_payload(item) for item in skipped],
                "brief_version": version.payload,
            },
        )

    def _route_brief_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_not_found")
        missing = sorted(item.value for item in project.brief.brief.missing_fields)
        if missing:
            return _Answer(
                409,
                {
                    "status": "BRIEF_INCOMPLETE",
                    "gate": None,
                    "events": [],
                    "missing_fields": missing,
                    "issue": None,
                },
            )
        status, gate, events, issue = self._submit_gate(
            project, "brief", self._require_reference(project, "brief")
        )
        return _Answer(
            _submission_status(status),
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "missing_fields": [],
                "issue": issue,
            },
        )

    def _route_brief_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("brief")
        if gate is None:
            raise _Refusal(404, "project_brief_gate_not_found")
        return _Answer(200, _gate_payload(gate))

    def _route_brief_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, DECISION_ACTIONS, literal=True, maximum=2000)
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_gate_not_found")
        status, gate, event, issue = self._decide_gate(
            project, "brief", self._require_reference(project, "brief"), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, "project_brief_gate_not_found")
        return _Answer(
            200 if status == "APPLIED" else 409,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": issue,
            },
        )

    def _route_brief_gate_events(self, call: _Call) -> _Answer:
        return _Answer(200, self._gate_events(self._owned(call), "brief", call.params["gate_id"]))


def _decision_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = " ".join(reason.split())
    if not normalized:
        raise _Invalid([_error(("body", "reason"), "value_error")])
    return normalized


def _assumption_payload(assumption: BriefAssumption) -> dict[str, object]:
    return {
        "id": str(assumption.id),
        "project_id": str(assumption.project_id),
        "brief_version_number": assumption.brief_version_number,
        "field": assumption.field.value,
        "statement": assumption.statement,
        "source": assumption.source.value,
        "status": assumption.status.value,
        "created_by_user_id": str(assumption.created_by_user_id),
        "created_at": _stamp(assumption.created_at),
        "decided_by_user_id": None
        if assumption.decided_by_user_id is None
        else str(assumption.decided_by_user_id),
        "decided_at": None if assumption.decided_at is None else _stamp(assumption.decided_at),
        "decision_reason": assumption.decision_reason,
    }


def _with_assumption(brief: ProjectBrief, assumption: BriefAssumption) -> ProjectBrief:
    unknown = set(brief.unknown_fields)
    unknown.discard(assumption.field)
    value: object = assumption.statement
    if assumption.field in LIST_FIELDS:
        existing = brief.value_for(assumption.field)
        value = (
            (*existing, assumption.statement)
            if isinstance(existing, tuple)
            else (assumption.statement,)
        )
    return replace(brief, **{assumption.field.value: value, "unknown_fields": frozenset(unknown)})
