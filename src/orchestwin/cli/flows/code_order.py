from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.project import read_json

if TYPE_CHECKING:
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

APPROVED: Final = "APPROVED"
DESIGN_STAGE: Final = "design"
STATE_DOCUMENT: Final = "state/state.json"
STATE_TEXT: Final = "state/state.md"
TASK_STATUSES: Final = ("OPEN", "DONE", "DROPPED")
TASK_ORIGINS: Final = ("CODE_CHANGE", "TEST_RUN", "OWNER")
OPEN: Final = TASK_STATUSES[0]
CODE_CHANGE: Final = TASK_ORIGINS[0]
TEST_RUN: Final = TASK_ORIGINS[1]
OWNER: Final = TASK_ORIGINS[2]
INDEX_TEXT: Final = "ORCHESTWIN.md"
REQUIREMENTS_TEXT: Final = "requirements/requirements.md"
DESIGN_TEXT: Final = "design/design.md"
MOCKUP_FILE: Final = "design/mockup.html"
DESIGN_DOCUMENT: Final = "design/design.json"
TWINS_TEXT: Final = "twins/twins.md"
FEEDBACK_TEXT: Final = "twins/feedback/feedback.md"
READ_FIRST: Final = (
    INDEX_TEXT,
    REQUIREMENTS_TEXT,
    DESIGN_TEXT,
    MOCKUP_FILE,
    TWINS_TEXT,
    FEEDBACK_TEXT,
    STATE_TEXT,
)
SHORT_LENGTH: Final = 7
ITALIAN: Final = "Italian"
ENGLISH: Final = "English"
TITLE: Final = "# Work order from OrchesTwin Studio"
INTRODUCTION: Final = (
    'You are working in the repository of the project "{name}". Its design was approved in '
    "OrchesTwin Studio and the application is developed here, outside the Studio. The folder "
    "`{folder}/` of this repository is the knowledge folder of the project, version {version}: "
    "it is the source of truth for what to build and for whom."
)
READ_FIRST_HEADING: Final = "## Read first"
INDEX_ITEM: Final = "{path}: the index of the folder and the state of the development."
REQUIREMENTS_ITEM: Final = (
    "{path}: the approved requirements (REQ codes) and acceptance criteria (AC codes)."
)
DESIGN_ITEM: Final = (
    "{design} and {mockup}: the approved design alternative{code} and its mockup; the screens "
    "have SCR codes."
)
DESIGN_ONLY_ITEM: Final = (
    "{design}: the approved design alternative{code}; the screens have SCR codes."
)
MOCKUP_ONLY_ITEM: Final = (
    "{mockup}: the mockup of the approved design alternative{code}; the screens have SCR codes."
)
TWINS_CLAUSE: Final = "{path}: the user twins, synthetic representatives of the user groups"
FEEDBACK_CLAUSE: Final = (
    "{path}: what they said about the design, the commits and the tests, and what they learned "
    "during the development"
)
FEEDBACK_ALONE_CLAUSE: Final = (
    "{path}: what the user twins said about the design, the commits and the tests, and what they "
    "learned during the development"
)
STATE_ITEM: Final = (
    "{path}: the commits already examined, the open tasks and the latest results of the "
    "acceptance tests."
)
WORK_HEADING: Final = "## What to do now"
TASKS_INTRODUCTION: Final = (
    "Carry out these tasks for the code. The owner of the project decided each of them."
)
TASK_LINE: Final = "- {code}: {text}"
FROM_LINE: Final = "  From: {origin}"
ABOUT_LINE: Final = "  About: {codes}"
TEST_FINDING: Final = "a finding of {twin} on the acceptance tests{finding}"
COMMIT_FINDING: Final = "a finding of {twin} on {commit}{finding}"
VERDICT: Final = "the decision on {commit}"
WRITTEN_BY_OWNER: Final = "written by the owner"
NAMED_TWIN: Final = 'the twin "{name}"'
SOME_TWIN: Final = "a twin"
NAMED_COMMIT: Final = "the commit {commit}"
SOME_COMMIT: Final = "a commit"
QUOTED_FINDING: Final = ': "{text}"'
REQUEST_INTRODUCTION: Final = "The owner asks:"
BUILD: Final = (
    "Build the application as the approved requirements and design describe. If the repository "
    "already holds the application, bring it in line with them."
)
RULES: Final = (
    "## Rules",
    "- The application is for the people described by the twins: every text that a person reads "
    "in the application is written in {language}.",
    "- Follow the approved design (screens, flows, labels) and the requirements. Where you have "
    "to depart from them, do it and say so at the end with the reason: the owner realigns the "
    "design with `ut verify`.",
    "- Never edit `{folder}/` and `.orchestwin/`: OrchesTwin Studio writes them.",
    "- Do not commit and do not push: the owner reviews your changes and commits them.",
    "- The MCP server `orchestwin-twins` answers from the knowledge folder: the twins, the "
    "requirements, the design, the feedback, the tasks and the test results. {paid_tools}",
    "- Start no paid service and add no dependency that the work does not need.",
)
FREE_TOOLS: Final = "Its paid tools are switched off: do not call them."
PAID_TOOLS: Final = (
    "Its paid tools (asking a twin, reviewing the changes, running the acceptance tests) spend "
    "on the owner's Studio: use them only when the work needs them."
)
FINISH: Final = (
    "## When you finish",
    "Say in a few lines: what you changed, file by file; which tasks you consider done, by their "
    "TSK code; how to start the application, so that the owner can verify the acceptance "
    "criteria with `ut test --url <address>` or `ut test --static <folder>`; what you left out "
    "and why.",
)


