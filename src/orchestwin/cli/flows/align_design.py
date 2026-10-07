from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import design as design_api
from orchestwin.cli.console import format_elapsed
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import (
    code_agents,
    code_order,
    code_run,
    design_delta,
    design_state,
    verify_review,
)
from orchestwin.cli.flows.code_agents import CLAUDE
from orchestwin.cli.flows.design_delta import ADD, CHANGE, REMOVE
from orchestwin.cli.flows.design_state import wrapped
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.code_run import Finished, Launch
    from orchestwin.cli.flows.design_delta import DeltaLine, DesignDelta
    from orchestwin.cli.flows.design_state import DesignState
    from orchestwin.cli.flows.verify_review import Workspace
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

DEFAULT_PYTHON: Final = "python"
REFUSED_REASON: Final = "AGENT"
DESIGN_FILES: Final = frozenset({code_order.DESIGN_TEXT, code_order.MOCKUP_FILE})
READ_FIRST: Final = (
    code_order.DESIGN_TEXT,
    code_order.MOCKUP_FILE,
    code_order.REQUIREMENTS_TEXT,
    code_order.STATE_TEXT,
)
SIGNS: Final[Mapping[str, str]] = MappingProxyType({ADD: "+", REMOVE: "-", CHANGE: "~"})
LINE_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        design_delta.SELECTION: "align.design_line_selection",
        design_delta.ALTERNATIVE: "align.design_line_alternative",
        design_delta.WORKFLOW: "align.design_line_workflow",
        design_delta.VISUAL: "align.design_line_visual",
        design_delta.SCREEN: "align.design_line_screen",
        design_delta.ELEMENT: "align.design_line_element",
        design_delta.TRANSITION: "align.design_line_transition",
        design_delta.MOCKUP: "align.design_line_mockup",
        design_delta.STYLES: "align.design_line_styles",
    }
)
FEMININE: Final = frozenset({design_delta.SCREEN})
FEMININE_WORDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        ADD: "align.design_what_added",
        REMOVE: "align.design_what_removed",
        CHANGE: "align.design_what_changed",
    }
)
MASCULINE_WORDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        ADD: "align.design_what_added_masculine",
        REMOVE: "align.design_what_removed_masculine",
        CHANGE: "align.design_what_changed_masculine",
    }
)
REDRAWN: Final = "align.design_what_redrawn"
FIELD_KEY: Final = "align.design_field_{name}"
TITLE: Final = "# Work order from OrchesTwin Studio: the design changed"
INTRODUCTION: Final = (
    'You are working in the repository of the project "{name}". The application was built '
    "from version {start} of its approved design{alternative}; the owner has since approved "
    "design version {end}."
)
ALTERNATIVE_CLAUSE: Final = " (alternative {code})"
FOLDER_SENTENCE: Final = (
    "The folder `{folder}/` of this repository is the knowledge folder of the project, "
    "version {version}{described}"
)
DESCRIBED_BOTH: Final = ": {design} and {mockup} describe design version {end}."
DESCRIBED_ONE: Final = ": {path} describes design version {end}."
CHANGES_HEADING: Final = "## What changed from design version {start} to version {end}"
CHANGE_LINE: Final = "- {text}"
OTHER_LINE: Final = (
    "- {count} other changes concern the twins' critiques and the design concerns: they need "
    "no work in the code."
)
OTHER_LINE_ONE: Final = (
    "- 1 other change concerns the twins' critiques and the design concerns: it needs no work "
    "in the code."
)
DESIGN_ITEM: Final = (
    "{design} and {mockup}: the approved design alternative{code} at version {end}; the "
    "screens have SCR codes."
)
DESIGN_ONLY_ITEM: Final = (
    "{design}: the approved design alternative{code} at version {end}; the screens have SCR codes."
)
MOCKUP_ONLY_ITEM: Final = (
    "{mockup}: the mockup of the approved design alternative{code} at version {end}; the "
    "screens have SCR codes."
)
WORK: Final = (
    "Bring the application in line with design version {end}: change only what the "
    "differences above require and keep everything else as it is."
)
HAND_SENTENCE: Final = (
    "The repository has {count} commits after the point the Studio last examined: read the "
    "code as it is now."
)
HAND_SENTENCE_ONE: Final = (
    "The repository has 1 commit after the point the Studio last examined: read the code as "
    "it is now."
)
FINISH: Final = (
    "## When you finish",
    "Say in a few lines: what you changed, file by file; which of the differences above you "
    "covered; how to start the application, so that the owner can verify the acceptance "
    "criteria with `ut test --url <address>` or `ut test --static <folder>`; what you left out "
    "and why.",
)


