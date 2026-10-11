from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.knowledge.state import (
    MAX_LEARNED_OBSERVATIONS,
    MAX_OBSERVATION_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MAX_UPDATE_CHANGES,
    MAX_UPDATE_OBSERVATIONS,
    MAX_UPDATE_TESTS,
    OBSERVATION_CODE_PREFIX,
    UPDATE_DECISIONS,
)
from orchestwin.models.evidence_update import EvidenceUpdateOutput, evidence_update_context
from orchestwin.projects.evidence_application import apply_evidence_change, evidence_profile
from orchestwin.projects.research_evidence import EvidenceChange, EvidenceStatus, EvidenceVersion
from orchestwin.twins.epistemics import EvidenceSourceKind

from .. import fake_studio as package
from .common import (
    _code_number,
    _critique_of,
    _distinct,
    _fake_twin_profile,
    _items_value,
    _model_rule,
    _models,
    _optional_line,
    _single_line,
)
from .fields import _Fields
from .texts import COSTS
from .values import DEFAULT_LOCALE, LOCALE_PATTERN, MAX_LOCALE_LENGTH, _Answer, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


OBSERVATION_CODE = re.compile(r"OBS-[0-9]{3,6}", re.IGNORECASE)
REQUIREMENT_REFERENCE = re.compile(r"REQ-[0-9]{3,6}")
SCREEN_REFERENCE = re.compile(r"SCR-[0-9]{3,6}")
UPDATE_FIELDS = ("locale", "evidence_id", "evidence_version")
UPDATE_DECISION_FIELDS = ("decision", "kept", "reason")
KEPT_FIELDS = ("index", "statement")
OBSERVATION_FIELDS = ("statement", "about")
ABOUT_FIELDS = ("requirement", "screen")
RETIRE_FIELDS = ("reason",)
PROPOSED_OBSERVATIONS = 2
MAX_OBSERVATION_NUMBER = 999_999
UNKNOWN_INDEX = "the proposal has no observation at this index"
LEARNING_TEXTS = {
    "it": {
        "tests": "Un rilievo sulla verifica dei criteri.",
        "commit": "Un rilievo sul commit {commit}.",
        "learned": "Dalle ultime critiche ho imparato {count} cose sul mio gruppo.",
        "nothing": "Le ultime critiche non mi insegnano nulla di nuovo.",
    },
    "en": {
        "tests": "A finding on the acceptance tests.",
        "commit": "A finding on the commit {commit}.",
        "learned": "From the latest critiques I learned {count} things about my group.",
        "nothing": "The latest critiques teach me nothing new.",
    },
}