@dataclass(frozen=True, slots=True)
class Task:
    code: str
    text: str
    origin: Mapping[str, object] | None = None
    from_commit: str | None = None
    requirements: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()

    @property
    def subjects(self) -> tuple[str, ...]:
        return (*self.requirements, *self.screens, *self.criteria)


@dataclass(frozen=True, slots=True)
class Work:
    tasks: tuple[Task, ...] = ()
    request: str | None = None
    every: bool = False

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(task.code for task in self.tasks)


@dataclass(frozen=True, slots=True)
class OrderFacts:
    project_name: str
    knowledge_folder: str
    version_number: int
    alternative: str | None
    language: str
    present: frozenset[str]


def approved_folder(project: ProjectFolder) -> FolderSummary:
    from orchestwin.cli.mcp.knowledge import FolderProblem, load
    from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_CODE_UNAVAILABLE

    try:
        folder = load(project.knowledge)
        if folder.approved_provided_prototype() is not None:
            raise CliError(PROVIDED_PROTOTYPE_CODE_UNAVAILABLE)
    except FolderProblem as error:
        if error.code != "FOLDER_MISSING":
            raise CliError(
                "FOLDER_NOT_VERIFIED",
                values={
                    "code": error.code,
                    "path": error.values.get("path", ""),
                    "folder": str(project.knowledge),
                },
            ) from error
    found = knowledge.summary(project.knowledge)
    if found is None or not design_approved(found):
        raise CliError("CODE_DESIGN_REQUIRED", status=1)
    return found


def design_approved(found: FolderSummary) -> bool:
    entry = found.stage(DESIGN_STAGE)
    return (
        DESIGN_STAGE in found.progress
        and entry is not None
        and entry.version_number is not None
        and entry.gate_status == APPROVED
    )


def open_tasks(project: ProjectFolder) -> tuple[Task, ...]:
    return tasks_of(read_json(project.knowledge.joinpath(*STATE_DOCUMENT.split("/"))))


def tasks_of(document: object) -> tuple[Task, ...]:
    items = document.get("tasks") if isinstance(document, Mapping) else None
    found: list[Task] = []
    for item in items if isinstance(items, list) else ():
        task = task_from(item)
        if task is not None:
            found.append(task)
    return tuple(found)


