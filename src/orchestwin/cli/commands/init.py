from __future__ import annotations

import argparse
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import brief, usage
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.client import ensure_access
from orchestwin.cli.console import Choice, ProgressOutcome, selected_choice
from orchestwin.cli.errors import (
    BUDGET_CODES,
    INTERRUPTED_STATUS,
    USAGE_STATUS,
    ApiFailure,
    CliError,
)
from orchestwin.cli.flows import answers as answers_file
from orchestwin.cli.flows import init_brief, init_requirements, init_team, init_twins
from orchestwin.cli.flows.publish import publish_approved
from orchestwin.cli.project import LINK_FILE, STEPS_FOLDER, ProjectFolder, ProjectLink

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.answers import Answers

NAME = "init"
DESIGN_ONLY: Final = "DESIGN_ONLY"
DESIGN_AND_CODE: Final = "DESIGN_AND_CODE"
MODE_OPTIONS: Final = {"design": DESIGN_ONLY, "design-code": DESIGN_AND_CODE}
MODE_KEYS: Final = {
    DESIGN_ONLY: "init.mode_design_only",
    DESIGN_AND_CODE: "init.mode_design_and_code",
}
STAGES: Final = ("brief", "team", "twins", "requirements")
FLOWS: Final = (init_brief, init_team, init_twins, init_requirements)
STAGE_INDEX: Final = {"BRIEF": 0, "TEAM": 1, "USER_TWINS": 2, "REQUIREMENTS": 3}
STAGE_OPERATIONS: Final = (
    ("BRIEF_DIALOGUE",),
    ("TEAM_PROPOSAL",),
    ("PERSONA_PROPOSAL", "USER_TWIN_GENERATION"),
    ("REQUIREMENTS_PROPOSAL",),
)
CHANGE_OPERATION: Final = "REQUIREMENTS_CHANGE"
BUSY_CODE: Final = "TOO_MANY_GENERATIONS"
BUSY_ATTEMPTS: Final = 8
BUSY_SECONDS: Final = 15.0
MAX_RESTARTS: Final = 3
ATTEMPTS: Final = 5
MICRO_USD: Final = 1_000_000
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


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", metavar="NAME", help="init.option_name")
    parser.add_argument("--idea", metavar="TEXT", help="init.option_idea")
    parser.add_argument("--mode", choices=tuple(MODE_OPTIONS), help="init.option_mode")
    parser.add_argument("--project", metavar="ID", help="init.option_project")
    parser.add_argument("--answers", metavar="FILE", help="init.option_answers")
    parser.add_argument("--until", choices=STAGES, help="init.option_until")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    script = _script(context, arguments.answers)
    name = _name_option(arguments.name)
    idea = _idea_option(arguments.idea)
    project_id = _project_option(arguments.project)
    mode = MODE_OPTIONS[arguments.mode] if arguments.mode else None
    until = arguments.until
    folder = context.project(required=False)
    if folder is None and project_id is None and script is not None:
        if name is None and script.name is None:
            raise script.missing("name")
        if idea is None and script.idea is None:
            raise script.missing("idea")
    client = context.client()
    require_sign_in(context, client)
    if folder is not None:
        journey = resume(context, client, folder, project_id, mode, script, until, idea)
    elif project_id is not None:
        journey = attach(context, client, project_id, mode, script, until, idea)
    else:
        journey = create(context, client, name, idea, mode, script, until)
    return journey.run()


def require_sign_in(context: CommandContext, client: StudioClient) -> None:
    ensure_access(context, client)


