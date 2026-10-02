from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import twin_learning as learning_api
from orchestwin.cli.errors import BUDGET_CODES, SPENDING_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import publish
from orchestwin.cli.flows.align_review import titles
from orchestwin.cli.flows.code_order import project_language
from orchestwin.cli.flows.design_state import wrapped
from orchestwin.cli.flows.review import review_locale
from orchestwin.cli.flows.test_plan import budget_error
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.align_review import Titles
    from orchestwin.cli.flows.twin_selection import Twin
    from orchestwin.cli.project import ProjectFolder

LIMIT_SECONDS: Final = 900.0
MICRO_USD: Final = 1_000_000
PAYMENT_REQUIRED: Final = 402
ATTEMPTS: Final = 5
KEEP: Final = "KEEP"
EDIT: Final = "EDIT"
DROP: Final = "DROP"
ANSWERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "k": KEEP,
        "keep": KEEP,
        "t": KEEP,
        "tieni": KEEP,
        "e": EDIT,
        "edit": EDIT,
        "c": EDIT,
        "correggi": EDIT,
        "d": DROP,
        "drop": DROP,
        "s": DROP,
        "scarta": DROP,
    }
)
SPENDING_REFUSED: Final = "SPENDING_REFUSED"
STOPPED: Final = frozenset({"INPUT_CLOSED", "ANSWER_NOT_VALID"})
UNFINISHED: Final = frozenset({"GENERATION_LOST", "GENERATION_STILL_RUNNING"})
FAILURE_PREFIX: Final = "twins.update_errors"


@dataclass(frozen=True, slots=True)
class Subject:
    twin: Twin
    entry: Mapping[str, object]

    @property
    def name(self) -> str:
        return self.twin.name

    @property
    def number(self) -> int:
        return self.twin.number

    @property
    def label(self) -> str:
        return learning_api.label_of(self.entry, self.twin.version_number)

    @property
    def pending(self) -> Mapping[str, object] | None:
        return learning_api.pending_update(self.entry)

    @property
    def new_material(self) -> bool:
        return learning_api.has_new_material(self.entry)


def run_update(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    subjects: Sequence[Subject],
    *,
    available: bool,
    evidence: Mapping[str, object] | None = None,
) -> int:
    return TwinUpdates(context, client, project, evidence=evidence).run(
        subjects, available=available
    )


def publish_folder(context: CommandContext, client: StudioClient, project: ProjectFolder) -> None:
    console = context.console
    console.write()
    try:
        found = publish.publish_and_pull(context, client, project)
    except CliError as error:
        inner = error.values.get("code")
        shown = inner if isinstance(inner, str) and inner else error.code
        console.say("twins.folder_not_updated", code=shown)
        return
    console.say("twins.folder_updated", version=found.version_number)


