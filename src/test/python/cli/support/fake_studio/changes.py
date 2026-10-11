from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from orchestwin.knowledge.state import (
    DECISIONS,
    MAX_AUTHOR_LENGTH,
    MAX_DIFF_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_TASK_LENGTH,
    MAX_TASKS,
    review_is_stale,
)

from .common import (
    _by_id,
    _error,
    _findings_by_twin,
    _first_goal,
    _first_line,
    _first_screen,
    _lax_boolean,
    _models,
    _optional_line,
    _prepared_task,
    _single_line,
    _task_origin,
)
from .fields import _Fields
from .texts import COSTS
from .values import (
    COMMIT_PATTERN,
    DEFAULT_LOCALE,
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    REQUIREMENT_CODE,
    _Answer,
    _Invalid,
    _iso,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


ALIGNMENT_WORDS = (
    ("CODE_DRIFT", ("drift",)),
    ("DESIGN_OUTDATED", ("design",)),
    ("REQUIREMENTS_OUTDATED", ("requisit", "requirement")),
)
FINDING_FIELDS = ("twin_id", "finding")
DECISION_FIELDS = ("kind", "note", "tasks", "findings")
CHANGE_CRITIQUES = {
    "it": {
        "CONCERN": "Per «{goal}» la modifica «{line}» mi lascia qualche dubbio: ecco dove.",
        "FINE": "Per «{goal}» la modifica «{line}» mi va bene.",
        "requirement": (
            "Nella pagina non ritrovo ancora quello che chiede il requisito {code}.",
            "Mostrare nella pagina quello che chiede il requisito {code}.",
        ),
        "screen": (
            "Nella schermata {code} le cifre restano piccole sul telefono.",
            "Ingrandire le cifre della schermata {code}.",
        ),
        "check": (
            "La modifica non cambia come uso la schermata {screen}, ma il requisito {code} "
            "va provato.",
            "Provare il requisito {code} sulla schermata {screen}.",
        ),
    },
    "en": {
        "CONCERN": "For “{goal}” the change “{line}” leaves me some doubts: here is where.",
        "FINE": "For “{goal}” the change “{line}” works for me.",
        "requirement": (
            "On the page I still cannot find what requirement {code} asks for.",
            "Show on the page what requirement {code} asks for.",
        ),
        "screen": (
            "On screen {code} the digits stay small on the phone.",
            "Make the digits of screen {code} larger.",
        ),
        "check": (
            "The change does not alter how I use screen {screen}, but requirement {code} "
            "needs a test.",
            "Try requirement {code} on screen {screen}.",
        ),
    },
}
CHANGE_VERDICTS = {
    "it": {
        "ALIGNED": "La modifica «{line}» segue i requisiti e il design approvati.",
        "CODE_DRIFT": "La modifica «{line}» si allontana dai requisiti o dal design approvati: "
        "va corretto il codice.",
        "DESIGN_OUTDATED": "La modifica «{line}» è un'evoluzione legittima: il design va "
        "aggiornato con una nuova versione.",
        "REQUIREMENTS_OUTDATED": "La modifica «{line}» è un'evoluzione legittima: i requisiti "
        "vanno aggiornati con una nuova versione.",
        "design_request": "Aggiornare il design perché descriva quello che la modifica «{line}» "
        "ha introdotto nella schermata {screen}.",
        "requirements_request": "Aggiornare i requisiti perché descrivano quello che la modifica "
        "«{line}» ha introdotto, a partire dal requisito {code}.",
        "tasks": (
            "Riportare il codice in linea con la schermata {screen} del design approvato.",
            "Coprire il requisito {code} con un test automatico.",
        ),
    },
    "en": {
        "ALIGNED": "The change “{line}” follows the approved requirements and design.",
        "CODE_DRIFT": "The change “{line}” departs from the approved requirements or design: "
        "the code should change.",
        "DESIGN_OUTDATED": "The change “{line}” is a legitimate evolution: the design should get "
        "a new version.",
        "REQUIREMENTS_OUTDATED": "The change “{line}” is a legitimate evolution: the "
        "requirements should get a new version.",
        "design_request": "Update the design so that it describes what the change “{line}” "
        "introduced on screen {screen}.",
        "requirements_request": "Update the requirements so that they describe what the change "
        "“{line}” introduced, starting from requirement {code}.",
        "tasks": (
            "Bring the code back in line with screen {screen} of the approved design.",
            "Cover requirement {code} with an automated test.",
        ),
    },
}


class _ChangeRoutes:
    def _code_project(self, call: _Call) -> FakeProject:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        return project

    def _find_change(self, project: FakeProject, commit: str) -> dict[str, object]:
        wanted = commit.lower()
        if COMMIT_PATTERN.fullmatch(wanted) is None:
            raise _Refusal(404, {"code": "CODE_CHANGE_NOT_FOUND"})
        exact = next((item for item in project.code_changes if item["commit"] == wanted), None)
        if exact is not None:
            return exact
        found = [item for item in project.code_changes if str(item["commit"]).startswith(wanted)]
        if not found:
            raise _Refusal(404, {"code": "CODE_CHANGE_NOT_FOUND"})
        if len(found) > 1:
            raise _Refusal(409, {"code": "CODE_CHANGE_AMBIGUOUS"})
        return found[0]

    def _latest_run(self, project: FakeProject, commit: object) -> dict[str, object] | None:
        return next((run for run in project.change_runs if run["commit"] == commit), None)

    def _current_reference(self, project: FakeProject) -> dict[str, object] | None:
        reference = self._alignment_reference(project)
        requirements, design = reference["requirements"], reference["design"]
        if requirements is None or design is None:
            return None
        return {
            "requirements_version_number": requirements["version_number"],
            "design_version_number": design["version_number"],
            "alternative_code": design["alternative_code"],
        }

    def _change_payload(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        frame: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        latest = self._latest_run(project, record["commit"])
        review = None
        if latest is not None:
            reference = dict(latest["reference"])
            stale = review_is_stale(reference, self._current_reference(project))
            review = {
                "run_id": latest["id"],
                "reviewed_at": latest["reviewed_at"],
                "verdict": latest["alignment"]["status"],
                "summary": latest["alignment"]["summary"],
                "reference": reference,
                "stale": stale,
            }
            if frame is not None:
                del review["stale"]
                if frame["reference"] is not None and not stale:
                    review["reference"] = dict(frame["reference"])
        return {
            "commit": record["commit"],
            "parent": record["parent"],
            "committed_at": record["committed_at"],
            "author": record["author"],
            "message": record["message"],
            "files": copy.deepcopy(record["files"]),
            "recorded_at": record["recorded_at"],
            "review": review,
            "decision": copy.deepcopy(record["decision"]),
        }

    def _stale_reviews(self, project: FakeProject) -> int:
        current = self._current_reference(project)
        count = 0
        for record in self._pending(project):
            latest = self._latest_run(project, record["commit"])
            if latest is not None and review_is_stale(latest["reference"], current):
                count += 1
        return count

    def _aligned(self, project: FakeProject) -> dict[str, object] | None:
        record = next((item for item in project.code_changes if item["aligned"] is not None), None)
        return None if record is None else dict(record["aligned"])

    def _pending(self, project: FakeProject) -> list[dict[str, object]]:
        pending = []
        for record in project.code_changes:
            if record["aligned"] is not None:
                break
            pending.append(record)
        return pending

    def _alignment_reference(self, project: FakeProject) -> dict[str, object]:
        approvals = self._approvals(project)
        requirements = project.specification if approvals["requirements"] else None
        design = project.design if approvals["design"] else None
        return {
            "requirements": None
            if requirements is None
            else {
                "version_id": requirements["id"],
                "version_number": requirements["version_number"],
                "content_hash": requirements["content_hash"],
            },
            "design": None
            if design is None
            else {
                "version_id": design["id"],
                "version_number": design["version_number"],
                "content_hash": design["content_hash"],
                "alternative_code": _chosen_code(design["package"]),
            },
        }

    def _alignment_payload(self, project: FakeProject) -> dict[str, object]:
        latest = project.code_changes[0] if project.code_changes else None
        return {
            "project_id": project.id,
            "reference": self._alignment_reference(project),
            "aligned": self._aligned(project),
            "pending_changes": len(self._pending(project)),
            "stale_reviews": self._stale_reviews(project),
            "latest_change": None if latest is None else self._change_payload(project, latest),
            "tasks": self._task_list(project, every=False),
            "review_available": self.hosted,
        }

    def _approved_twins(self, project: FakeProject) -> list[dict[str, object]]:
        snapshot = project.snapshot
        if snapshot is None or not self._approvals(project)["twins"]:
            return []
        return list(snapshot["snapshot"]["twin_versions"])

    def _route_alignment(self, call: _Call) -> _Answer:
        return _Answer(200, self._alignment_payload(self._code_project(call)))

    def _route_record_change(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(),
            ("commit", "parent", "committed_at", "author", "message", "files", "diff"),
        )
        commit = fields.pattern("commit", COMMIT_PATTERN)
        parent = fields.pattern("parent", COMMIT_PATTERN, required=False, nullable=True)
        committed_at = fields.moment("committed_at")
        author = fields.text("author", required=False, nullable=True, maximum=MAX_AUTHOR_LENGTH)
        if author is not None:
            author = fields.normalized("author", author, _optional_line)
        message = fields.text("message", minimum=1, maximum=MAX_MESSAGE_LENGTH)
        if message is not None:
            message = fields.normalized("message", message, _text_block)
        files = fields.changed_files("files")
        diff = fields.text("diff", required=False, maximum=MAX_DIFF_LENGTH, default="")
        diff = fields.normalized("diff", diff, _diff_text)
        fields.check()
        commit = str(commit).lower()
        parent = None if parent is None else parent.lower()
        if parent == commit:
            raise _Invalid([_error(("body",), "value_error")])
        project = self._code_project(call)
        stored = next((item for item in project.code_changes if item["commit"] == commit), None)
        if stored is not None:
            change = self._change_payload(project, stored)
            return _Answer(200, {"status": "ALREADY_RECORDED", "change": change})
        record: dict[str, object] = {
            "commit": commit,
            "parent": parent,
            "committed_at": _iso(committed_at) if committed_at is not None else None,
            "author": author,
            "message": message,
            "files": files,
            "recorded_at": _iso(self._now()),
            "decision": None,
            "diff": diff,
            "aligned": None,
        }
        project.code_changes.append(record)
        project.code_changes.sort(key=_recorded_order, reverse=True)
        return _Answer(201, {"status": "RECORDED", "change": self._change_payload(project, record)})

    def _route_changes(self, call: _Call) -> _Answer:
        raw = call.value("pending")
        pending = False if raw is None else _lax_boolean(raw)
        if pending is None:
            raise _Invalid([_error(("query", "pending"), "bool_parsing")])
        project = self._code_project(call)
        records = self._pending(project) if pending else project.code_changes
        return _Answer(
            200, {"items": [self._change_payload(project, record) for record in records]}
        )

    def _route_change(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        return _Answer(200, {**self._change_payload(project, record), "diff": record["diff"]})

    def _route_change_reviews(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        runs = [
            copy.deepcopy(run) for run in project.change_runs if run["commit"] == record["commit"]
        ]
        return _Answer(200, {"items": runs})

    def _route_review_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("locale", "again"))
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        again = fields.flag("again")
        fields.check()
        return self._later(
            call,
            "CODE_CHANGE_REVIEW",
            {"locale": locale, "again": again},
            lambda: self._reviewed_change(call, str(locale), again),
        )

    def _reviewed_change(self, call: _Call, locale: str, again: bool) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        if not again and any(run["commit"] == record["commit"] for run in project.change_runs):
            raise _Refusal(409, {"code": "CODE_CHANGE_REVIEW_EXISTS"})
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"})
        charged = 0
        for operation in (*("CODE_CHANGE_REVIEW" for _ in twins), "CODE_ALIGNMENT"):
            self._record(project, operation)
            charged += COSTS[operation]
        run = self._stored_change_run(project, record, twins, locale, reference, charged)
        return _Answer(201, {"status": "REVIEWED", "run": copy.deepcopy(run)})

    def _stored_change_run(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        reference: Mapping[str, object],
        charged: int,
    ) -> dict[str, object]:
        previous = self._latest_run(project, record["commit"])
        if previous is not None:
            earlier, source = _findings_by_twin(previous["critiques"]), "THIS_COMMIT"
        else:
            earlier, source = self._previous_commit_findings(project, record), "PREVIOUS_COMMIT"
        run = self._change_run(project, record, twins, locale, reference, charged)
        project.change_runs.insert(0, run)
        project.critique_contexts.insert(
            0,
            {
                "kind": "CODE_CHANGE",
                "run_id": run["id"],
                "commit": record["commit"],
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "earlier_source": source if earlier.get(twin["twin_id"]) else None,
                        "earlier_findings": earlier.get(twin["twin_id"], []),
                    }
                    for twin in twins
                ],
            },
        )
        return run

    def _previous_commit_findings(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, list[str]]:
        pending = self._pending(project)
        index = next(
            (place for place, item in enumerate(pending) if item["commit"] == record["commit"]),
            None,
        )
        if index is None:
            return {}
        for older in pending[index + 1 :]:
            latest = self._latest_run(project, older["commit"])
            if latest is not None:
                return _findings_by_twin(latest["critiques"])
        return {}

    def _change_run(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        reference: Mapping[str, object],
        charged: int,
    ) -> dict[str, object]:
        texts = CHANGE_CRITIQUES[self.language]
        verdicts = CHANGE_VERDICTS[self.language]
        specification = project.specification
        design = project.design
        if specification is None or design is None:
            raise RuntimeError("a review needs the approved requirements and design")
        line = _first_line(str(record["message"]))
        known = [str(item["code"]) for item in specification["specification"]["requirements"]]
        cited = [code for code in REQUIREMENT_CODE.findall(str(record["diff"])) if code in known]
        requirement = cited[0] if cited else known[0]
        screen = _first_screen(design["package"])
        files = record["files"]
        first_file = str(files[0]["path"]) if files else None
        critiques = []
        for position, twin in enumerate(twins):
            findings = []
            if position == 0:
                text, action = texts["requirement"]
                findings.append(
                    _change_finding(
                        "MEDIUM",
                        text.format(code=requirement),
                        action.format(code=requirement),
                        requirement=requirement,
                        file=first_file,
                    )
                )
                text, action = texts["screen"]
                findings.append(
                    _change_finding(
                        "LOW", text.format(code=screen), action.format(code=screen), screen=screen
                    )
                )
            elif position == 1:
                text, action = texts["check"]
                findings.append(
                    _change_finding(
                        "LOW",
                        text.format(code=requirement, screen=screen),
                        action.format(code=requirement, screen=screen),
                        requirement=requirement,
                        screen=screen,
                    )
                )
            verdict = "CONCERN" if position == 0 else "FINE"
            critiques.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "verdict": verdict,
                    "summary": texts[verdict].format(goal=_first_goal(twin), line=line),
                    "findings": findings,
                }
            )
        status = _alignment_status(str(record["message"]))
        about = [finding["about"] for critique in critiques for finding in critique["findings"]]
        design_reference = reference["design"]
        requirements_reference = reference["requirements"]
        return {
            "id": self._new_id(),
            "commit": record["commit"],
            "reviewed_at": _iso(self._now()),
            "locale": locale,
            "reference": {
                "requirements_version_number": requirements_reference["version_number"],
                "design_version_number": design_reference["version_number"],
                "alternative_code": design_reference["alternative_code"],
            },
            "critiques": critiques,
            "alignment": {
                "status": status,
                "summary": verdicts[status].format(line=line),
                "affected": {
                    "requirements": sorted(
                        {str(item["requirement"]) for item in about if item["requirement"]}
                    ),
                    "screens": sorted({str(item["screen"]) for item in about if item["screen"]}),
                },
                "design_request": verdicts["design_request"].format(line=line, screen=screen)
                if status == "DESIGN_OUTDATED"
                else None,
                "requirements_request": verdicts["requirements_request"].format(
                    line=line, code=requirement
                )
                if status == "REQUIREMENTS_OUTDATED"
                else None,
                "code_tasks": [
                    task.format(screen=screen, code=requirement) for task in verdicts["tasks"]
                ]
                if status == "CODE_DRIFT"
                else [],
            },
            "cost_microusd": charged,
        }

    def _route_decide_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), DECISION_FIELDS)
        kind = fields.choice("kind", DECISIONS)
        note = fields.text("note", required=False, nullable=True, maximum=MAX_NOTE_LENGTH)
        if note is not None:
            note = fields.normalized("note", note, _optional_block)
        tasks = fields.texts(
            "tasks",
            nullable=False,
            maximum_items=MAX_TASKS,
            default=[],
            item_minimum=1,
            item_maximum=MAX_TASK_LENGTH,
        )
        texts = fields.normalized("tasks", tasks, _task_texts) if tasks else []
        findings = _models(
            fields,
            "findings",
            FINDING_FIELDS,
            _finding_of,
            required=False,
            maximum_items=MAX_TASKS,
        )
        fields.check()
        texts = list(texts or [])
        if kind == "CODE_TASKS":
            valid = 1 <= len(texts) + len(findings) <= MAX_TASKS
        else:
            valid = not texts and not findings
        if not valid:
            raise _Invalid([_error(("body",), "value_error")])
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        self._decide(project, record, str(kind), note, texts, findings)
        return _Answer(
            200,
            {
                "status": "DECIDED",
                "change": self._change_payload(project, record),
                "alignment": self._alignment_payload(project),
            },
        )

    def _decide(
        self,
        project: FakeProject,
        record: dict[str, object],
        kind: str,
        note: str | None,
        texts: Sequence[str],
        findings: Sequence[Mapping[str, object]],
    ) -> None:
        sources = [
            {
                "kind": "CODE_CHANGE",
                "commit": record["commit"],
                "twin_id": item["twin_id"],
                "finding": item["finding"],
            }
            for item in findings
        ]
        resolved = self._resolve_sources(project, sources)
        latest = self._latest_run(project, record["commit"])
        affected = {"requirements": [], "screens": []}
        if latest is not None:
            affected = copy.deepcopy(latest["alignment"]["affected"])
        moment = _iso(self._now())
        record["decision"] = {"kind": kind, "decided_at": moment, "note": note}
        record["aligned"] = None
        if kind == "ALIGNED":
            reference = self._alignment_reference(project)
            requirements, design = reference["requirements"], reference["design"]
            record["aligned"] = {
                "commit": record["commit"],
                "decided_at": moment,
                "requirements_version_number": None
                if requirements is None
                else requirements["version_number"],
                "design_version_number": None if design is None else design["version_number"],
            }
            self._close_aligned_tasks(project, record, moment)
        origin = _task_origin("CODE_CHANGE", commit=str(record["commit"]))
        for text in texts:
            self._new_task(
                project,
                text,
                {**affected, "criteria": []},
                origin,
                moment,
            )
        self._create_tasks(project, [_prepared_task(None, item) for item in resolved], moment)
        project.decision_count += 1

    def _close_aligned_tasks(
        self, project: FakeProject, record: Mapping[str, object], moment: str
    ) -> None:
        places = {str(item["commit"]): place for place, item in enumerate(project.code_changes)}
        aligned_place = places[str(record["commit"])]
        recorded = datetime.fromisoformat(str(record["recorded_at"]))
        for task in project.code_tasks:
            if task["status"] != "OPEN":
                continue
            origin = task["origin"]
            if origin["kind"] == "CODE_CHANGE":
                closed = places[str(origin["commit"])] >= aligned_place
            else:
                closed = datetime.fromisoformat(str(task["created_at"])) <= recorded
            if closed:
                task["status"] = "DONE"
                task["closed_at"] = moment
                task["note"] = None