class _LearningRoutes:
    def _learning_entry(
        self, project: FakeProject, twin: Mapping[str, object]
    ) -> dict[str, object]:
        twin_id = str(twin["twin_id"])
        version = int(twin["version_number"])
        development = project.development.get(twin_id, 0)
        own = [item for item in project.learned if item["twin_id"] == twin_id]
        retired = sorted(
            (item for item in own if item["retired"] is not None),
            key=lambda item: (
                int(item["retired"]["retired_in_version"]),
                _code_number(item["code"]),
            ),
        )
        return {
            "twin_id": twin_id,
            "twin_name": str(twin["profile"]["name"]),
            "profile_version_number": version,
            "development_version_number": development,
            "label": f"{version}.{development}",
            "observations": [_active_entry(item) for item in own if item["retired"] is None],
            "retired": [_retired_entry(item) for item in retired],
        }

    def _learning_entries(self, project: FakeProject) -> list[dict[str, object]]:
        return [self._learning_entry(project, twin) for twin in self._approved_twins(project)]

    def _learning_twin(self, project: FakeProject, twin_id: str) -> dict[str, object]:
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        twin = next((item for item in twins if item["twin_id"] == twin_id), None)
        if twin is None:
            raise _Refusal(404, {"code": "USER_TWIN_NOT_FOUND"})
        return twin

    def _pending_update(self, project: FakeProject, twin_id: str) -> dict[str, object] | None:
        return next(
            (
                update
                for update in project.updates
                if update["twin_id"] == twin_id and update["status"] == "PROPOSED"
            ),
            None,
        )

    def _refuse_pending(self, project: FakeProject, twin_id: str) -> None:
        pending = self._pending_update(project, twin_id)
        if pending is not None:
            raise _Refusal(409, {"code": "TWIN_UPDATE_PENDING", "update_id": pending["id"]})

    def _active_count(self, project: FakeProject, twin_id: str) -> int:
        return sum(
            1 for item in project.learned if item["twin_id"] == twin_id and item["retired"] is None
        )

    def _new_material(
        self, project: FakeProject, twin_id: str
    ) -> tuple[list[tuple[dict, dict]], list[tuple[dict, dict]]]:
        latest = next((update for update in project.updates if update["twin_id"] == twin_id), None)
        since = None if latest is None else datetime.fromisoformat(str(latest["created_at"]))
        changes = []
        for record in project.code_changes:
            run = self._latest_run(project, record["commit"])
            critique = None if run is None else _critique_of(run, twin_id)
            if critique is not None and _after(run["reviewed_at"], since):
                changes.append((run, critique))
        tests = []
        for record in project.acceptance_runs:
            review = self._latest_test_review(project, record["id"])
            critique = None if review is None else _critique_of(review, twin_id)
            if critique is not None and _after(review["reviewed_at"], since):
                tests.append((review, critique))
        changes.sort(key=_critique_moment, reverse=True)
        tests.sort(key=_critique_moment, reverse=True)
        return changes, tests

    def _proposal(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        changes: Sequence[tuple[dict, dict]],
        tests: Sequence[tuple[dict, dict]],
        language: str,
    ) -> list[dict[str, object]]:
        texts = LEARNING_TEXTS[language]
        name = str(twin["profile"]["name"])
        seen = {
            _comparable(str(item["statement"]))
            for item in project.learned
            if item["twin_id"] == twin["twin_id"] and item["retired"] is None
        }
        candidates = [
            *(
                (finding, texts["tests"])
                for _, critique in tests
                for finding in critique["findings"]
            ),
            *(
                (finding, texts["commit"].format(commit=str(run["commit"])[:8]))
                for run, critique in changes
                for finding in critique["findings"]
            ),
        ]
        observations: list[dict[str, object]] = []
        for finding, basis in candidates:
            statement = _cut_line(f"{name}: {finding['text']}", MAX_OBSERVATION_LENGTH)
            if _comparable(statement) in seen:
                continue
            seen.add(_comparable(statement))
            about = finding["about"]
            observations.append(
                {
                    "index": len(observations),
                    "statement": statement,
                    "basis": basis,
                    "about": {
                        "requirement": about.get("requirement"),
                        "screen": about.get("screen"),
                    },
                    "contradicts_profile": None,
                }
            )
            if len(observations) == PROPOSED_OBSERVATIONS:
                break
        return observations

    def _update_of(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        locale: str,
        observations: Sequence[Mapping[str, object]],
        material: Mapping[str, int],
        cost: int,
    ) -> dict[str, object]:
        texts = LEARNING_TEXTS[_locale_language(locale)]
        twin_id = str(twin["twin_id"])
        return {
            "id": self._new_id(),
            "twin_id": twin_id,
            "twin_name": str(twin["profile"]["name"]),
            "created_at": _iso(self._now()),
            "locale": locale,
            "status": "PROPOSED" if observations else "EMPTY",
            "base": {
                "profile_version_number": int(twin["version_number"]),
                "development_version_number": project.development.get(twin_id, 0),
            },
            "comment": texts["learned"].format(count=len(observations))
            if observations
            else texts["nothing"],
            "observations": [copy.deepcopy(dict(item)) for item in observations],
            "material": dict(material),
            "decision": None,
            "cost_microusd": cost,
        }

    def _add_observation(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        observation: Mapping[str, object],
        *,
        source: str,
        version: int,
        moment: str,
        update_id: str | None,
    ) -> None:
        about = observation.get("about") or {}
        project.learned.append(
            {
                "twin_id": str(twin["twin_id"]),
                "code": f"{OBSERVATION_CODE_PREFIX}-{len(project.learned) + 1:03d}",
                "statement": observation["statement"],
                "basis": observation.get("basis"),
                "source": source,
                "about": {"requirement": about.get("requirement"), "screen": about.get("screen")},
                "contradicts_profile": observation.get("contradicts_profile"),
                "added_in_version": version,
                "approved_at": moment,
                "update_id": update_id,
                "retired": None,
            }
        )

    def _find_update(self, project: FakeProject, update_id: str) -> dict[str, object]:
        update = next((item for item in project.updates if item["id"] == update_id), None)
        if update is None:
            raise _Refusal(404, {"code": "TWIN_UPDATE_NOT_FOUND"})
        return update

    def _named_twin(
        self, project: FakeProject, twin_id: str, name: object, version: object
    ) -> dict[str, object]:
        twin = next(
            (item for item in self._approved_twins(project) if item["twin_id"] == twin_id), None
        )
        if twin is not None:
            return twin
        return {"twin_id": twin_id, "version_number": version, "profile": {"name": name}}

    def _route_twin_learning(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        twins = []
        for twin in self._approved_twins(project):
            twin_id = str(twin["twin_id"])
            changes, tests = self._new_material(project, twin_id)
            pending = self._pending_update(project, twin_id)
            twins.append(
                {
                    **self._learning_entry(project, twin),
                    "pending_update": None if pending is None else copy.deepcopy(pending),
                    "new_material": {"changes": len(changes), "tests": len(tests)},
                }
            )
        return _Answer(
            200, {"project_id": project.id, "update_available": self.hosted, "twins": twins}
        )

    def _route_propose_update(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), UPDATE_FIELDS)
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        source_id = fields.identifier("evidence_id", required=False, nullable=True)
        source_version = fields.integer("evidence_version", required=False, minimum=1)
        fields.check()
        return self._later(
            call,
            "TWIN_UPDATE",
            {
                "locale": locale,
                **(
                    {"evidence_id": source_id, "evidence_version": source_version}
                    if source_id is not None
                    else {}
                ),
            },
            lambda: self._proposed_update(
                call, str(locale), evidence_id=source_id, evidence_version=source_version
            ),
        )

    def _proposed_update(
        self, call: _Call, locale: str, *, evidence_id=None, evidence_version=None
    ) -> _Answer:
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        if evidence_id is not None:
            return self._proposed_evidence_update(
                project, twin, locale, evidence_id, evidence_version
            )
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twin_id = str(twin["twin_id"])
        self._refuse_pending(project, twin_id)
        changes, tests = self._new_material(project, twin_id)
        if not changes and not tests:
            raise _Refusal(409, {"code": "TWIN_UPDATE_NOTHING_NEW"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_UPDATE_MODEL_NOT_CONFIGURED"})
        self._record(project, "TWIN_UPDATE")
        changes, tests = changes[:MAX_UPDATE_CHANGES], tests[:MAX_UPDATE_TESTS]
        observations = self._proposal(project, twin, changes, tests, _locale_language(locale))
        update = self._update_of(
            project,
            twin,
            locale,
            observations,
            {"changes": len(changes), "tests": len(tests)},
            COSTS["TWIN_UPDATE"],
        )
        project.updates.insert(0, update)
        return _Answer(201, {"status": "PROPOSED", "update": copy.deepcopy(update)})

    def _proposed_evidence_update(self, project, twin, locale, source_id, source_version):
        self._refuse_pending(project, str(twin["twin_id"]))
        source = self._evidence_source(project, source_id, source_version)
        latest = self._evidence_source(project, source_id)
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        if source["version"] != latest["version"]:
            raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
        text = project.evidence_texts.get((source_id, source["version"]))
        if text is None:
            raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_UPDATE_MODEL_NOT_CONFIGURED"})
        it = _locale_language(locale) == "it"
        passages = [(index, line) for index, line in enumerate(text.split("\n"), 1) if line.strip()]
        candidates = []
        fields = ("goals", "context_of_use", "preferred_vocabulary")
        effects = ("SUPPORTS", "CONTRADICTS", "ADDS")
        current = {
            item["observation_key"]: item["value"] for item in twin["profile"]["observations"]
        }
        for index, (line, quote) in enumerate(passages[:3]):
            field, effect = fields[index], effects[index]
            value = copy.deepcopy(current.get(f"user_twin.{field}"))
            if effect == "ADDS":
                value = _items_value([" ".join(quote.split())[:300]])
            elif value is None or value.get("kind") not in ("TEXT", "ITEMS"):
                continue
            value.pop("reason", None)
            candidates.append(
                {
                    "statement": (
                        "Interpretazione di prova della fonte "
                        if it
                        else "Test interpretation of the source "
                    )
                    + str(index + 1),
                    "basis": "Citazione da testo di prova, senza validazione umana."
                    if it
                    else "Quotation from test text, without human validation.",
                    "effect": effect,
                    "field": field,
                    "value": value,
                    "quote": quote[:1000],
                    "line": line,
                }
            )
        context = evidence_update_context(
            project_id=project.id, locale=locale, twin=twin, evidence=source, text=text
        )
        comment, observations, rejected = package.bind_evidence_update(
            EvidenceUpdateOutput(
                comment="Proposte simulate da testo di prova; il proprietario decide."
                if it
                else "Simulated proposals from test text; the owner decides.",
                changes=candidates,
            ),
            context=context,
        )
        self._record(project, "TWIN_UPDATE")
        update = self._update_of(
            project,
            twin,
            locale,
            [item.to_snapshot() for item in observations],
            {"changes": 0, "tests": 0},
            COSTS["TWIN_UPDATE"],
        )
        update["comment"] = comment
        update["evidence"] = {
            "source_id": source_id,
            "source_version": source["version"],
            "content_hash": source["content_hash"],
            "rejected_changes": rejected,
        }
        project.updates.insert(0, update)
        return _Answer(201, {"status": "PROPOSED", "update": copy.deepcopy(update)})

    def _route_twin_update(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, copy.deepcopy(self._find_update(project, call.params["update_id"])))

    def _route_decide_update(self, call: _Call) -> _Answer:
        decision, kept, reason = _update_decision_of(call.json())
        project = self._code_project(call)
        update = self._find_update(project, call.params["update_id"])
        if update["status"] != "PROPOSED":
            raise _Refusal(409, {"code": "TWIN_UPDATE_ALREADY_DECIDED"})
        twin_id = str(update["twin_id"])
        twin = self._named_twin(
            project, twin_id, update["twin_name"], update["base"]["profile_version_number"]
        )
        development = project.development.get(twin_id, 0)
        approving = decision == "APPROVE"
        if approving and development != update["base"]["development_version_number"]:
            raise _Refusal(409, {"code": "TWIN_UPDATE_CONTEXT_CHANGED"})
        if (
            approving
            and not update.get("evidence")
            and self._active_count(project, twin_id) + len(kept) > (MAX_LEARNED_OBSERVATIONS)
        ):
            raise _Refusal(409, {"code": "TWIN_OBSERVATIONS_LIMIT"})
        proposed = update["observations"]
        position = next(
            (place for place, item in enumerate(kept) if item["index"] >= len(proposed)), None
        )
        if position is not None:
            raise _Refusal(
                422,
                {
                    "code": "invalid_request",
                    "errors": [
                        {
                            "loc": ["body", "kept", position, "index"],
                            "type": "value_error",
                            "msg": UNKNOWN_INDEX,
                        }
                    ],
                },
            )
        moment = _iso(self._now())
        if approving and update.get("evidence"):
            twin = self._decide_evidence_update(project, twin, update, kept)
        elif approving:
            for item in sorted(kept, key=lambda entry: int(entry["index"])):
                observation = dict(proposed[item["index"]])
                if item["statement"] is not None:
                    observation["statement"] = item["statement"]
                self._add_observation(
                    project,
                    twin,
                    observation,
                    source="TWIN_CRITIQUE",
                    version=development + 1,
                    moment=moment,
                    update_id=str(update["id"]),
                )
            project.development[twin_id] = development + 1
        update["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        update["decision"] = {
            "decided_at": moment,
            "kept": sorted(int(item["index"]) for item in kept),
            "reason": reason,
        }
        return _Answer(
            200,
            {
                "status": "DECIDED",
                "update": copy.deepcopy(update),
                "twin": self._learning_entry(project, twin),
            },
        )

    def _decide_evidence_update(self, project, twin, update, kept):
        twin = self._learning_twin(project, str(twin["twin_id"]))
        reference = update["evidence"]
        source = self._evidence_source(project, reference["source_id"], reference["source_version"])
        latest = self._evidence_source(project, reference["source_id"])
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        if (
            latest["version"] != source["version"]
            or source["content_hash"] != reference["content_hash"]
            or twin["version_number"] != update["base"]["profile_version_number"]
        ):
            raise _Refusal(409, {"code": "TWIN_UPDATE_CONTEXT_CHANGED"})
        text = project.evidence_texts.get((source["id"], source["version"]))
        if text is None:
            raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
        domain_source = EvidenceVersion(
            **{
                key: value
                for key, value in source.items()
                if key
                not in {"id", "source_kind", "status", "created_at", "retired_at", "imported_from"}
            },
            id=UUID(source["id"]),
            source_kind=EvidenceSourceKind(source["source_kind"]),
            status=EvidenceStatus(source["status"]),
            created_at=datetime.fromisoformat(source["created_at"]),
            retired_at=None
            if source["retired_at"] is None
            else datetime.fromisoformat(source["retired_at"]),
        )
        profile = _fake_twin_profile(twin["profile"])
        observations, rows, touched = [], [], set()
        for item in kept:
            proposal = update["observations"][item["index"]]
            change = EvidenceChange.from_snapshot(proposal["evidence"])
            if change.field in touched or not change.citation.verify(text):
                raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
            touched.add(change.field)
            before = profile.observation_for(change.field)
            after = apply_evidence_change(
                before,
                change,
                domain_source,
                statement=item["statement"],
                rationale=proposal["basis"],
            )
            observations.append(after)
            rows.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_version": twin["version_number"] + 1,
                    "field": change.field.value,
                    "source_id": str(change.citation.source_id),
                    "source_version": change.citation.source_version,
                    "change": change.to_snapshot(),
                    "before": None if before is None else before.to_snapshot(),
                    "after": after.to_snapshot(),
                    "retired_at": None,
                }
            )
        updated = evidence_profile(profile, observations)
        snapshot = self._append_evidence_profiles(project, {twin["twin_id"]: updated})
        project.evidence_changes.extend(rows)
        return next(
            item
            for item in snapshot["snapshot"]["twin_versions"]
            if item["twin_id"] == twin["twin_id"]
        )

    def _route_learn(self, call: _Call) -> _Answer:
        observation = _owner_observation_of(call.json())
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        twin_id = str(twin["twin_id"])
        if self._active_count(project, twin_id) >= MAX_LEARNED_OBSERVATIONS:
            raise _Refusal(409, {"code": "TWIN_OBSERVATIONS_LIMIT"})
        self._refuse_pending(project, twin_id)
        version = project.development.get(twin_id, 0) + 1
        self._add_observation(
            project,
            twin,
            observation,
            source="OWNER",
            version=version,
            moment=_iso(self._now()),
            update_id=None,
        )
        project.development[twin_id] = version
        return _Answer(201, {"status": "LEARNED", "twin": self._learning_entry(project, twin)})

    def _route_retire_observation(self, call: _Call) -> _Answer:
        reason = _retire_reason_of(call.json())
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        twin_id = str(twin["twin_id"])
        number = _observation_number(call.params["code"])
        observation = next(
            (
                item
                for item in project.learned
                if item["twin_id"] == twin_id
                and item["retired"] is None
                and _code_number(item["code"]) == number
            ),
            None,
        )
        if observation is None:
            raise _Refusal(404, {"code": "TWIN_OBSERVATION_NOT_FOUND"})
        self._refuse_pending(project, twin_id)
        version = project.development.get(twin_id, 0) + 1
        observation["retired"] = {
            "retired_in_version": version,
            "retired_at": _iso(self._now()),
            "reason": reason,
        }
        project.development[twin_id] = version
        return _Answer(200, {"status": "RETIRED", "twin": self._learning_entry(project, twin)})