def create(
    context: CommandContext,
    client: StudioClient,
    name: str | None,
    idea: str | None,
    mode: str | None,
    script: Answers | None,
    until: str | None,
) -> Journey:
    console = context.console
    client.get("/auth/me")
    console.say("init.welcome")
    console.say("init.path")
    chosen = _mode(context, mode, script)
    statement = idea or (script.idea if script is not None else None) or ask_idea(context)
    title = name or (script.name if script is not None else None) or ask_name(context)
    spend(context, client, operations(0, until, script), script)
    created = project_api.create_project(client, title)
    shown = created.get("display_name")
    link = ProjectLink(
        studio=client.studio.origin,
        api_prefix=client.studio.api_prefix,
        project_id=str(created["id"]),
        project_name=shown if isinstance(shown, str) and shown else title,
        mode=chosen,
        language=context.language,
        created_at=moment(context),
    )
    folder = ProjectFolder.create(context.directory, link)
    console.say("init.created", name=link.project_name, path=str(folder.local / LINK_FILE))
    return Journey(context, client, folder, script=script, until=until, idea=statement)


def attach(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    mode: str | None,
    script: Answers | None,
    until: str | None,
    idea: str | None,
) -> Journey:
    found = project_api.get_project(client, project_id)
    shown = found.get("display_name")
    title = shown if isinstance(shown, str) and shown else project_id
    context.console.say("init.attaching", name=title)
    chosen = _mode(context, mode, script)
    link = ProjectLink(
        studio=client.studio.origin,
        api_prefix=client.studio.api_prefix,
        project_id=str(found.get("id") or project_id),
        project_name=title,
        mode=chosen,
        language=None,
        created_at=moment(context),
    )
    folder = ProjectFolder.create(context.directory, link)
    context.console.say("init.linked", name=title, path=str(folder.local / LINK_FILE))
    position(context, client, found, until, script)
    return Journey(context, client, folder, script=script, until=until, idea=idea)


def resume(
    context: CommandContext,
    client: StudioClient,
    folder: ProjectFolder,
    project_id: str | None,
    mode: str | None,
    script: Answers | None,
    until: str | None,
    idea: str | None,
) -> Journey:
    link = folder.link()
    if project_id is not None and project_id != link.project_id:
        raise CliError("PROJECT_ALREADY_LINKED", values={"root": str(folder.root)})
    found = project_api.get_project(client, link.project_id)
    wanted = mode or (script.mode if script is not None else None)
    if wanted is not None and wanted != link.mode:
        folder.update_link(mode=wanted)
        context.console.say("init.mode_updated", mode=context.text(MODE_KEYS[wanted]))
        if wanted == DESIGN_AND_CODE:
            context.console.say("init.mode_code_note")
    position(context, client, found, until, script)
    return Journey(context, client, folder, script=script, until=until, idea=idea)


def position(
    context: CommandContext,
    client: StudioClient,
    found: Mapping[str, object],
    until: str | None,
    script: Answers | None,
) -> None:
    shown = found.get("display_name")
    name = shown if isinstance(shown, str) else ""
    index = STAGE_INDEX.get(str(found.get("current_stage")))
    if index is None:
        context.console.say("init.resume_done", name=name)
        return
    context.console.say(
        "init.resume",
        name=name,
        number=index + 1,
        total=len(STAGES),
        step=context.text(f"common.stage_{STAGES[index]}"),
    )
    needed = operations(index, until, script)
    if needed:
        spend(context, client, needed, script)


def spend(
    context: CommandContext,
    client: StudioClient,
    needed: Sequence[str],
    script: Answers | None,
) -> None:
    try:
        costs.confirm_spending(context, client, needed, ask=script is None)
    except CliError as error:
        if error.code == "SPENDING_REFUSED" and script is not None:
            raise CliError("SPENDING_REFUSED", values={"reason": "answers"}) from None
        raise


def operations(start: int, until: str | None, script: Answers | None) -> list[str]:
    last = STAGES.index(until) if until else len(STAGES) - 1
    found: list[str] = []
    for index in range(start, last + 1):
        found.extend(STAGE_OPERATIONS[index])
    if script is not None and start <= len(STAGES) - 1 <= last:
        found.extend([CHANGE_OPERATION] * len(script.changes))
    return found


def moment(context: CommandContext) -> str:
    return context.environment.now().isoformat(timespec="seconds")


