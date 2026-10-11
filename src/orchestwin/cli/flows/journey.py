from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import brief
from orchestwin.cli.console import ATTEMPTS, ProgressOutcome
from orchestwin.cli.errors import (
    BUDGET_CODES,
    INTERRUPTED_STATUS,
    PAYMENT_REQUIRED,
    ApiFailure,
    CliError,
)
from orchestwin.cli.flows import init_brief, init_requirements, init_team, init_twins
from orchestwin.cli.flows.publish import publish_approved
from orchestwin.cli.project import LINK_FILE, STEPS_FOLDER
from orchestwin.cli.shapes import version_number_of as version_number

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.answers import Answers
    from orchestwin.cli.project import ProjectFolder

STAGES: Final = ("brief", "team", "twins", "requirements")
FLOWS: Final = (init_brief, init_team, init_twins, init_requirements)
BUSY_CODE: Final = "TOO_MANY_GENERATIONS"
BUSY_ATTEMPTS: Final = 8
BUSY_SECONDS: Final = 15.0
MAX_RESTARTS: Final = 3
APPROVED: Final = "APPROVED"
MODEL_REFUSALS: Final = frozenset(
    {
        "PROPOSAL_REJECTED",
        "INVALID_PROPOSAL",
        "CANDIDATE_DERIVATION_REJECTED",
        "PERSISTENCE_REJECTED",
    }
)
STALE_CODES: Final = frozenset(
    {
        "ARTIFACT_STALE",
        "PROPOSAL_STALE",
        "STALE",
        "GATE_STATE_CONFLICT",
        "gate_state_conflict",
        "CONTEXT_CHANGED",
        "BRIEF_NOT_APPROVED",
        "BRIEF_APPROVAL_REQUIRED",
        "TEAM_APPROVAL_REQUIRED",
        "USER_MODELING_APPROVAL_REQUIRED",
    }
)
REQUEST_ERRORS: Final = frozenset({400, 401, 403, 404, 405})


def ask_idea(context: CommandContext) -> str:
    console = context.console
    for _ in range(ATTEMPTS):
        lines = [line.strip() for line in console.ask_text("init.idea").splitlines()]
        idea = "\n".join(line for line in lines if line)
        if idea and len(idea) <= brief.MAX_STATEMENT:
            return idea
        if idea:
            console.say("init.idea_too_long", limit=brief.MAX_STATEMENT)
        else:
            console.say("init.idea_required")
    raise CliError("ANSWER_NOT_VALID")


