from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from orchestwin.agents.catalog import all_agent_catalog_entries
from orchestwin.knowledge.state import (
    MAX_BASIS_LENGTH,
    MAX_LEARNED_OBSERVATIONS,
    MAX_OBSERVATION_LENGTH,
    MAX_PAGE_TEXT_LENGTH,
    MAX_STEP_DETAIL_LENGTH,
    MAX_UPDATE_CHANGES,
    MAX_UPDATE_OBSERVATIONS,
    MAX_UPDATE_TESTS,
)
from orchestwin.projects.brief_dialogue import ESSENTIAL_FIELDS
from orchestwin.projects.briefs import BriefField, create_project_brief

from .acceptance import MAX_SNAPSHOT_TITLE_LENGTH, _criteria_outcomes, _cut_text, _run_summary
from .changes import _recorded_order, _text_block
from .common import _cited_ids, _copy, _critique_of, _mockup_warnings
from .learning import _comparable, _cut_line
from .projects import SEED_BRIEF
from .tasks import _task_items
from .team import RULE_KEYS
from .texts import COSTS, PERSONAS
from .values import APPROACHES, COMMIT_PATTERN, SEED_DIFF, SEED_FILE, STAGES, _iso

if TYPE_CHECKING:
    from .project import FakeProject


REQUEST_OPERATIONS = (
    "PERSONA_PROPOSAL",
    "USER_TWIN_GENERATION",
    "REQUIREMENTS_PROPOSAL",
    "REQUIREMENTS_CHANGE",
    "DESIGN_PROPOSAL",
    "DESIGN_REGENERATION",
    "DESIGN_EVALUATION",
    "CODE_CHANGE_REVIEW",
    "TEST_PLAN",
    "TEST_REVIEW",
    "TWIN_UPDATE",
    "KNOWLEDGE_ALIGNMENT",
    "DESIGN_CHANGE",
)
OPERATIONS = ("MOCKUP", "ITERATION", *REQUEST_OPERATIONS)
ALWAYS_PRESENT = frozenset(
    entry.agent_id.value for entry in all_agent_catalog_entries() if entry.is_always_present
)
SEED_AUTHOR = "Test Author"
SEED_ADDRESS = "dist"
SEED_BROWSER = {"name": "chrome", "version": "151.0.7922.76"}
SEED_PAGE = "http://127.0.0.1:41234/"
SEED_TEXTS = {
    "it": {
        "message": "Aggiunge la divisione del conto",
        "owner_task": "Scrivere il testo di aiuto della pagina.",
        "verdict_task": "Coprire il calcolo della mancia con un test automatico.",
        "goal": "Ricordare la percentuale scelta l'ultima volta",
        "requirement": "Il sistema permette di arrotondare la mancia all'euro.",
        "assertion": "Il totale resta visibile in ogni schermata.",
        "observations": (
            (
                "Chi paga al tavolo legge le cifre da lontano, spesso con poca luce.",
                "Un rilievo ripetuto sui commit e sui test.",
            ),
            (
                "Chi divide il conto vuole vedere subito la quota di ciascuno.",
                "Un rilievo sulla verifica dei criteri.",
            ),
        ),
    },
    "en": {
        "message": "Add the split of the bill",
        "owner_task": "Write the help text of the page.",
        "verdict_task": "Cover the tip calculation with an automated test.",
        "goal": "Remember the percentage chosen last time",
        "requirement": "The system lets people round the tip to the euro.",
        "assertion": "The total stays visible on every screen.",
        "observations": (
            (
                "People who pay at the table read the digits from a distance, often in dim light.",
                "A finding repeated on the commits and the tests.",
            ),
            (
                "People who split the bill want to see each share at once.",
                "A finding on the acceptance tests.",
            ),
        ),
    },
}
ESSENTIAL = frozenset(item.value for item in ESSENTIAL_FIELDS)