def _after(moment: object, since: datetime | None) -> bool:
    return since is None or datetime.fromisoformat(str(moment)) > since


def _critique_moment(item: tuple[Mapping[str, object], Mapping[str, object]]) -> datetime:
    return datetime.fromisoformat(str(item[0]["reviewed_at"]))


def _comparable(text: str) -> str:
    return " ".join(text.split()).casefold()


def _cut_line(value: str, maximum: int) -> str:
    return " ".join(value.split())[:maximum].rstrip()


def _locale_language(locale: str) -> str:
    return "it" if locale.split("-", 1)[0].lower() == "it" else "en"


def _observation_number(code: str) -> int | None:
    if OBSERVATION_CODE.fullmatch(code) is None:
        return None
    number = _code_number(code)
    return number if 1 <= number <= MAX_OBSERVATION_NUMBER else None


def _active_entry(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "code": item["code"],
        "statement": item["statement"],
        "basis": item["basis"],
        "source": item["source"],
        "about": dict(item["about"]),
        "contradicts_profile": item["contradicts_profile"],
        "added_in_version": item["added_in_version"],
        "approved_at": item["approved_at"],
        "update_id": item["update_id"],
    }


def _retired_entry(item: Mapping[str, object]) -> dict[str, object]:
    retired = item["retired"]
    return {
        "code": item["code"],
        "statement": item["statement"],
        "retired_in_version": retired["retired_in_version"],
        "retired_at": retired["retired_at"],
        "reason": retired["reason"],
    }