def code_of(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    if isinstance(detail, str) and detail:
        return detail
    for key in ("status", "outcome"):
        value = document.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class Journey:
    def __init__(
        self,
        context: CommandContext,
        client: StudioClient,
        project: ProjectFolder,
        *,
        script: Answers | None,
        until: str | None,
        idea: str | None,
    ) -> None:
        self.context = context
        self.console = context.console
        self.client = client
        self.project = project
        self.project_id = project.link().project_id
        self.script = script
        self.until = until
        self.idea = idea
        self.explained = False
        self.retried = False
        self.designer_note = False
        self.partial_folders = True
        self.versions: dict[str, int | None] = {}
        self.announced: set[str] = set()

    def text(self, key: str, /, **values: object) -> str:
        return self.console.text(key, **values)

    def say(self, key: str, /, **values: object) -> None:
        self.console.say(key, **values)

    def stage_name(self, stage: str) -> str:
        return self.text(f"common.stage_{stage}")

    def run(self) -> int:
        restarts = 0
        while True:
            try:
                return self._walk()
            except CliError as error:
                if error.code != "STATE_CHANGED" or restarts >= MAX_RESTARTS:
                    raise
                restarts += 1
                self.say("init.state_changed", code=error.values.get("code", ""))

    def _walk(self) -> int:
        for number, (stage, flow) in enumerate(zip(STAGES, FLOWS, strict=True), start=1):
            state = flow.read(self)
            if state.approved:
                self._announce(stage, state.number)
                self.refresh_folder(stage, state.number, approved_now=False)
            else:
                self.console.write()
                self.console.heading(
                    self.text(
                        "init.step_heading",
                        number=number,
                        total=len(STAGES),
                        step=self.stage_name(stage),
                    )
                )
                if not flow.run(self, state):
                    return 0
                self.refresh_folder(stage, self.versions.get(stage), approved_now=True)
            if stage == self.until and number < len(STAGES):
                self.say(
                    "init.until_stop",
                    step=self.stage_name(stage),
                    next=self.stage_name(STAGES[number]),
                )
                return 0
        self._finish()
        return 0

    def refresh_folder(self, stage: str, number: int | None, *, approved_now: bool) -> None:
        if not self.partial_folders or (not approved_now and self._folder_holds(stage, number)):
            return
        try:
            found = publish_approved(self.context, self.client, self.project)
        except CliError as error:
            if error.status == INTERRUPTED_STATUS:
                raise
            self.partial_folders = False
            self.say("init.folder_not_updated", code=str(error.values.get("code", error.code)))
            return
        if found is None:
            self.partial_folders = False
            return
        self.say("init.folder_updated", version=found.version_number)

    def _folder_holds(self, stage: str, number: int | None) -> bool:
        try:
            local = knowledge.summary(self.project.knowledge)
        except CliError:
            return False
        entry = None if local is None or stage not in local.progress else local.stage(stage)
        return entry is not None and entry.version_number == number

    def _announce(self, stage: str, number: int | None) -> None:
        if stage in self.announced:
            return
        self.announced.add(stage)
        self.say(
            "init.already_approved",
            step=self.stage_name(stage),
            version="-" if number is None else number,
        )

    def _finish(self) -> None:
        link = self.project.link()
        self.console.write()
        self.say("init.done", name=link.project_name)
        for stage in STAGES:
            number = self.versions.get(stage)
            self.say(
                "init.done_step",
                step=self.stage_name(stage),
                version="-" if number is None else number,
            )
        self.say(
            "init.done_saved",
            steps=str(self.project.local / STEPS_FOLDER),
            link=str(self.project.local / LINK_FILE),
        )
        self.say("init.next_design")
        if self.designer_note:
            self.say("init.designer_missing_end")

    def statement(self) -> str:
        if self.idea:
            return self.idea
        if self.script is not None:
            if self.script.idea:
                return self.script.idea
            raise self.script.missing("idea")
        self.idea = ask_idea(self.context)
        return self.idea

    def keep(
        self, stage: str, version: Mapping[str, object], gate: Mapping[str, object]
    ) -> Path | None:
        self.versions[stage] = version_number(version)
        saved = self.project.step(stage)
        if saved is not None and saved.get("version") == version and saved.get("gate") == gate:
            return None
        return self.project.save_step(stage, version, gate, self.context.environment.now())

    def conclude(
        self, stage: str, version: Mapping[str, object], gate: Mapping[str, object]
    ) -> None:
        self.announced.add(stage)
        self.keep(stage, version, gate)
        path = self.project.local / STEPS_FOLDER / f"{stage}.json"
        self.say(
            "init.step_approved",
            step=self.stage_name(stage),
            version=version_number(version) or "-",
            path=path.relative_to(self.project.root).as_posix(),
        )

    def waiting(self, label: str, send: Callable[[], tuple[int, object]]) -> tuple[int, object]:
        with self.console.progress(label) as progress:
            status, document = send()
            if status >= jobs.FAILURE_STATUS:
                progress.set_outcome(ProgressOutcome.NOT_COMPLETED)
            return status, document

    def job(
        self,
        path: str,
        body: object | None = None,
        *,
        operation: str,
        label: str,
        passthrough: Collection[str] = (),
    ) -> tuple[int, object]:
        running = jobs.running_jobs(self.client, self.project_id)
        if any(item.get("operation") == operation for item in running):
            self.say("init.generation_resumed", label=label)

        def send() -> tuple[int, object]:
            result = jobs.generate(
                self.context, self.client, self.project_id, path, body, label=label
            )
            return result.status_code, result.body

        return self.generate(send, operation=operation, label=label, passthrough=passthrough)

    def generate(
        self,
        send: Callable[[], tuple[int, object]],
        *,
        operation: str,
        label: str,
        passthrough: Collection[str] = (),
        again: Callable[[], tuple[int, object]] | None = None,
    ) -> tuple[int, object]:
        waits = 0
        while True:
            status, document = send()
            code = code_of(document)
            if status < 400:
                self.retried = False
                return status, document
            if code in passthrough:
                return status, document
            if status == 429 or code == BUSY_CODE:
                if waits >= BUSY_ATTEMPTS:
                    raise CliError(BUSY_CODE, values={"label": label})
                waits += 1
                self.say(
                    "init.busy",
                    seconds=int(BUSY_SECONDS),
                    attempt=waits,
                    attempts=BUSY_ATTEMPTS,
                )
                self.context.environment.sleep(BUSY_SECONDS)
                continue
            if status == PAYMENT_REQUIRED or code in BUDGET_CODES:
                raise self.budget_error(code, operation)
            if status == 409 and code not in MODEL_REFUSALS:
                raise self.changed(code)
            if status in REQUEST_ERRORS or (status == 422 and code in {None, "invalid_request"}):
                raise ApiFailure(code or "API_FAILURE", http_status=status, detail=document)
            shown = code or f"HTTP {status}"
            if not self.retry(label, shown, operation):
                raise CliError("GENERATION_FAILED", values={"label": label, "code": shown})
            self.retried = True
            if again is not None:
                return again()

    def retry(self, label: str, code: str, operation: str) -> bool:
        if self.retried:
            return False
        self.say("init.generation_failed", label=label, code=code)
        if self.script is not None and not self.context.assume_yes:
            return False
        if costs.uses_subscription(self.client):
            if self.script is not None:
                self.say("init.retry_assumed_subscription")
                return True
            return self.console.confirm("init.retry_confirm_subscription", default=True)
        amount = costs.amount_text(costs.estimate([operation]), self.context.language)
        if self.script is not None:
            self.say("init.retry_assumed", amount=amount)
            return True
        return self.console.confirm("init.retry_confirm", default=True, amount=amount)

    def budget_error(self, code: str | None, operation: str) -> CliError:
        return costs.budget_error(self.context, self.client, self.project_id, code, operation)

    def changed(self, code: str | None) -> CliError:
        return CliError("STATE_CHANGED", values={"code": code or "CONFLICT"})

    def refused(self, status: int, document: object) -> CliError:
        code = code_of(document) or "API_FAILURE"
        if status == 409:
            return self.changed(code)
        return ApiFailure(code, http_status=status, detail=document)

    def approve(
        self,
        submit: Callable[[], tuple[int, object]],
        decide: Callable[[], tuple[int, object]],
        *,
        step: str,
    ) -> Mapping[str, object]:
        status, document = submit()
        if not 200 <= status < 300:
            raise self.gate_refused(status, document, step)
        gate = _gate(document)
        if gate.get("status") == APPROVED:
            return gate
        status, document = decide()
        if not 200 <= status < 300:
            raise self.gate_refused(status, document, step)
        gate = _gate(document)
        if gate.get("status") != APPROVED:
            raise CliError(
                "GATE_REFUSED",
                values={"step": self.stage_name(step), "code": str(gate.get("status"))},
            )
        return gate

    def gate_refused(self, status: int, document: object, step: str) -> CliError:
        code = code_of(document) or "API_FAILURE"
        if code == "BRIEF_INCOMPLETE" and isinstance(document, Mapping):
            fields = [str(item) for item in document.get("missing_fields") or []]
            return CliError(
                "BRIEF_INCOMPLETE",
                values={
                    "fields": ", ".join(self.text(f"init.field_{item}") for item in fields),
                    "missing": tuple(fields),
                },
            )
        if code in STALE_CODES:
            return self.changed(code)
        if status in REQUEST_ERRORS or status >= 500:
            return ApiFailure(code, http_status=status, detail=document)
        return CliError("GATE_REFUSED", values={"step": self.stage_name(step), "code": code})


def _gate(document: object) -> Mapping[str, object]:
    value = document.get("gate") if isinstance(document, Mapping) else None
    return value if isinstance(value, Mapping) else {}