class _Seeding:
    def _seed_twin(self, project: FakeProject, twin: int | str) -> dict[str, object]:
        twins = self._approved_twins(project)
        if not twins:
            raise ValueError("the twins of the project are not approved")
        if isinstance(twin, bool) or not isinstance(twin, int | str):
            raise ValueError("name the twin by its position or its twin_id")
        if isinstance(twin, int):
            if not 0 <= twin < len(twins):
                raise ValueError(f"the project has no twin at position {twin}")
            return twins[twin]
        found = next((item for item in twins if item["twin_id"] == twin), None)
        if found is None:
            raise ValueError(f"the project has no approved twin {twin}")
        return found

    def _seed_locale(self) -> str:
        return "it-IT" if self.language == "it" else "en-US"

    def _seed_ground(self, project: FakeProject) -> dict[str, object]:
        reference = self._alignment_reference(project)
        if reference["requirements"] is None or reference["design"] is None:
            raise ValueError("the project needs approved requirements and an approved design")
        return reference

    def _seed_twins(self, project: FakeProject) -> list[dict[str, object]]:
        twins = self._approved_twins(project)
        if not twins:
            raise ValueError("a review needs the approved twins")
        return twins

    def _seed_commit(self, project: FakeProject) -> str:
        number = len(project.code_changes)
        known = {str(item["commit"]) for item in project.code_changes}
        while True:
            number += 1
            seed = f"orchestwin-fake-seed:{project.id}:{number}".encode()
            commit = hashlib.sha256(seed).hexdigest()[:40]
            if commit not in known:
                return commit

    def _seed_change(
        self, project: FakeProject, message: str | None, commit: str | None, reviewed: bool
    ) -> dict[str, object]:
        chosen = self._seed_commit(project) if commit is None else commit.lower()
        if COMMIT_PATTERN.fullmatch(chosen) is None:
            raise ValueError("a commit holds 7 to 64 hexadecimal characters")
        if any(item["commit"] == chosen for item in project.code_changes):
            raise ValueError(f"the commit {chosen} is already recorded")
        text = SEED_TEXTS[self.language]["message"] if message is None else _text_block(message)
        reference = self._seed_ground(project) if reviewed else None
        twins = self._seed_twins(project) if reviewed else []
        parent = str(project.code_changes[0]["commit"]) if project.code_changes else None
        record: dict[str, object] = {
            "commit": chosen,
            "parent": parent,
            "committed_at": _iso(self._now()),
            "author": SEED_AUTHOR,
            "message": text,
            "files": [dict(SEED_FILE)],
            "recorded_at": _iso(self._now()),
            "decision": None,
            "diff": SEED_DIFF,
            "aligned": None,
        }
        project.code_changes.append(record)
        project.code_changes.sort(key=_recorded_order, reverse=True)
        if reference is not None:
            cost = len(twins) * COSTS["CODE_CHANGE_REVIEW"] + COSTS["CODE_ALIGNMENT"]
            self._stored_change_run(project, record, twins, self._seed_locale(), reference, cost)
        return self._change_payload(project, record)

    def _seed_test_run(
        self, project: FakeProject, *, failed: bool, reviewed: bool
    ) -> dict[str, object]:
        reference = self._seed_ground(project)
        twins = self._seed_twins(project) if reviewed else []
        specification = project.specification
        if specification is None:
            raise ValueError("the project needs approved requirements")
        locale = self._seed_locale()
        body = {
            "locale": locale,
            "application": {"kind": "STATIC", "address": SEED_ADDRESS},
            "snapshot": {
                "url": SEED_PAGE,
                "title": project.name,
                "text": project.name,
                "hidden_text": "",
                "elements": [],
            },
            "criteria": None,
            "earlier": None,
        }
        wanted = [
            (str(item["code"]), str(item["statement"]))
            for item in specification["specification"]["acceptance_criteria"]
        ]
        plan = self._test_plan(body, reference, wanted, 1)
        project.acceptance_plans.insert(0, plan)
        project.acceptance_plan_requests.insert(0, _copy(body))
        results = [
            _seeded_result(path, "FAILED" if failed and position == 0 else "PASSED", project.name)
            for position, path in enumerate(plan["paths"])
        ]
        uncovered = copy.deepcopy(plan["not_covered"])
        outcomes = _criteria_outcomes([plan], results, uncovered)
        record: dict[str, object] = {
            "id": self._new_id(),
            "started_at": _iso(self._now()),
            "finished_at": _iso(self._now()),
            "recorded_at": _iso(self._now()),
            "application": {"kind": "STATIC", "address": SEED_ADDRESS},
            "browsers": [dict(SEED_BROWSER)],
            "reference": copy.deepcopy(plan["reference"]),
            "summary": _run_summary(outcomes),
            "criteria": outcomes,
            "not_covered": uncovered,
            "results": results,
            "critiques": [],
            "reviewed_at": None,
            "cost_microusd": int(plan["cost_microusd"]),
        }
        project.acceptance_runs.insert(0, record)
        if twins:
            cost = len(twins) * COSTS["TEST_REVIEW"]
            self._stored_test_review(project, record, twins, locale, cost)
        return self._test_run_payload(project, record)

    def _seed_version(self, project: FakeProject, stage: str) -> dict[str, object]:
        approvals = self._approvals(project)
        if stage == "design":
            design = project.design
            if design is None or not approvals["design"]:
                raise ValueError("the design of the project is not approved")
            version = self._append_design(
                project, copy.deepcopy(design["package"]), project.account
            )
        elif stage == "requirements":
            specification = project.specification
            if specification is None or not approvals["requirements"]:
                raise ValueError("the requirements of the project are not approved")
            version = self._append_requirements(
                project, copy.deepcopy(specification["specification"]), project.account
            )
        else:
            raise ValueError("stage must be requirements or design")
        self._approve(project, stage)
        return _copy(version)

    def _seed_perspective_change(self, project: FakeProject, agent_id: str) -> dict[str, object]:
        team = project.team
        if team is None or not self._approvals(project)["team"]:
            raise ValueError("the perspectives of the project are not approved")
        units = {
            str(unit["agent_id"]): bool(unit["editable"])
            for perspective in team["perspectives"]
            for unit in (perspective, *perspective["aspects"])
            if unit["agent_id"] is not None
        }
        if agent_id not in units:
            raise ValueError(f"{agent_id} does not switch a perspective or an aspect")
        if not units[agent_id]:
            raise ValueError(f"the brief does not let the owner switch {agent_id}")
        current = list(team["selected_agent_ids"])
        selected = (
            [agent for agent in current if agent != agent_id]
            if agent_id in current
            else [*current, agent_id]
        )
        content = self._team_content(
            project,
            project.brief,
            selected,
            list(team["members"]),
            {},
            {key: team[key] for key in RULE_KEYS},
            owner=True,
        )
        self._append_team(project, content, "OWNER_EDITED", project.account)
        self._seed_approval(project, "team")
        return _copy(self._sections(project))

    def _seed_requirements_change(self, project: FakeProject) -> dict[str, object]:
        current = project.specification
        if current is None or not self._approvals(project)["requirements"]:
            raise ValueError("the requirements of the project are not approved")
        if self._pending_requirements_diff(project) is not None:
            raise ValueError("a proposed change of the requirements waits for its decision")
        proposed, _ = self._with_requirement(
            current["specification"], SEED_TEXTS[self.language]["requirement"]
        )
        self._append_requirements(project, proposed, project.account)
        self._seed_approval(project, "requirements")
        return _copy(self._sections(project))

    def _seed_brief_change(self, project: FakeProject) -> dict[str, object]:
        version = project.brief
        if version is None or not self._approvals(project)["brief"]:
            raise ValueError("the brief of the project is not approved")
        goal = SEED_TEXTS[self.language]["goal"]
        goals = version.brief.value_for(BriefField.GOALS) or ()
        if goal in goals:
            raise ValueError("the brief already holds the seeded goal")
        unknown = set(version.brief.unknown_fields)
        unknown.discard(BriefField.GOALS)
        changed = replace(version.brief, goals=(*goals, goal), unknown_fields=frozenset(unknown))
        self._append_brief(project, changed, project.account)
        self._seed_approval(project, "brief")
        return _copy(self._sections(project))

    def _seed_requirement_removed(self, project: FakeProject) -> dict[str, object]:
        current, design = project.specification, project.design
        approvals = self._approvals(project)
        if current is None or design is None or not approvals["requirements"]:
            raise ValueError("the project needs approved requirements and a design")
        if not approvals["design"]:
            raise ValueError("the design of the project is not approved")
        if self._pending_requirements_diff(project) is not None:
            raise ValueError("a proposed change of the requirements waits for its decision")
        specification = current["specification"]
        cited = _cited_ids(design["package"])
        removed = next(
            (item for item in reversed(specification["requirements"]) if str(item["id"]) in cited),
            None,
        )
        if removed is None or len(specification["requirements"]) < 2:
            raise ValueError("the design cites no requirement that can be removed")
        proposed = _without_requirement(specification, str(removed["id"]))
        self._append_requirements(project, proposed, project.account)
        self._seed_approval(project, "requirements")
        return _copy(self._sections(project))

    def _seed_design_revision(self, project: FakeProject) -> dict[str, object]:
        design = project.design
        if design is None or not self._approvals(project)["design"]:
            raise ValueError("the design of the project is not approved")
        package = copy.deepcopy(design["package"])
        assertion = SEED_TEXTS[self.language]["assertion"]
        if assertion in package["owner_assertions"]:
            raise ValueError("the design already holds the seeded assertion")
        package["owner_assertions"] = [*package["owner_assertions"], assertion]
        self._seeded(lambda: self._design_diff(project, design, package, project.account))
        return _copy(self._sections(project))

    def _seed_tasks(self, project: FakeProject) -> list[dict[str, object]]:
        twin_id = str(self._seed_twins(project)[0]["twin_id"])
        texts = SEED_TEXTS[self.language]
        change = next(
            (
                record
                for record in project.code_changes
                if _has_findings(self._latest_run(project, record["commit"]), twin_id)
            ),
            None,
        )
        if change is None:
            commit = str(self._seed_change(project, None, None, True)["commit"])
            change = next(item for item in project.code_changes if item["commit"] == commit)
        reviewed = self._latest_reviewed_run(project)
        if reviewed is not None and _has_findings(reviewed[1], twin_id):
            run_id = str(reviewed[0]["id"])
        else:
            run_id = str(self._seed_test_run(project, failed=True, reviewed=True)["id"])
        self._decide(project, change, "CODE_TASKS", None, [texts["verdict_task"]], [])
        verdict = project.code_tasks[-1]
        items = [
            {
                "text": None,
                "source": {
                    "kind": "CODE_CHANGE",
                    "commit": change["commit"],
                    "twin_id": twin_id,
                    "finding": 0,
                },
            },
            {
                "text": None,
                "source": {
                    "kind": "TEST_RUN",
                    "test_run_id": run_id,
                    "twin_id": twin_id,
                    "finding": 0,
                },
            },
            {"text": texts["owner_task"], "source": {"kind": "OWNER"}},
        ]
        _, tasks = self._created_tasks(project, _task_items({"tasks": items}))
        return copy.deepcopy([verdict, *tasks])

    def _seed_learning(
        self,
        project: FakeProject,
        twin: int | str,
        statements: Sequence[str] | None,
        source: str,
    ) -> dict[str, object]:
        if source not in ("TWIN_CRITIQUE", "OWNER"):
            raise ValueError("source must be TWIN_CRITIQUE or OWNER")
        chosen = self._seed_twin(project, twin)
        twin_id = str(chosen["twin_id"])
        defaults = SEED_TEXTS[self.language]["observations"]
        wanted = (
            [statement for statement, _ in defaults]
            if statements is None
            else [_cut_line(statement, MAX_OBSERVATION_LENGTH) for statement in statements]
        )
        if not wanted or (source == "TWIN_CRITIQUE" and len(wanted) > MAX_UPDATE_OBSERVATIONS):
            raise ValueError(f"give 1 to {MAX_UPDATE_OBSERVATIONS} statements")
        _valid_statements(wanted)
        if self._pending_update(project, twin_id) is not None:
            raise ValueError("a proposal of the twin waits for its decision")
        if self._active_count(project, twin_id) + len(wanted) > MAX_LEARNED_OBSERVATIONS:
            raise ValueError(f"a twin keeps at most {MAX_LEARNED_OBSERVATIONS} observations")
        material = self._seed_material(project, twin_id) if source == "TWIN_CRITIQUE" else {}
        moment = _iso(self._now())
        observations = [
            {
                "index": index,
                "statement": statement,
                "basis": None if source == "OWNER" else defaults[index % len(defaults)][1],
                "about": {"requirement": None, "screen": None},
                "contradicts_profile": None,
            }
            for index, statement in enumerate(wanted)
        ]
        if source == "OWNER":
            for observation in observations:
                version = project.development.get(twin_id, 0) + 1
                self._add_observation(
                    project,
                    chosen,
                    observation,
                    source="OWNER",
                    version=version,
                    moment=moment,
                    update_id=None,
                )
                project.development[twin_id] = version
            return self._learning_entry(project, chosen)
        update = self._update_of(
            project, chosen, self._seed_locale(), observations, material, COSTS["TWIN_UPDATE"]
        )
        version = project.development.get(twin_id, 0) + 1
        for observation in observations:
            self._add_observation(
                project,
                chosen,
                observation,
                source="TWIN_CRITIQUE",
                version=version,
                moment=moment,
                update_id=str(update["id"]),
            )
        project.development[twin_id] = version
        update["status"] = "APPROVED"
        update["decision"] = {
            "decided_at": moment,
            "kept": [int(item["index"]) for item in observations],
            "reason": None,
        }
        project.updates.insert(0, update)
        return self._learning_entry(project, chosen)

    def _seed_update(
        self,
        project: FakeProject,
        twin: int | str,
        observations: Sequence[Mapping[str, object]] | None,
    ) -> dict[str, object]:
        chosen = self._seed_twin(project, twin)
        twin_id = str(chosen["twin_id"])
        if self._pending_update(project, twin_id) is not None:
            raise ValueError("a proposal of the twin already waits for its decision")
        defaults = SEED_TEXTS[self.language]["observations"]
        given = (
            [{"statement": statement, "basis": basis} for statement, basis in defaults]
            if observations is None
            else [dict(item) for item in observations]
        )
        if len(given) > MAX_UPDATE_OBSERVATIONS:
            raise ValueError(f"a proposal holds at most {MAX_UPDATE_OBSERVATIONS} observations")
        proposed = []
        for index, item in enumerate(given):
            if not isinstance(item.get("statement"), str):
                raise ValueError("every observation needs a statement")
            about = item.get("about") or {}
            contradicts = item.get("contradicts_profile")
            proposed.append(
                {
                    "index": index,
                    "statement": _cut_line(str(item["statement"]), MAX_OBSERVATION_LENGTH),
                    "basis": _cut_line(
                        str(item.get("basis") or defaults[index % len(defaults)][1]),
                        MAX_BASIS_LENGTH,
                    ),
                    "about": {
                        "requirement": about.get("requirement"),
                        "screen": about.get("screen"),
                    },
                    "contradicts_profile": None
                    if contradicts is None
                    else _cut_line(str(contradicts), MAX_BASIS_LENGTH),
                }
            )
        _valid_statements([str(item["statement"]) for item in proposed])
        material = self._seed_material(project, twin_id)
        update = self._update_of(
            project, chosen, self._seed_locale(), proposed, material, COSTS["TWIN_UPDATE"]
        )
        project.updates.insert(0, update)
        return copy.deepcopy(update)

    def _seed_material(self, project: FakeProject, twin_id: str) -> dict[str, int]:
        changes, tests = self._new_material(project, twin_id)
        if not changes and not tests:
            raise ValueError(
                "the twin has no new material: seed a reviewed change or test run first"
            )
        return {
            "changes": min(len(changes), MAX_UPDATE_CHANGES),
            "tests": min(len(tests), MAX_UPDATE_TESTS),
        }

    def _seed(
        self,
        project: FakeProject,
        through: str,
        *,
        approve: bool,
        dropped: Sequence[str] = (),
        requirements_schema_version: int = 2,
    ) -> None:
        account = project.account
        steps = STAGES[: STAGES.index(through) + 1]
        texts = SEED_BRIEF[self.language]
        provided = {
            "name": project.name,
            "description": texts["description"],
            "problem": texts["problem"],
            "goals": texts["goals"],
            "target_users": PERSONAS[self.language][: self.twins],
            "functional_requirements": texts["functional_requirements"],
            "domain": texts["domain"],
        }
        unknown = {item for item in BriefField if item.value not in provided}
        self._append_brief(
            project, create_project_brief(**provided, unknown_fields=unknown), account
        )
        if approve:
            self._approve(project, "brief")
        if "team" not in steps:
            return
        brief = project.brief
        assert brief is not None
        constraints = self._team_rules(project, brief, dropped)
        self._append_team(
            project,
            self._generated_team(project, brief, constraints, dropped),
            "PROPOSER_GENERATED",
            account,
        )
        if approve:
            self._approve(project, "team")
        if "twins" not in steps:
            return
        for persona in self._propose_personas(project, account):
            versions = project.personas[str(persona["persona_id"])]
            self._decide_persona(project, versions, "CONFIRM", None, account)
        self._create_twins(project, self._current_personas(project), account)
        if approve:
            self._approve(project, "twins")
        if "requirements" not in steps:
            return
        self._append_requirements(
            project,
            self._specification(project, schema_version=requirements_schema_version),
            account,
        )
        if approve:
            self._approve(project, "requirements")
        if "design" not in steps:
            return
        package = self._design_package(project)
        chosen = str(package["recommended_alternative_id"])
        self._append_design(project, package, account)
        selected = self._mockup_package(project, package, chosen, [])
        design = self._append_design(project, selected, account)
        if self.hosted:
            project.mockups[chosen] = {
                "status": "MOCKUP_GENERATED",
                "generation_id": self._new_id(),
                "design_version_id": design["id"],
                "design_content_hash": design["content_hash"],
                "package": copy.deepcopy(selected),
                "approach": APPROACHES[self.language][0],
                "changes": [],
                "warnings": _mockup_warnings(selected, project.specification["specification"]),
                "cost_microusd": COSTS["MOCKUP"],
            }
        if approve:
            self._approve(project, "design")