@dataclass(frozen=True, slots=True)
class DesignOrder:
    project_name: str
    knowledge_folder: str
    folder_version: int | None
    start: int
    end: int
    start_code: str | None
    code: str | None
    language: str
    present: frozenset[str]
    lines: tuple[str, ...]
    other: int
    hand: int


def run(context: CommandContext, *, since: str | None, dry_run: bool, max_usd: str | None) -> int:
    wanted = since_version(since)
    workspace = verify_review.prepare(context)
    project = workspace.project
    console = context.console
    console.heading(context.text("align.design_heading", name=project.link().project_name))
    settings = code_run.read_settings(project) or code_run.CodeSettings()
    budget = code_agents.budget(max_usd, agent=settings.agent, headless=settings.headless)
    state = design_state.read_state(workspace.client, project)
    current = state.version_number
    if current is None:
        raise CliError("ALIGN_DESIGN_REQUIRED")
    if not state.approved:
        raise CliError("ALIGN_DESIGN_NOT_APPROVED", status=1, values={"version": current})
    chosen = state.chosen
    code = chosen.code if chosen is not None else code_order.alternative_code(project)
    aligned = starting_point(context, workspace, wanted)
    console.say("align.design_current", version=current, code=code or "-")
    if aligned >= current:
        console.say("align.design_nothing", version=current)
        return 0
    if verify_review.uncommitted(context, workspace):
        raise CliError("ALIGN_DESIGN_UNCOMMITTED", status=1)
    base, target = versions(workspace, state, aligned, current)
    delta = design_delta.compare(package_of(base), package_of(target))
    show_delta(context, delta, aligned, current)
    if delta.empty:
        console.say("align.design_no_code_changes", **{"from": aligned, "to": current})
        code_run.write_design_point(
            project,
            version=current,
            folder=None,
            reason=code_run.NO_CODE_CHANGES_REASON,
            moment=context.environment.now(),
        )
        return 0
    hand = hand_commits(context, workspace)
    if hand > 0:
        key = "align.design_hand_commits_one" if hand == 1 else "align.design_hand_commits"
        console.say(key, count=hand)
    summary = refreshed_folder(context, workspace, current)
    order = order_of(
        context, project, summary, delta, start=aligned, end=current, code=code, hand=hand
    )
    program = code_run.claude_program(context) if settings.agent == CLAUDE else None
    files = code_run.write_run_files(
        project,
        context.environment.now(),
        work_order(order),
        spend=False,
        python=sys.executable or DEFAULT_PYTHON,
    )
    launch = code_run.Launch(
        project=project,
        files=files,
        arguments=code_run.agent_arguments(
            project, settings, files, program=program, max_usd=budget
        ),
        settings=settings,
        work=code_order.Work(),
        spend=False,
        kind=code_run.DESIGN_KIND,
        design_from=aligned,
        design_version_number=current,
    )
    announce(context, launch, max_usd=budget)
    if dry_run:
        from orchestwin.cli.commands.code import show_words

        show_words(context, launch)
        return 0
    if not context.assume_yes and not console.confirm("align.design_confirm", default=True):
        raise CliError("SPENDING_REFUSED", values={"reason": REFUSED_REASON})
    console.say("code.starting", program=launch.program)
    return report(context, launch, code_run.start(context, launch), current=current)