def _kept_of(fields: _Fields) -> dict[str, object]:
    index = fields.whole("index", minimum=0)
    statement = fields.text(
        "statement", required=False, nullable=True, minimum=1, maximum=MAX_OBSERVATION_LENGTH
    )
    if statement is not None:
        statement = fields.normalized("statement", statement, _single_line)
    return {"index": index, "statement": statement}


def _kept_rule(decision: object, kept: Sequence[Mapping[str, object]]) -> None:
    indexes = [item["index"] for item in kept]
    _distinct(indexes)
    if (decision == "APPROVE") != bool(indexes):
        raise ValueError("an approval keeps one observation or more, a rejection keeps none")


def _update_decision_of(body: object) -> tuple[str, list[dict[str, object]], str | None]:
    fields = _Fields(body, UPDATE_DECISION_FIELDS)
    decision = fields.choice("decision", UPDATE_DECISIONS)
    kept = _models(
        fields,
        "kept",
        KEPT_FIELDS,
        _kept_of,
        required=False,
        maximum_items=MAX_UPDATE_OBSERVATIONS,
    )
    reason = fields.text("reason", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if reason is not None:
        reason = fields.normalized("reason", reason, _optional_line)
    _model_rule(fields, lambda: _kept_rule(decision, kept))
    fields.check()
    return str(decision), kept, reason


def _owner_observation_of(body: object) -> dict[str, object]:
    fields = _Fields(body, OBSERVATION_FIELDS)
    statement = fields.text("statement", minimum=1, maximum=MAX_OBSERVATION_LENGTH)
    if statement is not None:
        statement = fields.normalized("statement", statement, _single_line)
    about: dict[str, object] = {"requirement": None, "screen": None}
    child = fields.child("about", ABOUT_FIELDS, required=False, nullable=True)
    if child is not None:
        about = {
            "requirement": child.pattern(
                "requirement", REQUIREMENT_REFERENCE, required=False, nullable=True
            ),
            "screen": child.pattern("screen", SCREEN_REFERENCE, required=False, nullable=True),
        }
        fields.adopt(child)
    fields.check()
    return {"statement": statement, "basis": None, "about": about, "contradicts_profile": None}


def _retire_reason_of(body: object) -> str | None:
    fields = _Fields(body, RETIRE_FIELDS)
    reason = fields.text("reason", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if reason is not None:
        reason = fields.normalized("reason", reason, _optional_line)
    fields.check()
    return reason
