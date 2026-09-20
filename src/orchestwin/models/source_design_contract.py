"""Check declared UI structure against a selected prototype, not pixel fidelity."""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from orchestwin.models.proposal_generation import ProposalGenerationError

_VOID = {
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
    "param",
    "source",
    "track",
    "wbr",
}
_TAGS = {"TEXT_INPUT": "input", "SELECT": "select", "BUTTON": "button", "LINK": "a"}
_TEXT_TAGS = {
    "caption",
    "dd",
    "div",
    "dt",
    "figcaption",
    "li",
    "span",
    "p",
    "output",
    "pre",
    "small",
    "strong",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "td",
    "th",
}


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict
    parent: object = None
    children: list = field(default_factory=list)
    text: str = ""

    def content(self):
        return " ".join((self.text + " " + " ".join(x.content() for x in self.children)).split())

    def label_content(self):
        # A nested select's options are values, not part of its enclosing label.
        if self.tag in {"input", "select", "textarea"}:
            return ""
        return " ".join(
            (self.text + " " + " ".join(x.label_content() for x in self.children)).split()
        )


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].text += data


def validate_prototype_html(content, prototype):
    """Require the exact selected controls, names, options, order and screen edges.

    This checks static structure only. CSS appearance and actual business behavior
    still require browser verification. Extra business/error controls are allowed.
    """
    if not prototype or not prototype.get("screens"):
        return
    document = _Document()
    document.feed(content)

    def require(condition, reason, **details):
        if not condition:
            error = ProposalGenerationError("SOURCE_DESIGN_STRUCTURE_MISMATCH")
            error.diagnostic = {"reason": reason, **details}
            raise error

    def one(attribute, value):
        nodes = [node for node in document.nodes if node.attrs.get(attribute) == value]
        require(
            len(nodes) == 1,
            "EXACTLY_ONE_MARKER_REQUIRED",
            attribute=attribute,
            value=value,
            actual_count=len(nodes),
        )
        return nodes[0]

    def inside(node, ancestor):
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False

    identifiers = [node.attrs["id"] for node in document.nodes if "id" in node.attrs]
    require(len(identifiers) == len(set(identifiers)), "HTML_IDS_MUST_BE_UNIQUE")
    screens = {screen["id"]: screen for screen in prototype["screens"]}
    transitions = {edge["trigger_element_id"]: edge for edge in prototype.get("transitions", [])}
    for screen in screens.values():
        container = one("data-design-screen", screen["code"])
        previous = -1
        for element in screen.get("elements", []):
            kind = element["kind"]
            if kind not in _TAGS and kind != "TEXT":
                continue
            node = one("data-design-element", element["code"])
            details = {"element": element["code"], "screen": screen["code"]}
            require(inside(node, container), "ELEMENT_IN_APPROVED_SCREEN_REQUIRED", **details)
            require(
                node.tag in _TEXT_TAGS if kind == "TEXT" else node.tag == _TAGS[kind],
                "APPROVED_CONTROL_KIND_REQUIRED",
                expected_kind=kind,
                actual_tag=node.tag,
                **details,
            )
            position = document.nodes.index(node)
            require(position > previous, "APPROVED_ELEMENT_ORDER_REQUIRED", **details)
            previous = position
            if kind == "TEXT":
                # Dynamic results need the approved location, not placeholder text.
                continue
            label = element.get("accessible_name") or element["content"]
            if kind in {"TEXT_INPUT", "SELECT"}:
                require(
                    node.attrs.get("name") == element["field_name"],
                    "APPROVED_FIELD_NAME_REQUIRED",
                    expected=element["field_name"],
                    **details,
                )
                require(
                    ("required" in node.attrs) == element.get("required", False),
                    "APPROVED_REQUIRED_ATTRIBUTE_REQUIRED",
                    expected=element.get("required", False),
                    **details,
                )
                labels = [
                    x.label_content()
                    for x in document.nodes
                    if x.tag == "label"
                    and (
                        (node.attrs.get("id") and x.attrs.get("for") == node.attrs["id"])
                        or inside(node, x)
                    )
                ]
                require(
                    node.attrs.get("aria-label") == label or label in labels,
                    "APPROVED_ACCESSIBLE_LABEL_REQUIRED",
                    expected=label,
                    **details,
                )
                if kind == "SELECT":
                    options = [
                        x.content()
                        for x in node.children
                        if x.tag == "option" and "disabled" not in x.attrs
                    ]
                    require(
                        options == list(element["options"]),
                        "APPROVED_SELECT_OPTIONS_REQUIRED",
                        expected=list(element["options"]),
                        **details,
                    )
            else:
                require(
                    node.attrs.get("aria-label", node.content()) == label,
                    "APPROVED_ACCESSIBLE_LABEL_REQUIRED",
                    expected=label,
                    **details,
                )
                edge = transitions.get(element["id"])
                if edge:
                    require(
                        node.attrs.get("data-design-target")
                        == screens[edge["target_screen_id"]]["code"],
                        "APPROVED_TRANSITION_TARGET_REQUIRED",
                        expected=screens[edge["target_screen_id"]]["code"],
                        **details,
                    )
