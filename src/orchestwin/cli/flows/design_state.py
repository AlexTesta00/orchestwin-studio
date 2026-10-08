from __future__ import annotations

import re
import textwrap
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli import jobs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import packages
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.messages import known
from orchestwin.cli.views import directions

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

REQUIREMENTS_PENDING: Final = "REQUIREMENTS_PENDING"
NO_DESIGN: Final = "NO_DESIGN"
JOB_RUNNING: Final = "JOB_RUNNING"
NO_MOCKUPS: Final = "NO_MOCKUPS"
MOCKUPS_READY: Final = "MOCKUPS_READY"
CHOSEN: Final = "CHOSEN"
APPROVED: Final = "APPROVED"
KINDS: Final = (
    REQUIREMENTS_PENDING,
    NO_DESIGN,
    JOB_RUNNING,
    NO_MOCKUPS,
    MOCKUPS_READY,
    CHOSEN,
    APPROVED,
)
DESIGN_STAGES: Final = frozenset({"DESIGN", "PACKAGE"})
DESIGN_OPERATIONS: Final = frozenset(
    {"MOCKUP", "ITERATION", "DESIGN_PROPOSAL", "DESIGN_REGENERATION", "DESIGN_EVALUATION"}
)
VISUAL_DIMENSIONS: Final = ("archetype", "hue_family", "color_mode", "tone", "heading_family")
VISUAL_PLACEHOLDERS: Final = MappingProxyType(
    {
        "archetype": "layout",
        "hue_family": "hue",
        "color_mode": "mode",
        "tone": "tone",
        "heading_family": "font",
    }
)
POINT_FIELDS: Final = (
    "strengths",
    "concerns",
    "unmet_needs",
    "accessibility_observations",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
SENTENCE_ENDINGS: Final = (".", "!", "?", "…")
MINIMUM_WIDTH: Final = 20
PROPOSED: Final = "PROPOSED"
EMPTY: Final[Mapping[str, Mapping[str, object]]] = MappingProxyType({})
NEXT_COMMANDS: Final = (
    "design.after_code",
    "design.after_test",
    "design.after_tasks",
    "design.after_align",
    "design.after_twins",
    "design.after_watch",
)
CLOSE: Final = "CLOSE"
VERDICTS: Final = frozenset({"FAR", CLOSE, "UNKNOWN"})
NOT_FOLLOWED: Final = "NOT_FOLLOWED"
LEVELS: Final = (
    ("styles", "design.distance_styles"),
    ("structure", "design.distance_structure"),
)
JOINER: Final = " · "
SCREEN_ID: Final = re.compile(r"SCR-[0-9]{3}")
ELEMENT_MARK: Final = "data-elm"
LABEL_LIMIT: Final = 120
HTML_LIMIT: Final = 2048
PIN_CLASS: Final = "ot-pin"
NAME_ATTRIBUTES: Final = ("value", "placeholder", "title", "alt")
VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
SILENT_TAGS: Final = frozenset(
    {"script", "style", "template", "noscript", "select", "textarea", "svg"}
)
BLOCK_TAGS: Final = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "legend",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


@dataclass(frozen=True, slots=True)
class MockupElement:
    code: str
    kind: str
    text: str
    html: str

    @property
    def label(self) -> str:
        return self.text or self.code


@dataclass(frozen=True, slots=True)
class MockupScreen:
    code: str
    title: str
    html: str
    elements: tuple[MockupElement, ...] = ()

    @property
    def label(self) -> str:
        return clipped(self.title, LABEL_LIMIT) or self.code

    def element(self, code: str) -> MockupElement | None:
        return next((item for item in self.elements if item.code == code), None)


@dataclass(slots=True, eq=False)
class _Node:
    tag: str
    attributes: dict[str, str]
    parent: _Node | None
    start: int
    end: int = -1
    children: list[_Node | str] = field(default_factory=list)


class _MockupParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [
            0,
            *(index + 1 for index, character in enumerate(source) if character == "\n"),
        ]
        self.root = _Node("", {}, None, 0, len(source))
        self.stack: list[_Node] = [self.root]
        self.labels: list[_Node] = []
        self.ids: dict[str, _Node] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self.opened(tag, attrs)
        if tag in VOID_TAGS:
            node.end = node.start + len(self.get_starttag_text() or "")
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self.opened(tag, attrs)
        node.end = node.start + len(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag != tag:
                continue
            closing = self.source.find(">", self.position())
            end = len(self.source) if closing < 0 else closing + 1
            for node in self.stack[depth:]:
                node.end = end
            del self.stack[depth:]
            return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def opened(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        parent = self.stack[-1]
        attributes: dict[str, str] = {}
        for name, value in attrs:
            attributes.setdefault(name, value or "")
        node = _Node(tag, attributes, parent, self.position())
        parent.children.append(node)
        if tag == "label":
            self.labels.append(node)
        identifier = attributes.get("id")
        if identifier:
            self.ids.setdefault(identifier, node)
        return node

    def position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def finish(self) -> None:
        self.close()
        for node in self.stack[1:]:
            node.end = len(self.source)
        del self.stack[1:]


@dataclass(frozen=True, slots=True)
class Direction:
    name: str
    axes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Alternative:
    id: str
    code: str
    number: int
    title: str
    summary: str
    product_name: str | None
    choices: Mapping[str, str]
    recommended: bool
    direction: Direction | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    twin_id: str
    twin_name: str
    alternative_id: str
    verdict: str | None
    quote: str | None
    points: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class DesignState:
    project_id: str
    project_name: str
    stage: str
    version: Mapping[str, object] | None = None
    approved: bool = False
    capabilities: design_api.Capabilities = design_api.NO_CAPABILITIES
    running: tuple[Mapping[str, object], ...] = ()
    documents: Mapping[str, Mapping[str, object]] = field(default=EMPTY)
    review: Mapping[str, object] | None = None
    pending_change: Mapping[str, object] | None = None
    distance: Mapping[str, object] | None = None

    @property
    def kind(self) -> str:
        if self.stage not in DESIGN_STAGES:
            return REQUIREMENTS_PENDING
        if self.running:
            return JOB_RUNNING
        if self.version is None:
            return NO_DESIGN
        if self.approved:
            return APPROVED
        if self.chosen is not None:
            return CHOSEN
        if self.generated and not self.documents:
            return NO_MOCKUPS
        return MOCKUPS_READY

    @property
    def generated(self) -> bool:
        return self.capabilities.generated_mockups

    @property
    def package(self) -> Mapping[str, object]:
        package = None if self.version is None else self.version.get("package")
        return package if isinstance(package, Mapping) else {}

    @property
    def version_number(self) -> int | None:
        number = None if self.version is None else self.version.get("version_number")
        return number if isinstance(number, int) and not isinstance(number, bool) else None

    @property
    def alternatives(self) -> tuple[Alternative, ...]:
        recommended = self.package.get("recommended_alternative_id")
        found: list[Alternative] = []
        for item in _mappings(self.package.get("alternatives")):
            identifier = item.get("id")
            if not isinstance(identifier, str):
                continue
            visual = item.get("visual_language")
            visual = visual if isinstance(visual, Mapping) else {}
            choices = visual.get("choices")
            product = visual.get("product_name")
            found.append(
                Alternative(
                    id=identifier,
                    code=_text(item.get("code")) or f"#{len(found) + 1}",
                    number=len(found) + 1,
                    title=_text(item.get("title")),
                    summary=_text(item.get("summary")),
                    product_name=product if isinstance(product, str) and product else None,
                    choices={
                        str(name): str(value)
                        for name, value in (choices.items() if isinstance(choices, Mapping) else ())
                    },
                    recommended=identifier == recommended,
                    direction=_direction(visual.get("direction")),
                )
            )
        return tuple(found)

    @property
    def chosen(self) -> Alternative | None:
        selected = self.package.get("owner_selected_alternative_id")
        if not isinstance(selected, str) or not isinstance(self.package.get("prototype"), Mapping):
            return None
        return self.alternative_by_id(selected)

    @property
    def applied_mockup(self) -> str | None:
        bound = self.package.get("generated_mockup")
        mockup = bound.get("mockup") if isinstance(bound, Mapping) else None
        identifier = mockup.get("design_alternative_id") if isinstance(mockup, Mapping) else None
        return identifier if isinstance(identifier, str) else None

    @property
    def changeable(self) -> bool:
        return (
            self.chosen is not None
            and self.capabilities.iterations
            and self.applied_mockup is not None
        )

    @property
    def twins(self) -> tuple[tuple[str, str], ...]:
        grounding = self.package.get("grounding")
        references = (
            grounding.get("user_twin_references") if isinstance(grounding, Mapping) else None
        )
        found: dict[str, str] = {}
        for item in _mappings(references):
            identifier = item.get("twin_id")
            if isinstance(identifier, str):
                found.setdefault(identifier, _text(item.get("name")) or identifier)
        for verdict in self._critiques():
            found.setdefault(verdict.twin_id, verdict.twin_name)
        return tuple(found.items())

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        return self._critiques()

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(
            item
            for item in _sequence(self.package.get("owner_assertions"))
            if isinstance(item, str)
        )

    def alternative_by_id(self, identifier: str) -> Alternative | None:
        return next((item for item in self.alternatives if item.id == identifier), None)

    def find(self, value: str) -> Alternative | None:
        wanted = value.strip().casefold()
        alternatives = self.alternatives
        if wanted.isdecimal():
            number = int(wanted)
            return alternatives[number - 1] if 1 <= number <= len(alternatives) else None
        return next((item for item in alternatives if item.code.casefold() == wanted), None)

    def missing_mockups(self) -> tuple[Alternative, ...]:
        if not self.generated:
            return ()
        return tuple(item for item in self.alternatives if item.id not in self.documents)

    def choosable(self) -> tuple[Alternative, ...]:
        chosen = self.chosen
        return tuple(
            item
            for item in self.alternatives
            if (chosen is None or item.id != chosen.id)
            and (not self.generated or item.id in self.documents)
        )

    def _critiques(self) -> tuple[Verdict, ...]:
        found: list[Verdict] = []
        for item in _mappings(self.package.get("critiques")):
            reference = item.get("user_twin_reference")
            reference = reference if isinstance(reference, Mapping) else {}
            twin = reference.get("twin_id")
            alternative = item.get("design_alternative_id")
            if not isinstance(twin, str) or not isinstance(alternative, str):
                continue
            found.append(
                Verdict(
                    twin_id=twin,
                    twin_name=_text(reference.get("name")) or twin,
                    alternative_id=alternative,
                    verdict=_optional_text(item.get("verdict")),
                    quote=_optional_text(item.get("quote")),
                    points=tuple(
                        (name, texts) for name in POINT_FIELDS if (texts := _texts(item.get(name)))
                    ),
                )
            )
        return tuple(found)


def read_state(client: StudioClient, project: ProjectFolder) -> DesignState:
    link = project.link()
    project_id = link.project_id
    summary = project_api.get_project(client, project_id)
    name = _text(summary.get("display_name")) or link.project_name
    state = DesignState(
        project_id=project_id, project_name=name, stage=_text(summary.get("current_stage"))
    )
    if state.stage not in DESIGN_STAGES:
        return state
    readiness = design_api.readiness(client, project_id)
    version = readiness.get("version")
    running = tuple(
        job
        for job in jobs.running_jobs(client, project_id)
        if job.get("operation") in DESIGN_OPERATIONS
    )
    state = replace(
        state,
        version=version if isinstance(version, Mapping) and "package" in version else None,
        approved=readiness.get("approved_current_package") is True,
        capabilities=design_api.capabilities(client, project_id),
        running=running,
    )
    if state.version is None or running:
        return state
    state = replace(state, documents=read_documents(client, state))
    if state.chosen is None:
        return state
    return replace(
        state,
        review=latest_review(client, state),
        pending_change=pending_change(client, state),
    )


def with_distance(client: StudioClient, state: DesignState) -> DesignState:
    version = state.version
    if version is None or all(item.direction is None for item in state.alternatives):
        return state
    report = design_api.distance(client, state.project_id)
    if report is None or report.get("design_version_id") != version.get("id"):
        return state
    return replace(state, distance=report)


def read_documents(client: StudioClient, state: DesignState) -> Mapping[str, Mapping[str, object]]:
    if not state.generated:
        return EMPTY
    documents: dict[str, Mapping[str, object]] = {}
    applied = state.applied_mockup
    for alternative in state.alternatives:
        source = design_api.APPLIED if alternative.id == applied else design_api.LATEST
        document = design_api.mockup_document(
            client, state.project_id, alternative.id, source=source
        )
        if document is not None:
            documents[alternative.id] = document
    return MappingProxyType(documents)


def latest_review(client: StudioClient, state: DesignState) -> Mapping[str, object] | None:
    identifier = None if state.version is None else state.version.get("id")
    return next(
        (
            run
            for run in design_api.evaluations(client, state.project_id)
            if run.get("design_version_id") == identifier
        ),
        None,
    )


def pending_change(client: StudioClient, state: DesignState) -> Mapping[str, object] | None:
    if not state.capabilities.iterations or state.applied_mockup is None:
        return None
    number = state.version_number
    return next(
        (
            item
            for item in design_api.iterations(client, state.project_id)
            if item.get("status") == PROPOSED and item.get("base_design_version_number") == number
        ),
        None,
    )


def chosen_mockup(client: StudioClient, state: DesignState) -> Mapping[str, object] | None:
    chosen = state.chosen
    if chosen is None or state.applied_mockup != chosen.id:
        return None
    document = state.documents.get(chosen.id)
    if document is None:
        document = design_api.mockup_document(
            client, state.project_id, chosen.id, source=design_api.APPLIED
        )
    return document


def document_screens(document: Mapping[str, object] | None) -> tuple[MockupScreen, ...]:
    html = None if document is None else document.get("html")
    return mockup_screens(html) if isinstance(html, str) else ()


def mockup_screens(html: str) -> tuple[MockupScreen, ...]:
    parser = _MockupParser(html)
    parser.feed(html)
    parser.finish()
    return tuple(
        _screen(parser, node)
        for node in _descendants(parser.root)
        if node.tag == "section" and SCREEN_ID.fullmatch(node.attributes.get("id", ""))
    )


def clipped(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def show_state(
    context: CommandContext,
    state: DesignState,
    *,
    everything: bool = False,
    modelless: bool = False,
) -> None:
    kind = state.kind
    listed = kind in (NO_MOCKUPS, MOCKUPS_READY) or (everything and state.version is not None)
    if listed:
        show_alternatives(context, state)
        show_distance(context, state)
        show_verdicts(context, state)
    if kind in (CHOSEN, APPROVED):
        show_chosen(context, state)
    if state.version is not None and not state.generated and (listed or modelless):
        say_without_previews(context, state, modelless=modelless)


def say_without_previews(context: CommandContext, state: DesignState, *, modelless: bool) -> None:
    if not modelless:
        key = "design.previews_unavailable"
    elif state.chosen is None:
        key = "design.no_model"
    else:
        key = "design.no_model_chosen"
    context.console.say(key)


def show_alternatives(context: CommandContext, state: DesignState, *, mockups: bool = True) -> None:
    console = context.console
    console.write()
    console.heading(context.text("design.alternatives_heading"))
    for alternative in state.alternatives:
        show_alternative(context, state, alternative, mockups=mockups)


def show_alternative(
    context: CommandContext,
    state: DesignState,
    alternative: Alternative,
    *,
    mockups: bool = True,
) -> None:
    console = context.console
    key = "design.alternative_recommended" if alternative.recommended else "design.alternative"
    wrapped(context, context.text(key, code=alternative.code, title=alternative.title), hang="  ")
    if alternative.summary:
        wrapped(context, alternative.summary, indent="  ")
    if alternative.product_name:
        product = context.text("design.alternative_product", name=alternative.product_name)
        wrapped(context, product, hang="    ")
    line = visual_line(context, alternative)
    if line is not None:
        wrapped(context, line, indent="  ")
    direction = direction_line(context, alternative)
    if direction is not None:
        wrapped(context, direction, indent="  ")
    if mockups and state.generated and state.chosen is None:
        ready = alternative.id in state.documents
        console.say("design.mockup_present" if ready else "design.mockup_absent")
    console.write()


def show_distance(context: CommandContext, state: DesignState) -> None:
    report = state.distance
    if report is None:
        return
    pairs = _mappings(report.get("pairs"))
    lines = [line for pair in pairs for line in pair_lines(context, pair, named=len(pairs) > 1)]
    lines.extend(adherence_lines(context, report))
    if not lines:
        return
    console = context.console
    console.heading(context.text("design.distance_heading"))
    for line in [*lines, context.text("design.distance_caveat")]:
        wrapped(context, line)
    console.write()


def pair_lines(context: CommandContext, pair: Mapping[str, object], *, named: bool) -> list[str]:
    declared = _mapping(pair.get("declared"))
    verdict = pair.get("verdict")
    head = [context.text(f"design.distance_{verdict}")] if verdict in VERDICTS else []
    count = _whole(declared.get("axes_different"))
    if count is not None:
        head.append(context.text("design.distance_axes", count=count))
    score = _whole(declared.get("score"))
    levels = [] if score is None else [context.text("design.distance_declared", score=score)]
    for name, key in LEVELS:
        level = _mapping(pair.get(name))
        score = _whole(level.get("score"))
        if level.get("available") is True and score is not None:
            levels.append(context.text(key, score=score))
    lines: list[str] = []
    if head:
        text = JOINER.join(head)
        if named:
            text = context.text(
                "design.distance_pair",
                first=_text(pair.get("first")) or "-",
                second=_text(pair.get("second")) or "-",
                verdict=text,
            )
        lines.append(text)
    if levels:
        lines.append(JOINER.join(levels))
    if verdict == CLOSE:
        lines.append(context.text("design.distance_close"))
    return lines


def adherence_lines(context: CommandContext, report: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for item in _mappings(report.get("alternatives")):
        adherence = _mapping(item.get("adherence"))
        axes = _mapping(adherence.get("axes")) if adherence.get("available") is True else {}
        missed = [
            directions.axis_label(context.text, axis)
            for axis in directions.AXES
            if axes.get(axis) == NOT_FOLLOWED
        ]
        if missed:
            lines.append(
                context.text(
                    "design.distance_adherence",
                    code=_text(item.get("code")) or "-",
                    axes=", ".join(missed),
                )
            )
    return lines


def show_verdicts(context: CommandContext, state: DesignState) -> None:
    verdicts = state.verdicts
    alternatives = state.alternatives
    judged = [item for item in verdicts if item.verdict]
    quoted = [item for item in verdicts if item.quote]
    explained = [item for item in verdicts if not item.verdict and item.points]
    if not alternatives or not (judged or quoted or explained):
        return
    console = context.console
    console.heading(context.text("design.verdicts_heading"))
    if judged:
        columns = [
            alternative
            for alternative in alternatives
            if any(item.alternative_id == alternative.id for item in judged)
        ]
        rows = [
            [name, *(_verdict_cell(context, verdicts, twin, item.id) for item in columns)]
            for twin, name in state.twins
            if any(item.twin_id == twin for item in judged)
        ]
        console.table([context.text("design.column_twin"), *(item.code for item in columns)], rows)
    spaced = bool(judged)
    for alternative in alternatives:
        quotes = [
            context.text("design.quote", twin=item.twin_name, quote=item.quote)
            for item in quoted
            if item.alternative_id == alternative.id
        ]
        if quotes:
            if spaced:
                console.write()
            spaced = True
            console.write(alternative.code)
            console.items(quotes)
    for alternative in alternatives:
        critiques = [item for item in explained if item.alternative_id == alternative.id]
        if not critiques:
            continue
        if spaced:
            console.write()
        spaced = True
        title = context.text("design.alternative", code=alternative.code, title=alternative.title)
        wrapped(context, title, hang="  ")
        for critique in critiques:
            wrapped(context, critique.twin_name, indent="  ")
            bullets(context, point_lines(context, critique), indent="  ")
    console.write()


def point_lines(context: CommandContext, critique: Verdict) -> list[str]:
    return [
        context.text("design.point", label=context.text(f"design.point_{name}"), text=joined(texts))
        for name, texts in critique.points
    ]


def joined(texts: Sequence[str]) -> str:
    result = ""
    for text in texts:
        if result:
            result += " " if result.endswith(SENTENCE_ENDINGS) else "; "
        result += text
    return result


def wrapped(
    context: CommandContext, text: str, *, indent: str = "", hang: str | None = None
) -> None:
    console = context.console
    following = indent if hang is None else hang
    first = indent
    for paragraph in text.splitlines() or [""]:
        lines = textwrap.wrap(
            paragraph,
            width=max(console.width, MINIMUM_WIDTH),
            initial_indent=first,
            subsequent_indent=following,
            break_long_words=False,
            break_on_hyphens=False,
        )
        for line in lines or [first.rstrip()]:
            console.write(line)
        first = following


def bullets(context: CommandContext, lines: Sequence[str], *, indent: str = "") -> None:
    for line in lines:
        wrapped(context, line, indent=f"{indent}- ", hang=f"{indent}  ")


def show_chosen(context: CommandContext, state: DesignState) -> None:
    alternative = state.chosen
    if alternative is None:
        return
    console = context.console
    console.write()
    console.heading(context.text("design.chosen_heading"))
    key = "design.chosen_approved" if state.approved else "design.chosen_waiting"
    console.say(key, version=state.version_number or "-")
    show_alternative(context, state, alternative)
    show_rules(context, state.rules, changeable=state.changeable)


def show_rules(context: CommandContext, rules: Sequence[str], *, changeable: bool = True) -> None:
    console = context.console
    if not rules:
        console.say("design.rules_none" if changeable else "design.rules_none_plain")
        return
    console.say("design.rules_heading")
    console.items(list(rules))


def show_folder(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
) -> None:
    console = context.console
    target = project.knowledge
    try:
        local = knowledge.summary(target)
    except CliError as error:
        console.say("design.folder_unreadable", path=str(target), code=error.values.get("code"))
        return
    latest = _latest_folder(client, state.project_id)
    if local is not None:
        console.say(
            "design.folder_here",
            path=str(target),
            version=local.version_number,
            files=local.file_count,
        )
        if latest is not None and latest > local.version_number:
            console.say("design.folder_newer", version=latest)
    elif latest is not None:
        console.say("design.folder_not_here", version=latest, path=str(target))
    else:
        console.say("design.folder_not_published")


def show_next_commands(context: CommandContext) -> None:
    context.console.items([context.text(key) for key in NEXT_COMMANDS])


def show_summary(context: CommandContext, state: DesignState) -> None:
    console = context.console
    kind = state.kind
    chosen = state.chosen
    if kind == NO_MOCKUPS:
        console.say("design.summary_no_mockups")
    elif kind == MOCKUPS_READY:
        ready = [item.code for item in state.alternatives if item.id in state.documents]
        if state.generated and ready:
            console.say("design.summary_mockups", codes=", ".join(ready))
        else:
            console.say("design.summary_alternatives")
    elif kind == CHOSEN and chosen is not None:
        console.say(
            "design.summary_chosen",
            code=chosen.code,
            title=chosen.title,
            version=state.version_number or "-",
        )
    elif kind == APPROVED and chosen is not None:
        console.say(
            "design.summary_approved",
            code=chosen.code,
            title=chosen.title,
            version=state.version_number or "-",
        )


def visual_line(context: CommandContext, alternative: Alternative) -> str | None:
    choices = alternative.choices
    if not choices:
        return None
    words = {
        VISUAL_PLACEHOLDERS[dimension]: visual_word(context, dimension, choices.get(dimension))
        for dimension in VISUAL_DIMENSIONS
    }
    return context.text("design.visual_line", **words)


def visual_word(context: CommandContext, dimension: str, value: str | None) -> str:
    if not value:
        return "-"
    key = f"design.visual_{dimension}_{value}"
    if known(key):
        return context.text(key)
    return value.replace("_", " ").lower()


def direction_line(context: CommandContext, alternative: Alternative) -> str | None:
    direction = alternative.direction
    if direction is None:
        return None
    words = directions.value_labels(context.text, direction.axes)
    return context.text("design.alternative_direction", name=direction.name, axes=", ".join(words))


def _latest_folder(client: StudioClient, project_id: str) -> int | None:
    try:
        latest = packages.latest(client, project_id)
    except ApiFailure as failure:
        if failure.http_status == 404 or failure.http_status >= 500:
            return None
        raise
    number = None if latest is None else latest.get("version_number")
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def _verdict_cell(
    context: CommandContext, verdicts: Sequence[Verdict], twin: str, alternative: str
) -> str:
    found = next(
        (item for item in verdicts if item.twin_id == twin and item.alternative_id == alternative),
        None,
    )
    if found is None:
        return "-"
    if found.verdict:
        return found.verdict
    if found.quote or found.points:
        return context.text("design.verdict_below")
    return "-"


def _direction(value: object) -> Direction | None:
    if not isinstance(value, Mapping):
        return None
    name = _text(value.get("name"))
    if not name:
        return None
    axes = directions.axes_of(value)
    return Direction(
        name=name,
        axes={axis: str(axes[axis]) for axis in directions.AXES if isinstance(axes.get(axis), str)},
    )


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in _sequence(value) if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _texts(value: object) -> tuple[str, ...]:
    return tuple(text for item in _sequence(value) if (text := _text(item)))


def _screen(parser: _MockupParser, node: _Node) -> MockupScreen:
    elements: dict[str, MockupElement] = {}
    for item in _descendants(node):
        code = item.attributes.get(ELEMENT_MARK)
        if not code or code in elements or _closest_screen(item) is not node:
            continue
        elements[code] = MockupElement(
            code=code,
            kind=item.tag,
            text=_visible_text(parser, item),
            html=_outer(parser, item),
        )
    return MockupScreen(
        code=node.attributes["id"],
        title=_normalized(node.attributes.get("aria-label", "")),
        html=_outer(parser, node),
        elements=tuple(elements.values()),
    )


def _outer(parser: _MockupParser, node: _Node) -> str:
    return clipped(parser.source[node.start : node.end], HTML_LIMIT)


def _descendants(node: _Node) -> Iterator[_Node]:
    pending = [child for child in reversed(node.children) if isinstance(child, _Node)]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(child for child in reversed(current.children) if isinstance(child, _Node))


def _closest(node: _Node, tag: str) -> _Node | None:
    current: _Node | None = node
    while current is not None and current.tag != tag:
        current = current.parent
    return current


def _closest_screen(node: _Node) -> _Node | None:
    current = node.parent
    while current is not None and not (
        current.tag == "section" and SCREEN_ID.fullmatch(current.attributes.get("id", ""))
    ):
        current = current.parent
    return current


def _visible_text(parser: _MockupParser, node: _Node) -> str:
    return clipped(next((text for text in _names(parser, node) if text), ""), LABEL_LIMIT)


def _names(parser: _MockupParser, node: _Node) -> Iterator[str]:
    yield _own_text(node)
    references = node.attributes.get("aria-labelledby", "").split()
    yield _normalized(
        " ".join(_content(parser.ids[name]) for name in references if name in parser.ids)
    )
    yield _normalized(node.attributes.get("aria-label", ""))
    yield _label_text(parser, node)
    for name in NAME_ATTRIBUTES:
        yield _normalized(node.attributes.get(name, ""))


def _label_text(parser: _MockupParser, node: _Node) -> str:
    identifier = node.attributes.get("id")
    labels = [
        label
        for label in parser.labels
        if identifier is not None and label.attributes.get("for") == identifier
    ]
    owner = _closest(node, "label")
    if owner is not None:
        labels.append(owner)
    return _normalized(" ".join(_own_text(label) for label in labels))


def _own_text(node: _Node) -> str:
    if node.tag == "select":
        options = [item for item in _descendants(node) if item.tag == "option"]
        selected = next(
            (item for item in options if "selected" in item.attributes),
            options[0] if options else None,
        )
        return "" if selected is None else _normalized(_content(selected))
    if node.tag == "textarea":
        return _normalized(_content(node))
    parts: list[str] = []
    _collect(node, parts)
    return _normalized("".join(parts))


def _collect(node: _Node, parts: list[str]) -> None:
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif not _silent(child):
            spacer = " " if child.tag in BLOCK_TAGS else ""
            parts.append(spacer)
            _collect(child, parts)
            parts.append(spacer)


def _silent(node: _Node) -> bool:
    return (
        node.tag in SILENT_TAGS
        or "hidden" in node.attributes
        or PIN_CLASS in node.attributes.get("class", "").split()
    )


def _content(node: _Node) -> str:
    return "".join(child if isinstance(child, str) else _content(child) for child in node.children)


def _normalized(text: str) -> str:
    return " ".join(text.split())