class TwinUpdates:
    def __init__(
        self,
        context: CommandContext,
        client: StudioClient,
        project: ProjectFolder,
        *,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        link = project.link()
        self.context = context
        self.console = context.console
        self.client = client
        self.project = project
        self.project_id = link.project_id
        self.locale = review_locale(project_language(project, context.language))
        self.names: Titles | None = None
        self.decided = 0
        self.spent = 0
        self.failed = False
        self.refused = False
        self.stopped = False
        self.evidence = evidence

    def run(self, subjects: Sequence[Subject], *, available: bool) -> int:
        if not available and all(subject.pending is None for subject in subjects):
            self.console.error("twins.update_no_model")
            return 1
        plan = self.classify(subjects, available=available)
        generating = [subject for subject, resumed in plan if not resumed]
        if generating and not self.confirmed(generating):
            plan = [(subject, resumed) for subject, resumed in plan if resumed]
        for subject, resumed in plan:
            if self.stopped:
                break
            update = subject.pending if resumed else self.generated(subject)
            if update is not None:
                self.review(subject, update)
        if self.spent > 0:
            self.console.write()
            amount = costs.usd_text(self.spent / MICRO_USD, self.context.language)
            self.console.say("twins.update_cost", amount=amount)
        if self.decided > 0:
            publish_folder(self.context, self.client, self.project)
        return self.status()

    def status(self) -> int:
        if self.stopped:
            return 1
        if self.refused:
            return SPENDING_STATUS
        return 1 if self.failed else 0

    def classify(
        self, subjects: Sequence[Subject], *, available: bool
    ) -> list[tuple[Subject, bool]]:
        plan: list[tuple[Subject, bool]] = []
        missing_model = False
        for subject in subjects:
            if subject.pending is not None:
                if self.evidence is not None:
                    pending_source = subject.pending.get("evidence") or {}
                    if pending_source.get("source_id") != self.evidence.get(
                        "id"
                    ) or pending_source.get("source_version") != self.evidence.get("version"):
                        self.report(subject, learning_api.UPDATE_PENDING)
                        self.failed = True
                        continue
                self.console.say("twins.update_resumed", name=subject.name)
                plan.append((subject, True))
            elif not subject.new_material and self.evidence is None:
                self.console.say("twins.update_nothing_new", name=subject.name)
            elif not available:
                missing_model = True
            else:
                plan.append((subject, False))
        if missing_model:
            self.console.error("twins.update_no_model")
            self.failed = True
        return plan

    def confirmed(self, subjects: Sequence[Subject]) -> bool:
        names = ", ".join(subject.name for subject in subjects)
        self.console.say("twins.update_to_generate", names=names)
        operations = [learning_api.UPDATE_OPERATION] * len(subjects)
        try:
            costs.confirm_spending(self.context, self.client, operations)
        except CliError as error:
            if error.code != SPENDING_REFUSED:
                raise
            self.console.error("errors.SPENDING_REFUSED")
            self.refused = True
            return False
        return True

    def generated(self, subject: Subject) -> Mapping[str, object] | None:
        label = self.context.text("twins.update_label", name=subject.name)
        path = learning_api.propose_path(self.project_id, subject.twin.twin_id)
        body = learning_api.propose_body(self.locale)
        if self.evidence is not None:
            body.update(evidence_id=self.evidence["id"], evidence_version=self.evidence["version"])
        self.console.write()
        try:
            result = jobs.generate(
                self.context,
                self.client,
                self.project_id,
                path,
                body,
                label=label,
                limit_seconds=LIMIT_SECONDS,
            )
        except CliError as error:
            if error.code not in UNFINISHED:
                raise
            self.report(subject, error.code)
            self.failed = True
            return None
        if result.status_code < 400:
            update = learning_api.proposal_of(result.body)
            if update is None:
                raise ApiFailure("API_FAILURE", http_status=result.status_code)
            self.spent += learning_api.update_cost(update)
            return update
        return self.refused_proposal(subject, learning_api.failure(result.status_code, result.body))

    def refused_proposal(
        self, subject: Subject, failure: ApiFailure
    ) -> Mapping[str, object] | None:
        code = failure.code
        update_id = failure.values.get("update_id")
        if code == learning_api.UPDATE_PENDING and isinstance(update_id, str) and update_id:
            self.console.say("twins.update_already_waiting", name=subject.name)
            try:
                return learning_api.update_of(self.client, self.project_id, update_id)
            except ApiFailure as other:
                self.report(subject, other.code)
                self.failed = True
                return None
        if code == learning_api.NOTHING_NEW:
            self.console.say("twins.update_nothing_new", name=subject.name)
            return None
        if failure.http_status == PAYMENT_REQUIRED or code in BUDGET_CODES:
            error = budget_error(
                self.context, self.client, self.project, code, learning_api.UPDATE_OPERATION
            )
            self.report(subject, error.code, **error.values)
            self.refused = True
            return None
        self.report(subject, code)
        self.failed = True
        return None

    def review(self, subject: Subject, update: Mapping[str, object]) -> None:
        context = self.context
        console = self.console
        console.write()
        console.heading(
            context.text("twins.update_heading", name=subject.name, label=subject.label)
        )
        changes, tests = learning_api.update_material(update)
        evidence = update.get("evidence")
        if isinstance(evidence, Mapping):
            console.say(
                "twins.update_evidence",
                source=evidence.get("source_id", "-"),
                version=evidence.get("source_version", "-"),
                count=evidence.get("rejected_changes", 0),
            )
        else:
            console.say("twins.update_material", changes=changes, tests=tests)
        comment = learning_api.update_comment(update)
        if comment:
            wrapped(
                context, context.text("twins.update_comment", name=subject.name, comment=comment)
            )
        observations = learning_api.proposed_observations(update)
        if learning_api.update_status(update) == learning_api.EMPTY or not observations:
            wrapped(context, context.text("twins.update_empty", name=subject.name))
            return
        try:
            kept = self.chosen(observations)
            reason = None if kept else self.reason()
        except CliError as error:
            if error.code not in STOPPED:
                raise
            console.write()
            console.error("twins.update_left_pending", name=subject.name)
            self.stopped = True
            return
        self.decide(subject, update, kept, reason)

    def chosen(self, observations: Sequence[Mapping[str, object]]) -> list[learning_api.Kept]:
        context = self.context
        self.console.say("twins.update_how")
        kept: list[learning_api.Kept] = []
        count = len(observations)
        for position, observation in enumerate(observations, start=1):
            self.console.write()
            statement = _text(observation.get("statement"))
            wrapped(
                context,
                context.text(
                    "twins.update_observation", number=position, count=count, statement=statement
                ),
            )
            for line in self.details(observation):
                wrapped(context, line, indent="  ")
            answer = self.answer()
            if answer == DROP:
                continue
            index = learning_api.observation_index(observation, position - 1)
            edited = self.edited() if answer == EDIT else ""
            changed = edited if edited and edited != statement else None
            kept.append(learning_api.Kept(index, changed))
        return kept

    def details(self, observation: Mapping[str, object]) -> list[str]:
        context = self.context
        lines: list[str] = []
        basis = _text(observation.get("basis"))
        if basis:
            lines.append(context.text("twins.update_basis", basis=basis))
        about = self.about(observation)
        if about:
            lines.append(context.text("twins.update_about", about=about))
        contradiction = _text(observation.get("contradicts_profile"))
        if contradiction:
            lines.append(context.text("twins.update_contradiction", text=contradiction))
        evidence = observation.get("evidence")
        if isinstance(evidence, Mapping):
            citation = evidence.get("citation") or {}
            lines.append(
                context.text(
                    "twins.update_citation",
                    effect=evidence.get("effect", "-"),
                    field=evidence.get("field", "-"),
                    version=citation.get("source_version", "-"),
                    first=citation.get("start_line", "-"),
                    last=citation.get("end_line", "-"),
                    quote=citation.get("quote", ""),
                )
            )
        return lines

    def about(self, observation: Mapping[str, object]) -> str:
        requirement, screen = learning_api.observation_about(observation)
        if requirement is None and screen is None:
            return ""
        if self.names is None:
            self.names = titles(self.project)
        parts: list[str] = []
        if requirement is not None:
            title = self.names.requirements.get(requirement)
            parts.append(
                self.context.text("twins.about_requirement", code=requirement, title=title)
                if title
                else self.context.text("twins.about_requirement_code", code=requirement)
            )
        if screen is not None:
            title = self.names.screens.get(screen)
            parts.append(
                self.context.text("twins.about_screen", code=screen, title=title)
                if title
                else self.context.text("twins.about_screen_code", code=screen)
            )
        return ", ".join(parts)

    def answer(self) -> str:
        for _ in range(ATTEMPTS):
            reply = self.console.ask("twins.update_question", required=False)
            wanted = reply.strip().casefold()
            if not wanted:
                return KEEP
            found = ANSWERS.get(wanted)
            if found is not None:
                return found
            self.console.say("twins.update_answer_invalid")
        raise CliError("ANSWER_NOT_VALID")

    def edited(self) -> str:
        for _ in range(ATTEMPTS):
            line = _text(self.console.ask("twins.update_edit", required=False))
            if len(line) <= learning_api.MAX_OBSERVATION_LENGTH:
                return line
            self.console.say(
                "twins.update_edit_too_long", limit=learning_api.MAX_OBSERVATION_LENGTH
            )
        raise CliError("ANSWER_NOT_VALID")

    def reason(self) -> str | None:
        self.console.write()
        for _ in range(ATTEMPTS):
            line = _text(self.console.ask("twins.update_reason", required=False))
            if len(line) <= learning_api.MAX_REASON_LENGTH:
                return line or None
            self.console.say("twins.update_reason_too_long", limit=learning_api.MAX_REASON_LENGTH)
        raise CliError("ANSWER_NOT_VALID")

    def decide(
        self,
        subject: Subject,
        update: Mapping[str, object],
        kept: Sequence[learning_api.Kept],
        reason: str | None,
    ) -> None:
        update_id = learning_api.update_id_of(update)
        decision = learning_api.APPROVE if kept else learning_api.REJECT
        try:
            answer = learning_api.decide(
                self.client, self.project_id, update_id, decision, kept=kept, reason=reason
            )
        except ApiFailure as failure:
            self.console.write()
            self.report_decision(subject, failure)
            self.failed = True
            return
        self.decided += 1
        entry = learning_api.twin_of(answer)
        label = learning_api.label_of(entry, subject.twin.version_number)
        self.console.write()
        if decision == learning_api.REJECT:
            self.console.say("twins.update_rejected", name=subject.name, label=label)
            return
        evidence = update.get("evidence")
        if isinstance(evidence, Mapping):
            self.console.say(
                "twins.update_evidence_approved",
                name=subject.name,
                label=label,
                count=len(kept),
                source=(self.evidence or {}).get("code") or evidence.get("source_id", "-"),
                version=evidence.get("source_version", "-"),
            )
            return
        codes = learning_api.learned_codes(entry, update_id)
        self.console.say(
            "twins.update_approved", name=subject.name, label=label, codes=", ".join(codes) or "-"
        )

    def report(self, subject: Subject, code: str, **values: object) -> None:
        reason = values.get("reason")
        candidates = [f"{FAILURE_PREFIX}.{code}"]
        if isinstance(reason, str) and reason:
            candidates.insert(0, f"{FAILURE_PREFIX}.{code}.{reason}")
        key = next((item for item in candidates if known(item)), None)
        if key is None:
            self.console.error("twins.update_failed", name=subject.name, code=code)
            return
        self.console.error(key, **self.values(subject, values))

    def report_decision(self, subject: Subject, failure: ApiFailure) -> None:
        key = f"{FAILURE_PREFIX}.{failure.code}"
        if not known(key):
            self.console.error(
                "twins.update_decision_failed",
                name=subject.name,
                number=subject.number,
                code=failure.code,
            )
            return
        self.console.error(key, **self.values(subject, {}))

    def values(self, subject: Subject, values: Mapping[str, object]) -> dict[str, object]:
        return {
            **values,
            "name": subject.name,
            "number": subject.number,
            "limit": learning_api.MAX_LEARNED_OBSERVATIONS,
        }


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