def _has_findings(document: Mapping[str, object] | None, twin_id: object) -> bool:
    critique = _critique_of(document, twin_id)
    return critique is not None and bool(critique["findings"])


def _valid_statements(statements: Sequence[str]) -> None:
    keys = [_comparable(statement) for statement in statements]
    if not all(keys) or len(set(keys)) != len(keys):
        raise ValueError("the statements must hold words and differ from each other")


def _seeded_result(path: Mapping[str, object], status: str, title: str) -> dict[str, object]:
    count = len(path["steps"])
    steps = []
    for index, step in enumerate(path["steps"], start=1):
        failed = status == "FAILED" and index == count
        expect = step["expect"]
        detail = None
        if failed and expect is not None:
            detail = _cut_text(f"{expect['kind']}: {expect['text']}", MAX_STEP_DETAIL_LENGTH)
        steps.append(
            {
                "index": index,
                "status": "FAILED" if failed else "DONE",
                "detail": detail,
                "url": SEED_PAGE,
                "title": _cut_text(title, MAX_SNAPSHOT_TITLE_LENGTH),
                "screenshot": f"{path['code']}/chrome/{index:02d}.png",
            }
        )
    return {
        "path": copy.deepcopy(dict(path)),
        "browser": "chrome",
        "status": status,
        "seconds": 2.5,
        "steps": steps,
        "page_text": _cut_text(title, MAX_PAGE_TEXT_LENGTH),
    }


def _without_requirement(specification: Mapping[str, object], identifier: str) -> dict[str, object]:
    proposed = copy.deepcopy(dict(specification))
    proposed["requirements"] = [
        item for item in proposed["requirements"] if str(item["id"]) != identifier
    ]
    dropped = set()
    criteria = []
    for item in proposed["acceptance_criteria"]:
        item["requirement_ids"] = [
            value for value in item["requirement_ids"] if str(value) != identifier
        ]
        if item["requirement_ids"]:
            criteria.append(item)
        else:
            dropped.add(str(item["id"]))
    proposed["acceptance_criteria"] = criteria
    for key in ("user_stories", "scenarios", "risks", "definition_of_done"):
        for item in proposed[key]:
            item["requirement_ids"] = [
                value for value in item["requirement_ids"] if str(value) != identifier
            ]
    for scenario in proposed["scenarios"]:
        scenario["acceptance_criterion_ids"] = [
            value for value in scenario["acceptance_criterion_ids"] if str(value) not in dropped
        ]
    return proposed
