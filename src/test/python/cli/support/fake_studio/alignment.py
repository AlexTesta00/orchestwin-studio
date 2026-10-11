from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.api.knowledge_alignment import LATEST_RUN_KEYS
from orchestwin.projects import knowledge_alignment

from .common import _by_id, _copy, _error, _first_line, _first_screen
from .fields import _Fields
from .texts import ALIGNMENT_TEXTS, COSTS
from .values import (
    COMMIT_PATTERN,
    DEFAULT_LOCALE,
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    REQUIREMENT_CODE,
    SEED_DIFF,
    SEED_FILE,
    _Answer,
    _Invalid,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


ALIGNMENT_RUN_FIELDS = ("locale", "from_commit", "to_commit", "commits")
PROPOSAL_APPLY_FIELDS = ("text", "locale")
PROPOSAL_SKIP_FIELDS = ("reason",)
PROPOSAL_STATUS_FILTERS = ("waiting", "all")
APPLY_OPERATIONS = {"REQUIREMENTS": "REQUIREMENTS_CHANGE", "DESIGN": "DESIGN_CHANGE"}
EXCERPT_LINES = 8


class _AlignmentRoutes:
    def _route_alignment_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ALIGNMENT_RUN_FIELDS)
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        from_commit = fields.pattern("from_commit", COMMIT_PATTERN, required=False, nullable=True)
        to_commit = fields.pattern("to_commit", COMMIT_PATTERN)
        commits = fields.texts(
            "commits",
            required=True,
            nullable=False,
            minimum_items=1,
            maximum_items=knowledge_alignment.MAX_COMMITS,
            item_pattern=COMMIT_PATTERN,
        )
        fields.check()
        listed = [item.lower() for item in commits or []]
        start = None if from_commit is None else from_commit.lower()
        end = str(to_commit).lower()
        if (
            len(set(listed)) != len(listed)
            or not _same_commit(end, listed[-1])
            or (start is not None and any(_same_commit(start, item) for item in listed))
        ):
            raise _Invalid([_error(("body",), "value_error")])
        body = {"locale": locale, "from_commit": start, "to_commit": end, "commits": listed}
        return self._later(
            call, "KNOWLEDGE_ALIGNMENT", body, lambda: self._aligned_knowledge(call, body)
        )

    def _aligned_knowledge(self, call: _Call, body: Mapping[str, object]) -> _Answer:
        project = self._code_project(call)
        records = [self._find_change(project, str(commit)) for commit in body["commits"]]
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED"})
        identifier = self._record(project, "KNOWLEDGE_ALIGNMENT")
        from_commit = body["from_commit"]
        try:
            run = self._stored_alignment_run(
                project,
                records,
                str(body["locale"]),
                None if from_commit is None else str(from_commit),
                reference,
                COSTS["KNOWLEDGE_ALIGNMENT"],
                [identifier],
                self._proposed_updates(project, records),
            )
        except ValueError as error:
            raise _Refusal(422, "invalid_request") from error
        return _Answer(201, {"run": copy.deepcopy(run)})

    def _next_proposal_number(self, project: FakeProject) -> int:
        numbers = [
            knowledge_alignment.proposal_number(str(item["code"])) or 0
            for run in project.knowledge_runs
            for item in run["proposals"]
        ]
        return max(numbers, default=0) + 1

    def _stored_alignment_run(
        self,
        project: FakeProject,
        records: Sequence[Mapping[str, object]],
        locale: str,
        from_commit: str | None,
        reference: Mapping[str, object],
        cost: int,
        generation_ids: Sequence[str],
        updates: Sequence[knowledge_alignment.ProposedUpdate],
    ) -> dict[str, object]:
        run_id = UUID(self._new_id())
        moment = self._now()
        project_id, owner_id = UUID(project.id), UUID(project.account.id)
        first_number = self._next_proposal_number(project)
        proposals = tuple(
            knowledge_alignment.AlignmentProposal(
                id=UUID(self._new_id()),
                run_id=run_id,
                project_id=project_id,
                owner_user_id=owner_id,
                number=first_number + index,
                section=item.section,
                title=item.title,
                request=item.request,
                rationale=item.rationale,
                subjects=item.subjects,
                origin=item.origin,
                status=knowledge_alignment.ProposalStatus.PROPOSED,
                created_at=moment,
            )
            for index, item in enumerate(updates)
        )
        commits = tuple(str(record["commit"]) for record in records)
        texts = ALIGNMENT_TEXTS[self.language]
        line = _first_line(str(records[-1]["message"]))
        summary = (
            texts["summary"].format(count=len(records), line=line)
            if proposals
            else texts["summary_empty"]
        )
        requirements, design = reference["requirements"], reference["design"]
        run = knowledge_alignment.KnowledgeAlignmentRun(
            id=run_id,
            project_id=project_id,
            owner_user_id=owner_id,
            from_commit=from_commit,
            to_commit=commits[-1],
            commits=commits,
            locale=locale,
            requirements_version_number=int(requirements["version_number"]),
            design_version_number=int(design["version_number"]),
            alternative_code=str(design["alternative_code"]),
            summary=knowledge_alignment.normalize_summary(summary),
            created_at=moment,
            cost_microusd=cost,
            generation_ids=tuple(UUID(item) for item in generation_ids),
            proposals=proposals,
        )
        snapshot = run.to_snapshot()
        project.knowledge_runs.insert(0, snapshot)
        return snapshot

    def _proposed_updates(
        self, project: FakeProject, records: Sequence[Mapping[str, object]]
    ) -> tuple[knowledge_alignment.ProposedUpdate, ...]:
        specification, design = project.specification, project.design
        if specification is None or design is None:
            raise RuntimeError("an alignment run needs the approved requirements and design")
        changed = [record for record in records if str(record["diff"]).strip()]
        files = list(
            dict.fromkeys(str(item["path"]) for record in changed for item in record["files"])
        )
        if not changed or not files:
            return ()
        texts = ALIGNMENT_TEXTS[self.language]
        first = changed[0]
        line = _first_line(str(first["message"]))
        commits = tuple(str(record["commit"]) for record in changed)
        excerpt = _diff_excerpt(str(first["diff"]))
        items = specification["specification"]
        known = [str(item["code"]) for item in items["requirements"]]
        cited = [code for code in REQUIREMENT_CODE.findall(str(first["diff"])) if code in known]
        requirement = cited[0] if cited else known[0]
        screen = _first_screen(design["package"])
        criteria = tuple(str(item["code"]) for item in items["acceptance_criteria"][:1])
        cited_files = tuple(files[: knowledge_alignment.MAX_ORIGIN_FILES])
        return (
            knowledge_alignment.create_proposed_update(
                section="REQUIREMENTS",
                title=texts["requirements_title"].format(line=line),
                request=texts["requirements_request"].format(
                    code=requirement, file=files[0], line=line
                ),
                rationale=texts["requirements_rationale"].format(file=files[0]),
                origin=knowledge_alignment.ProposalOrigin(
                    commits=commits, files=(files[0],), excerpt=excerpt
                ),
                subjects=knowledge_alignment.ProposalSubjects(requirements=(requirement,)),
            ),
            knowledge_alignment.create_proposed_update(
                section="DESIGN",
                title=texts["design_title"].format(line=line),
                request=texts["design_request"].format(screen=screen, line=line),
                rationale=texts["design_rationale"].format(count=len(cited_files)),
                origin=knowledge_alignment.ProposalOrigin(
                    commits=commits, files=cited_files, excerpt=excerpt
                ),
                subjects=knowledge_alignment.ProposalSubjects(screens=(screen,)),
            ),
            knowledge_alignment.create_proposed_update(
                section="TESTS",
                title=texts["tests_title"].format(line=line),
                request=texts["tests_request"].format(
                    code=criteria[0] if criteria else requirement, line=line
                ),
                rationale=texts["tests_rationale"],
                origin=knowledge_alignment.ProposalOrigin(
                    commits=commits, files=(files[0],), excerpt=excerpt
                ),
                subjects=knowledge_alignment.ProposalSubjects(criteria=criteria),
            ),
        )

    def _alignment_proposals(
        self, project: FakeProject, *, waiting_only: bool = False
    ) -> list[dict[str, object]]:
        return [
            proposal
            for run in project.knowledge_runs
            for proposal in reversed(run["proposals"])
            if not waiting_only or proposal["status"] == "PROPOSED"
        ]

    def _find_proposal(self, project: FakeProject, code: str) -> dict[str, object]:
        number = knowledge_alignment.proposal_number(code)
        wanted = None if number is None else knowledge_alignment.proposal_code(number)
        found = next(
            (item for item in self._alignment_proposals(project) if item["code"] == wanted), None
        )
        if found is None:
            raise _Refusal(404, {"code": "ALIGNMENT_PROPOSAL_NOT_FOUND"})
        return found

    def _decided_proposal(
        self,
        project: FakeProject,
        proposal: dict[str, object],
        *,
        status: knowledge_alignment.ProposalStatus,
        note: str | None = None,
        applied_text: str | None = None,
        applied_diff_id: str | None = None,
    ) -> dict[str, object]:
        domain = knowledge_alignment.proposal_from_snapshot(
            proposal, project_id=UUID(project.id), owner_user_id=UUID(project.account.id)
        )
        try:
            decided = domain.with_decision(
                status=status,
                decided_at=self._now(),
                note=note,
                applied_text=applied_text,
                applied_diff_id=None if applied_diff_id is None else UUID(applied_diff_id),
            )
        except knowledge_alignment.ProposalAlreadyDecided as error:
            raise _Refusal(409, {"code": "ALIGNMENT_PROPOSAL_DECIDED"}) from error
        proposal.update(decided.to_snapshot())
        return proposal

    def _route_alignment_runs(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, {"items": [_alignment_run_item(run) for run in project.knowledge_runs]})

    def _route_alignment_run_view(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        run = _by_id(project.knowledge_runs, call.params["run_id"])
        if run is None:
            raise _Refusal(404, {"code": "KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND"})
        return _Answer(200, {"run": copy.deepcopy(run)})

    def _route_alignment_proposals(self, call: _Call) -> _Answer:
        status = call.value("status")
        if status is not None and status not in PROPOSAL_STATUS_FILTERS:
            raise _Invalid([_error(("query", "status"), "literal_error")])
        project = self._code_project(call)
        items = self._alignment_proposals(project, waiting_only=status in (None, "waiting"))
        latest = project.knowledge_runs[0] if project.knowledge_runs else None
        return _Answer(
            200,
            {
                "items": copy.deepcopy(items),
                "latest_run": None
                if latest is None
                else {key: latest[key] for key in LATEST_RUN_KEYS},
            },
        )

    def _route_apply_proposal(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), PROPOSAL_APPLY_FIELDS)
        text = fields.text(
            "text",
            required=False,
            nullable=True,
            maximum=knowledge_alignment.MAX_ANY_REQUEST_LENGTH,
        )
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        fields.check()
        project = self._code_project(call)
        proposal = self._find_proposal(project, call.params["code"])
        body = {"text": _stripped(text), "locale": locale}
        operation = APPLY_OPERATIONS.get(str(proposal["section"]))
        if operation is None:
            return self._applied_proposal(call, body)
        return self._later(call, operation, body, lambda: self._applied_proposal(call, body))

    def _applied_proposal(self, call: _Call, body: Mapping[str, object]) -> _Answer:
        project = self._code_project(call)
        proposal = self._find_proposal(project, call.params["code"])
        if proposal["status"] != "PROPOSED":
            raise _Refusal(409, {"code": "ALIGNMENT_PROPOSAL_DECIDED"})
        section = knowledge_alignment.ProposalSection(str(proposal["section"]))
        text = body["text"]
        chosen = str(proposal["request"]) if text is None else str(text)
        if not 1 <= len(chosen) <= knowledge_alignment.MAX_REQUEST_LENGTH[section]:
            raise _Refusal(422, "invalid_request")
        revision: dict[str, object] | None = None
        diff_id = None
        if section is knowledge_alignment.ProposalSection.REQUIREMENTS:
            answer = self._changed_requirements(call, chosen).body
            assert isinstance(answer, dict)
            revision = answer
            diff_id = str(answer["diff"]["id"])
        elif section is knowledge_alignment.ProposalSection.DESIGN:
            answer = self._changed_design(call, chosen).body
            assert isinstance(answer, dict)
            revision = answer
            diff_id = str(answer["revision"]["diff"]["id"])
        decided = self._decided_proposal(
            project,
            proposal,
            status=knowledge_alignment.ProposalStatus.APPLIED,
            applied_text=chosen,
            applied_diff_id=diff_id,
        )
        return _Answer(200, {"proposal": copy.deepcopy(decided), "revision": revision})

    def _route_skip_proposal(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), PROPOSAL_SKIP_FIELDS)
        reason = fields.text(
            "reason", required=False, nullable=True, maximum=knowledge_alignment.MAX_NOTE_LENGTH
        )
        fields.check()
        project = self._code_project(call)
        proposal = self._find_proposal(project, call.params["code"])
        decided = self._decided_proposal(
            project,
            proposal,
            status=knowledge_alignment.ProposalStatus.SKIPPED,
            note=_stripped(reason),
        )
        return _Answer(200, {"proposal": copy.deepcopy(decided)})

    def _seed_alignment_run(
        self, project: FakeProject, proposals: Sequence[object] | None
    ) -> dict[str, object]:
        reference = self._seed_ground(project)
        records = list(reversed(self._pending(project)))
        if not records:
            self._seed_change(project, None, None, False)
            records = list(reversed(self._pending(project)))
        aligned = self._aligned(project)
        from_commit = None if aligned is None else str(aligned["commit"])
        if proposals is None:
            updates = self._proposed_updates(project, records)
        else:
            updates = tuple(self._seeded_proposal(item, records) for item in proposals)
        return _copy(
            self._stored_alignment_run(
                project, records, self._seed_locale(), from_commit, reference, 0, [], updates
            )
        )

    def _seeded_proposal(
        self, item: object, records: Sequence[Mapping[str, object]]
    ) -> knowledge_alignment.ProposedUpdate:
        if isinstance(item, knowledge_alignment.ProposedUpdate):
            return item
        if not isinstance(item, Mapping):
            raise ValueError("a seeded proposal is a mapping or a ProposedUpdate")
        origin = item.get("origin")
        subjects = item.get("subjects")
        return knowledge_alignment.create_proposed_update(
            section=str(item["section"]),
            title=str(item["title"]),
            request=str(item["request"]),
            rationale=str(item.get("rationale") or ALIGNMENT_TEXTS[self.language]["rationale"]),
            origin=knowledge_alignment.ProposalOrigin(
                commits=tuple(str(record["commit"]) for record in records),
                files=(str(SEED_FILE["path"]),),
                excerpt=_diff_excerpt(SEED_DIFF),
            )
            if origin is None
            else knowledge_alignment.proposal_origin_from_snapshot(origin),
            subjects=None
            if subjects is None
            else knowledge_alignment.proposal_subjects_from_snapshot(subjects),
        )


def _same_commit(first: str, second: str) -> bool:
    return first.startswith(second) or second.startswith(first)


def _stripped(value: str | None) -> str | None:
    return None if value is None or not value.strip() else value.strip()


def _diff_excerpt(diff: str) -> str:
    lines: list[str] = []
    for raw in diff.splitlines():
        line = raw.rstrip()
        if not lines and not line:
            continue
        candidate = [*lines, line]
        if (
            len(candidate) > EXCERPT_LINES
            or len("\n".join(candidate)) > knowledge_alignment.MAX_EXCERPT_LENGTH
        ):
            break
        lines = candidate
    if not lines:
        lines = [diff.strip().splitlines()[0][: knowledge_alignment.MAX_EXCERPT_LENGTH]]
    return knowledge_alignment.normalize_excerpt("\n".join(lines))


def _alignment_run_item(run: Mapping[str, object]) -> dict[str, object]:
    proposals = run["proposals"]
    assert isinstance(proposals, list)
    return {
        **{key: copy.deepcopy(value) for key, value in run.items() if key != "proposals"},
        "waiting": sum(1 for item in proposals if item["status"] == "PROPOSED"),
        "proposals_count": len(proposals),
    }