def since_version(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not (text.isascii() and text.isdigit()) or int(text) < 1:
        raise CliError("ALIGN_DESIGN_SINCE_INVALID", status=USAGE_STATUS, values={"value": value})
    return int(text)


def starting_point(context: CommandContext, workspace: Workspace, wanted: int | None) -> int:
    console = context.console
    if wanted is not None:
        console.say("align.design_point_since", version=wanted)
        return wanted
    project = workspace.project
    recorded = code_run.design_point_version(project)
    found = code_run.aligned_design_version(project, verified_version(workspace.alignment))
    if found is None:
        raise CliError("ALIGN_DESIGN_NO_POINT", status=USAGE_STATUS)
    key = "align.design_point_run" if recorded == found else "align.design_point_verify"
    console.say(key, version=found)
    return found


def verified_version(document: Mapping[str, object]) -> int | None:
    point = changes_api.aligned(document)
    return None if point is None else whole(point.get("design_version_number"))


def versions(
    workspace: Workspace, state: DesignState, aligned: int, current: int
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    found: dict[int, Mapping[str, object]] = {}
    for item in design_api.history(workspace.client, workspace.project_id):
        number = whole(item.get("version_number"))
        if number is not None:
            found.setdefault(number, item)
    base = found.get(aligned)
    if base is None:
        raise CliError(
            "ALIGN_DESIGN_VERSION_UNKNOWN", status=USAGE_STATUS, values={"version": aligned}
        )
    return base, found.get(current) or state.version or {}


def package_of(version: Mapping[str, object]) -> Mapping[str, object]:
    package = version.get("package")
    return package if isinstance(package, Mapping) else {}


def show_delta(context: CommandContext, delta: DesignDelta, start: int, end: int) -> None:
    console = context.console
    count = len(delta.lines)
    key = "align.design_changes_heading_one" if count == 1 else "align.design_changes_heading"
    console.write()
    console.heading(context.text(key, **{"from": start, "to": end, "count": count}))
    for line in delta.lines:
        wrapped(context, line_text(context, line), hang="  ")
    if delta.other == 1:
        console.say("align.design_other_changes_one", count=delta.other)
    elif delta.other > 1:
        console.say("align.design_other_changes", count=delta.other)


def line_text(context: CommandContext, line: DeltaLine) -> str:
    sign = SIGNS.get(line.kind, SIGNS[CHANGE])
    key = LINE_KEYS.get(line.subject)
    if key is None:
        return f"{sign} {design_delta.english(line)}"
    return context.text(
        key,
        sign=sign,
        code=line.code or "-",
        title=line.title or "-",
        screen=line.screen or "-",
        what=what_text(context, line),
        fields=fields_text(context, line.fields),
        **{"from": line.before or "-", "to": line.after or line.code or "-"},
    )


def what_text(context: CommandContext, line: DeltaLine) -> str:
    if line.subject == design_delta.MOCKUP and line.kind == CHANGE:
        return context.text(REDRAWN)
    words = FEMININE_WORDS if line.subject in FEMININE else MASCULINE_WORDS
    return context.text(words.get(line.kind, words[CHANGE]))


def fields_text(context: CommandContext, fields: Sequence[str]) -> str:
    names = [field_name(context, name) for name in fields]
    return f": {', '.join(names)}" if names else ""


def field_name(context: CommandContext, name: str) -> str:
    key = FIELD_KEY.format(name=name)
    return context.text(key) if known(key) else name.replace("_", " ")


def hand_commits(context: CommandContext, workspace: Workspace) -> int:
    point = changes_api.aligned(workspace.alignment)
    commit = None if point is None else point.get("commit")
    if not isinstance(commit, str) or not commit:
        return 0
    if git.resolve(context, workspace.root, commit) is None:
        return 0
    commits = git.commits_after(context, workspace.root, commit)
    skipped = {item.hash for item in verify_review.folder_commits(workspace, commits)}
    return sum(1 for item in commits if item.hash not in skipped)


def refreshed_folder(
    context: CommandContext, workspace: Workspace, current: int
) -> FolderSummary | None:
    from orchestwin.cli.flows import verify_decision

    found = folder_summary(workspace.project)
    if design_version(found) != current:
        verify_decision.refresh_folder(context, workspace)
        found = folder_summary(workspace.project)
    return found


def folder_summary(project: ProjectFolder) -> FolderSummary | None:
    try:
        return knowledge.summary(project.knowledge)
    except CliError:
        return None


def design_version(summary: FolderSummary | None) -> int | None:
    stage = None if summary is None else summary.stage(code_order.DESIGN_STAGE)
    return None if stage is None else stage.version_number


def order_of(
    context: CommandContext,
    project: ProjectFolder,
    summary: FolderSummary | None,
    delta: DesignDelta,
    *,
    start: int,
    end: int,
    code: str | None,
    hand: int,
) -> DesignOrder:
    link = project.link()
    root = project.knowledge
    present = frozenset(name for name in READ_FIRST if root.joinpath(*name.split("/")).is_file())
    fresh = summary is not None and design_version(summary) == end
    name = "" if summary is None else inline(summary.project_name)
    return DesignOrder(
        project_name=name or inline(link.project_name),
        knowledge_folder=link.knowledge_folder,
        folder_version=summary.version_number if fresh and summary is not None else None,
        start=start,
        end=end,
        start_code=delta.from_code,
        code=code,
        language=code_order.language_name(
            code_order.project_language(project, context.language, summary=summary)
        ),
        present=present if fresh else present - DESIGN_FILES,
        lines=tuple(design_delta.english(line) for line in delta.lines),
        other=delta.other,
        hand=hand,
    )


def work_order(order: DesignOrder) -> str:
    alternative = order.start_code or order.code
    opening = INTRODUCTION.format(
        name=order.project_name,
        start=order.start,
        end=order.end,
        alternative=ALTERNATIVE_CLAUSE.format(code=alternative) if alternative else "",
    )
    sentence = folder_sentence(order)
    lines = [TITLE, "", f"{opening} {sentence}" if sentence else opening, ""]
    lines.append(CHANGES_HEADING.format(start=order.start, end=order.end))
    lines.extend(CHANGE_LINE.format(text=text) for text in order.lines)
    if order.other == 1:
        lines.append(OTHER_LINE_ONE)
    elif order.other > 1:
        lines.append(OTHER_LINE.format(count=order.other))
    lines.append("")
    items = read_first(order)
    if items:
        lines.extend([code_order.READ_FIRST_HEADING, *items, ""])
    lines.extend([code_order.WORK_HEADING, work_text(order), ""])
    lines.extend(
        rule.format(
            language=order.language,
            folder=order.knowledge_folder,
            paid_tools=code_order.FREE_TOOLS,
        )
        for rule in code_order.RULES
    )
    lines.extend(["", *FINISH])
    return "\n".join(lines) + "\n"


def folder_sentence(order: DesignOrder) -> str | None:
    if order.folder_version is None:
        return None
    design = code_order.DESIGN_TEXT in order.present
    mockup = code_order.MOCKUP_FILE in order.present
    if design and mockup:
        described = DESCRIBED_BOTH.format(
            design=quoted(order, code_order.DESIGN_TEXT),
            mockup=quoted(order, code_order.MOCKUP_FILE),
            end=order.end,
        )
    elif design or mockup:
        chosen = code_order.DESIGN_TEXT if design else code_order.MOCKUP_FILE
        described = DESCRIBED_ONE.format(path=quoted(order, chosen), end=order.end)
    else:
        described = "."
    return FOLDER_SENTENCE.format(
        folder=order.knowledge_folder, version=order.folder_version, described=described
    )


def read_first(order: DesignOrder) -> list[str]:
    def has(name: str) -> bool:
        return name in order.present

    code = f" {order.code}" if order.code else ""
    design = quoted(order, code_order.DESIGN_TEXT)
    mockup = quoted(order, code_order.MOCKUP_FILE)
    items: list[str] = []
    if has(code_order.DESIGN_TEXT) and has(code_order.MOCKUP_FILE):
        items.append(DESIGN_ITEM.format(design=design, mockup=mockup, code=code, end=order.end))
    elif has(code_order.DESIGN_TEXT):
        items.append(DESIGN_ONLY_ITEM.format(design=design, code=code, end=order.end))
    elif has(code_order.MOCKUP_FILE):
        items.append(MOCKUP_ONLY_ITEM.format(mockup=mockup, code=code, end=order.end))
    if has(code_order.REQUIREMENTS_TEXT):
        items.append(
            code_order.REQUIREMENTS_ITEM.format(path=quoted(order, code_order.REQUIREMENTS_TEXT))
        )
    if has(code_order.STATE_TEXT):
        items.append(code_order.STATE_ITEM.format(path=quoted(order, code_order.STATE_TEXT)))
    return [f"{number}. {item}" for number, item in enumerate(items, start=1)]


def work_text(order: DesignOrder) -> str:
    text = WORK.format(end=order.end)
    if order.hand == 1:
        return f"{text} {HAND_SENTENCE_ONE}"
    if order.hand > 1:
        return f"{text} {HAND_SENTENCE.format(count=order.hand)}"
    return text


def quoted(order: DesignOrder, name: str) -> str:
    return f"`{order.knowledge_folder}/{name}`"


def announce(context: CommandContext, launch: Launch, *, max_usd: float | None) -> None:
    from orchestwin.cli.commands.code import mode_key

    console = context.console
    settings = launch.settings
    agent_key = "code.agent_claude" if settings.agent == CLAUDE else "code.agent_custom"
    console.write()
    console.say(agent_key, program=launch.arguments[0])
    console.say(mode_key(settings))
    if settings.agent == CLAUDE and settings.model:
        console.say("code.model", model=settings.model)
    if max_usd is not None:
        console.say("code.budget", usd=costs.usd_text(max_usd, context.language))
    console.say("code.order", path=str(launch.files.prompt))
    console.say("code.own_account")


def report(context: CommandContext, launch: Launch, finished: Finished, *, current: int) -> int:
    from orchestwin.cli.commands.code import show_changes

    console = context.console
    outcome = finished.outcome
    elapsed = format_elapsed(outcome.seconds)
    console.write()
    if outcome.exit_status == 0:
        console.say("code.ended", elapsed=elapsed)
    else:
        console.say("code.ended_status", status=outcome.exit_status, elapsed=elapsed)
    show_changes(context, launch, finished.changes)
    if finished.touched:
        console.say("code.knowledge_touched", folder=launch.project.link().knowledge_folder)
    if outcome.exit_status != 0:
        console.say("align.design_next_steps_failed", folder=str(launch.files.folder))
        return 1
    code_run.write_design_point(
        launch.project,
        version=current,
        folder=launch.files.name,
        reason=code_run.DESIGN_RUN_REASON,
        moment=context.environment.now(),
    )
    console.say("align.design_next_steps", version=current)
    return 0


def whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def inline(value: object) -> str:
    return " ".join(str(value).split())