def _text_block(value: object) -> str:
    normalized = str(value).strip()
    if not normalized or "\x00" in normalized:
        raise ValueError("the text must hold visible characters")
    return normalized


def _optional_block(value: object) -> str | None:
    return None if value is None or not str(value).strip() else _text_block(value)


def _diff_text(value: object) -> str:
    diff = str(value)
    if "\x00" in diff:
        raise ValueError("the diff must not hold a null character")
    return diff


def _task_texts(value: object) -> list[str]:
    return [_single_line(item) for item in value] if isinstance(value, list) else []


def _chosen_code(package: Mapping[str, object]) -> str | None:
    chosen = _by_id(package["alternatives"], str(package["owner_selected_alternative_id"]))
    return None if chosen is None else str(chosen["code"])


def _change_finding(
    severity: str,
    text: str,
    action: str,
    *,
    requirement: str | None = None,
    screen: str | None = None,
    file: str | None = None,
) -> dict[str, object]:
    return {
        "severity": severity,
        "text": text,
        "about": {"requirement": requirement, "screen": screen, "file": file},
        "action": action,
    }


def _alignment_status(message: str) -> str:
    words = message.casefold()
    for status, keys in ALIGNMENT_WORDS:
        if any(key in words for key in keys):
            return status
    return "ALIGNED"


def _recorded_order(record: Mapping[str, object]) -> tuple[datetime, datetime, str]:
    return (
        datetime.fromisoformat(str(record["recorded_at"])),
        datetime.fromisoformat(str(record["committed_at"])),
        str(record["commit"]),
    )


def _finding_of(fields: _Fields) -> dict[str, object]:
    return {
        "twin_id": fields.identifier("twin_id"),
        "finding": fields.whole("finding", minimum=0),
    }
