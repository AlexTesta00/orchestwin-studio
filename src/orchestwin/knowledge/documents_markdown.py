from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from orchestwin.workflow.gates import HumanGate

UNSET: Final = "not provided"


def plain_text(value: object) -> str:
    if value is None:
        return UNSET
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value if value.strip() else UNSET
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {plain_text(item)}" for key, item in value.items()) or UNSET
    if isinstance(value, Sequence):
        return ", ".join(plain_text(item) for item in value) if value else UNSET
    return str(value)


def title_text(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _inline(value: object) -> str:
    return " ".join(str(value).split())


def _bare(value: object) -> str:
    return _inline(value).rstrip(".")


def _sentence(value: object) -> str:
    text = _inline(value)
    return text if not text or text.endswith((".", "!", "?", "…")) else f"{text}."


def markdown_bullets(items: Iterable[object]) -> list[str]:
    lines = [f"- {plain_text(item)}" for item in items]
    return lines or [f"- {UNSET}"]


def _cell(value: object) -> str:
    if value is None or (isinstance(value, Sequence) and not isinstance(value, str) and not value):
        return ""
    return plain_text(value).replace("|", "/").replace("\n", " ")


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    body = ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    if not body:
        return [f"{UNSET}."]
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
        *body,
    ]


def _version_lines(label: str, version: object, gate: HumanGate) -> list[str]:
    return [
        f"# {label}",
        "",
        f"Version {version.version_number}, content hash `{version.content_hash}`, "
        f"approved by the owner on {gate.updated_at.isoformat()}.",
        "",
    ]


def code_list(identifiers: Iterable[str], codes: Mapping[str, str]) -> str:
    return (
        ", ".join(sorted(codes.get(identifier, identifier) for identifier in identifiers)) or UNSET
    )


def twin_names(references: Iterable[Mapping[str, object]]) -> str:
    names = sorted(
        (str(reference["name"]) for reference in references),
        key=lambda name: (name.casefold(), name),
    )
    return ", ".join(names)


def _links(entries: Sequence[Mapping[str, object]]) -> list[str]:
    links = [f"- [{_inline(entry['title'])}]({entry['path']})" for entry in entries]
    return links or [f"- {UNSET}"]


def views_markdown(
    *,
    tables: Sequence[Mapping[str, object]],
    diagrams: Sequence[Mapping[str, object]],
    mermaid_version: str,
) -> str:
    lines = [
        "",
        "## Views",
        "",
        "This document is the text view. The same content is in the tables (CSV) and in the "
        f"diagrams (Mermaid {mermaid_version}) below; the links are relative to this document.",
        "",
        "Tables:",
        *_links(tables),
        "",
        "Diagrams:",
        *_links(diagrams),
        "",
    ]
    return "\n".join(lines)


def counted(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"
