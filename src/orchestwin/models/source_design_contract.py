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

    def require(condition):
        if not condition:
            raise ProposalGenerationError("SOURCE_DESIGN_STRUCTURE_MISMATCH")

    def one(attribute, value):
        nodes = [node for node in document.nodes if node.attrs.get(attribute) == value]
        require(len(nodes) == 1)
        return nodes[0]

    def inside(node, ancestor):
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False

    screens = {screen["id"]: screen for screen in prototype["screens"]}
    transitions = {edge["trigger_element_id"]: edge for edge in prototype.get("transitions", [])}
    for screen in screens.values():
        container = one("data-design-screen", screen["code"])
        previous = -1
        for element in screen.get("elements", []):
            kind = element["kind"]
            if kind not in _TAGS:
                continue
            node = one("data-design-element", element["code"])
            require(inside(node, container) and node.tag == _TAGS[kind])
            position = document.nodes.index(node)
            require(position > previous)
            previous = position
            label = element.get("accessible_name") or element["content"]
            if kind in {"TEXT_INPUT", "SELECT"}:
                require(node.attrs.get("name") == element["field_name"])
                require(("required" in node.attrs) == element.get("required", False))
                labels = [
                    x.label_content()
                    for x in document.nodes
                    if x.tag == "label"
                    and (
                        (node.attrs.get("id") and x.attrs.get("for") == node.attrs["id"])
                        or inside(node, x)
                    )
                ]
                require(node.attrs.get("aria-label") == label or label in labels)
                if kind == "SELECT":
                    options = [
                        x.content()
                        for x in node.children
                        if x.tag == "option" and "disabled" not in x.attrs
                    ]
                    require(options == list(element["options"]))
            else:
                require(node.attrs.get("aria-label", node.content()) == label)
                edge = transitions.get(element["id"])
                if edge:
                    require(
                        node.attrs.get("data-design-target")
                        == screens[edge["target_screen_id"]]["code"]
                    )