def task_from(item: object) -> Task | None:
    if not isinstance(item, Mapping) or item.get("status") != OPEN:
        return None
    code = _text(item.get("code"))
    text = _text(item.get("text"))
    if code is None or text is None:
        return None
    about = _mapping(item.get("about"))
    origin = item.get("origin")
    return Task(
        code=code,
        text=text,
        origin=origin if isinstance(origin, Mapping) else None,
        from_commit=_text(item.get("from_commit")),
        requirements=_codes(about.get("requirements")),
        screens=_codes(about.get("screens")),
        criteria=_codes(about.get("criteria")),
    )


def chosen_tasks(tasks: Sequence[Task], codes: Sequence[str]) -> tuple[Task, ...]:
    wanted = [code.strip().upper() for code in codes if code.strip()]
    known = {task.code.upper() for task in tasks}
    unknown = [code for code in dict.fromkeys(wanted) if code not in known]
    if unknown:
        raise CliError(
            "CODE_TASK_UNKNOWN", status=USAGE_STATUS, values={"codes": ", ".join(unknown)}
        )
    return tuple(task for task in tasks if task.code.upper() in wanted)


def work_for(tasks: Sequence[Task], codes: Sequence[str], request: str | None) -> Work:
    asked = request.strip() if request is not None and request.strip() else None
    if any(code.strip() for code in codes):
        return Work(tasks=chosen_tasks(tasks, codes), request=asked)
    if asked is not None:
        return Work(request=asked)
    return Work(tasks=tuple(tasks), every=bool(tasks))


def facts_of(project: ProjectFolder, summary: FolderSummary, *, language: str) -> OrderFacts:
    link = project.link()
    root = project.knowledge
    return OrderFacts(
        project_name=_inline(summary.project_name) or _inline(link.project_name),
        knowledge_folder=link.knowledge_folder,
        version_number=summary.version_number,
        alternative=alternative_code(project),
        language=language_name(project_language(project, language, summary=summary)),
        present=frozenset(name for name in READ_FIRST if root.joinpath(*name.split("/")).is_file()),
    )


def project_language(
    project: ProjectFolder, fallback: str, *, summary: FolderSummary | None = None
) -> str:
    found = folder_language(project) if summary is None else _text(summary.language)
    return found or _text(project.link().language) or fallback


def folder_language(project: ProjectFolder) -> str | None:
    try:
        found = knowledge.summary(project.knowledge)
    except CliError:
        return None
    return None if found is None else _text(found.language)


def alternative_code(project: ProjectFolder) -> str | None:
    state = read_json(project.knowledge.joinpath(*STATE_DOCUMENT.split("/")))
    reference = _mapping(_mapping(state).get("reference"))
    code = _text(_mapping(reference.get("design")).get("alternative_code"))
    if code is not None:
        return code
    design = read_json(project.knowledge.joinpath(*DESIGN_DOCUMENT.split("/")))
    package = _mapping(_mapping(design).get("package"))
    selected = package.get("owner_selected_alternative_id")
    alternatives = package.get("alternatives")
    for item in alternatives if isinstance(alternatives, list) else ():
        entry = _mapping(item)
        if selected is not None and str(entry.get("id")) == str(selected):
            return _text(entry.get("code"))
    return None


def language_name(value: str) -> str:
    return ITALIAN if value.strip().lower().startswith("it") else ENGLISH


def work_order(facts: OrderFacts, work: Work, *, spend: bool) -> str:
    folder = facts.knowledge_folder
    lines = [
        TITLE,
        "",
        INTRODUCTION.format(name=facts.project_name, folder=folder, version=facts.version_number),
        "",
    ]
    items = read_first(facts)
    if items:
        lines.extend([READ_FIRST_HEADING, *items, ""])
    lines.extend([WORK_HEADING, work_text(work), ""])
    paid_tools = PAID_TOOLS if spend else FREE_TOOLS
    lines.extend(
        rule.format(language=facts.language, folder=folder, paid_tools=paid_tools) for rule in RULES
    )
    lines.extend(["", *FINISH])
    return "\n".join(lines) + "\n"