def ask_mode(context: CommandContext) -> str:
    console = context.console
    options = [
        Choice("design", context.text("init.mode_design_only")),
        Choice("design-code", context.text("init.mode_design_and_code")),
    ]
    console.say("init.mode_question")
    for number, option in enumerate(options, start=1):
        console.write(f"  {number}. {option.label}")
    for _ in range(ATTEMPTS):
        selected = selected_choice(console.ask("common.choose_prompt", default="1"), options)
        if selected is not None:
            return MODE_OPTIONS[selected.key]
        console.say("common.choice_invalid")
    raise CliError("ANSWER_NOT_VALID")


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


def ask_name(context: CommandContext) -> str:
    console = context.console
    folder = " ".join(context.directory.name.split())
    default = folder if 0 < len(folder) <= brief.MAX_NAME else None
    for _ in range(ATTEMPTS):
        name = " ".join(console.ask("init.name", default=default).split())
        if 0 < len(name) <= brief.MAX_NAME:
            return name
        console.say("init.name_too_long", limit=brief.MAX_NAME)
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


def version_number(version: Mapping[str, object] | None) -> int | None:
    value = None if version is None else version.get("version_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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
            if status == 402 or code in BUDGET_CODES:
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
        if code == "GENERATION_BUDGET_UNAVAILABLE":
            return CliError("GENERATION_BUDGET_UNAVAILABLE")
        reason, ceiling = self.ceiling(operation)
        if reason is None:
            return CliError("GENERATION_BUDGET_EXCEEDED")
        return CliError(
            "GENERATION_BUDGET_EXCEEDED",
            values={
                "reason": reason,
                "ceiling": costs.usd_text(ceiling, self.context.language),
            },
        )

    def ceiling(self, operation: str) -> tuple[str | None, float]:
        try:
            budget = usage.budget(self.client)
        except CliError:
            return None, 0.0
        if budget is None:
            return None, 0.0
        need = round(costs.ESTIMATES[operation].high_usd * MICRO_USD)
        total = budget.get("total_microusd")
        remaining = budget.get("remaining_total_microusd")
        if _amount(total) and _amount(remaining) and remaining < need:
            return "total", total / MICRO_USD
        try:
            spent = usage.project_usage(self.client, self.project_id)
        except CliError:
            spent = None
        limit = budget.get("per_project_microusd")
        totals = spent.get("totals") if spent is not None else None
        used = totals.get("cost_microusd") if isinstance(totals, Mapping) else None
        if _amount(limit) and _amount(used) and limit - used < need:
            return "project", limit / MICRO_USD
        single = budget.get("per_generation_microusd")
        if _amount(single):
            return "generation", single / MICRO_USD
        return None, 0.0

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


def _amount(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _mode(context: CommandContext, mode: str | None, script: Answers | None) -> str:
    if mode is not None:
        chosen = mode
    elif script is not None:
        chosen = script.mode or DESIGN_ONLY
    else:
        chosen = ask_mode(context)
    if chosen == DESIGN_AND_CODE:
        context.console.say("init.mode_code_note")
    return chosen


def _script(context: CommandContext, value: str | None) -> Answers | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = context.environment.working_directory / path
    return answers_file.load(path)


def _name_option(value: str | None) -> str | None:
    if value is None:
        return None
    name = " ".join(value.split())
    if not 0 < len(name) <= brief.MAX_NAME:
        raise CliError("NAME_INVALID", status=USAGE_STATUS, values={"limit": brief.MAX_NAME})
    return name


def _idea_option(value: str | None) -> str | None:
    if value is None:
        return None
    idea = value.strip()
    if not 0 < len(idea) <= brief.MAX_STATEMENT:
        raise CliError("IDEA_INVALID", status=USAGE_STATUS, values={"limit": brief.MAX_STATEMENT})
    return idea


def _project_option(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        raise CliError("PROJECT_ID_INVALID", status=USAGE_STATUS, values={"value": value}) from None