def read_first(facts: OrderFacts) -> list[str]:
    def path(name: str) -> str:
        return f"`{facts.knowledge_folder}/{name}`"

    def has(name: str) -> bool:
        return name in facts.present

    code = f" {facts.alternative}" if facts.alternative else ""
    items: list[str] = []
    if has(INDEX_TEXT):
        items.append(INDEX_ITEM.format(path=path(INDEX_TEXT)))
    if has(REQUIREMENTS_TEXT):
        items.append(REQUIREMENTS_ITEM.format(path=path(REQUIREMENTS_TEXT)))
    design, mockup = path(DESIGN_TEXT), path(MOCKUP_FILE)
    if has(DESIGN_TEXT) and has(MOCKUP_FILE):
        items.append(DESIGN_ITEM.format(design=design, mockup=mockup, code=code))
    elif has(DESIGN_TEXT):
        items.append(DESIGN_ONLY_ITEM.format(design=design, code=code))
    elif has(MOCKUP_FILE):
        items.append(MOCKUP_ONLY_ITEM.format(mockup=mockup, code=code))
    clauses: list[str] = []
    if has(TWINS_TEXT):
        clauses.append(TWINS_CLAUSE.format(path=path(TWINS_TEXT)))
    if has(FEEDBACK_TEXT):
        clause = FEEDBACK_CLAUSE if clauses else FEEDBACK_ALONE_CLAUSE
        clauses.append(clause.format(path=path(FEEDBACK_TEXT)))
    if clauses:
        items.append(f"{'; '.join(clauses)}.")
    if has(STATE_TEXT):
        items.append(STATE_ITEM.format(path=path(STATE_TEXT)))
    return [f"{number}. {item}" for number, item in enumerate(items, start=1)]


def work_text(work: Work) -> str:
    parts: list[str] = []
    if work.tasks:
        lines = [TASKS_INTRODUCTION]
        for task in work.tasks:
            lines.append(TASK_LINE.format(code=task.code, text=_inline(task.text)))
            lines.append(FROM_LINE.format(origin=origin_text(task)))
            if task.subjects:
                lines.append(ABOUT_LINE.format(codes=", ".join(task.subjects)))
        parts.append("\n".join(lines))
    if work.request is not None:
        quoted = [f"> {line}".rstrip() for line in work.request.splitlines()]
        parts.append("\n".join([REQUEST_INTRODUCTION, *quoted]))
    if not parts:
        parts.append(BUILD)
    return "\n\n".join(parts)


def origin_text(task: Task) -> str:
    origin = task.origin
    kind = None if origin is None else origin.get("kind")
    if origin is None or kind not in TASK_ORIGINS:
        return VERDICT.format(commit=commit_words(task.from_commit))
    if kind == OWNER:
        return WRITTEN_BY_OWNER
    name = _text(origin.get("twin_name"))
    finding = _text(origin.get("finding"))
    twin = SOME_TWIN if name is None else NAMED_TWIN.format(name=_inline(name))
    quoted = "" if finding is None else QUOTED_FINDING.format(text=_inline(finding))
    if kind == TEST_RUN:
        return TEST_FINDING.format(twin=twin, finding=quoted)
    commit = commit_words(_text(origin.get("commit")) or task.from_commit)
    if name is None and finding is None:
        return VERDICT.format(commit=commit)
    return COMMIT_FINDING.format(twin=twin, commit=commit, finding=quoted)


def commit_words(commit: str | None) -> str:
    if commit is None:
        return SOME_COMMIT
    return NAMED_COMMIT.format(commit=commit[:SHORT_LENGTH])


def _codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(code for item in value if (code := _text(item)) is not None)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _inline(value: object) -> str:
    return " ".join(str(value).split())
