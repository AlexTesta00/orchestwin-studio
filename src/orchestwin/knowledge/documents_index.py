from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from orchestwin.knowledge.documents_markdown import _bare, _inline, counted, markdown_table
from orchestwin.knowledge.layout import STAGE_LABELS, STAGES, VIEW_STAGES, present_stages

OVERVIEW_DESCRIPTION_LENGTH: Final = 300
OVERVIEW_REQUIREMENTS: Final = 12
_ROLE_KEY: Final = "user_twin.role"
_MUST: Final = "MUST"
_VERIFIED: Final = "- How it is verified: {criteria}, which `ut test` checks in the browsers."
_OVERVIEW_TEXTS: Final[dict[str, dict[str, Any]]] = {
    "en": {
        "heading": "## In short",
        "project": "- Project: {name}.",
        "described": "- Project: {name}. {description}",
        "twins": "- Who it is for: {twins}.",
        "must": "- What it must do:",
        "more": ("and 1 more.", "and {count} more."),
        "design": "- Chosen design: {alternative}.",
        "product": "{alternative} (product name: {product})",
        "criteria": (_VERIFIED, _VERIFIED),
        "criterion_words": ("acceptance criterion", "acceptance criteria"),
    },
    "it": {
        "heading": "## In breve",
        "project": "- Progetto: {name}.",
        "described": "- Progetto: {name}. {description}",
        "twins": "- Per chi è: {twins}.",
        "must": "- Cosa deve fare:",
        "more": ("e un altro.", "e altri {count}."),
        "design": "- Design scelto: {alternative}.",
        "product": "{alternative} (nome del prodotto: {product})",
        "criteria": (
            "- Come si verifica: {criteria}, controllato da `ut test` nei browser.",
            "- Come si verifica: {criteria}, controllati da `ut test` nei browser.",
        ),
        "criterion_words": ("criterio di accettazione", "criteri di accettazione"),
    },
}
_STEP_NAMES: Final = ", ".join(STAGE_LABELS[stage] for stage in STAGES)


def excerpt(text: str, limit: int = OVERVIEW_DESCRIPTION_LENGTH) -> str:
    flat = _inline(text)
    if len(flat) <= limit:
        return flat
    head = flat[: limit + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else flat[:limit]
    return f"{cut.rstrip(' ,;:.')}…"


def _stage_rows(manifest: Mapping[str, object]) -> list[tuple[object, ...]]:
    return [
        (
            entry["label"],
            f"`{entry['text']}`",
            f"`{entry['document']}`",
            entry["version_number"],
            entry["content_hash"],
            entry["gate"]["gate_type"],
            entry["gate"]["updated_at"],
        )
        for entry in (manifest["stages"][stage] for stage in present_stages(manifest))
    ]


def _view_rows(manifest: Mapping[str, object]) -> list[tuple[object, ...]]:
    views = manifest["views"]
    return [
        (stage, form, f"`{entry['path']}`", entry["title"])
        for stage, view in ((name, views[name]) for name in VIEW_STAGES if name in views)
        for form, key in (
            ("text", "text"),
            ("table", "tables"),
            ("diagram", "diagrams"),
            ("mockup", "mockups"),
        )
        for entry in view[key]
    ]


def feedback_counts(counts: Mapping[str, object]) -> str:
    return (
        f"{counted(counts['reviews'], 'review', 'reviews')} with "
        f"{counted(counts['findings'], 'finding', 'findings')}, "
        f"{counted(counts['decisions'], 'owner decision', 'owner decisions')}, "
        f"{counted(counts['discussions'], 'approved discussion', 'approved discussions')} and "
        f"{counted(counts['insights'], 'applied insight', 'applied insights')}"
    )


def progress_sentence(manifest: Mapping[str, object]) -> str:
    present = present_stages(manifest)
    held = f"This folder holds {len(present)} of {len(STAGES)} approved steps"
    if len(present) == len(STAGES):
        return f"{held}; every step is approved."
    return f"{held}; next: {STAGE_LABELS[STAGES[len(present)]]}."


def _scope_line(present: tuple[str, ...]) -> str:
    if "design" in present:
        return (
            "- Build against `requirements/requirements.md` and `design/design.md`: they are the "
            "approved scope. Requirements, user stories, acceptance criteria, screens and "
            "elements have stable codes (REQ-001, USR-001, AC-001, SCR-001, ELM-001): quote them "
            "in code reviews, commits and tests."
        )
    if "requirements" in present:
        return (
            "- The requirements are approved in `requirements/requirements.md`, with stable codes "
            "(REQ-001, USR-001, AC-001); the design comes into this folder once the owner "
            "approves it, and only then is the scope complete."
        )
    return (
        "- The scope is not approved yet: the requirements and the design come into this folder "
        "once the owner approves them, and only then is there an approved scope to build against."
    )


def _usage_lines(manifest: Mapping[str, object]) -> list[str]:
    present = present_stages(manifest)
    state = manifest.get("state")
    lines = [_scope_line(present)]
    if "twins" in present:
        lines.extend(
            [
                "- Judge every change from the point of view of the user twins in `twins/`: each "
                "twin has a profile with goals, constraints and accessibility needs.",
                "- Treat the twins as models: an observation or a finding is an assumption until "
                "a person validates it.",
            ]
        )
    lines.extend(
        [
            "- Do not edit the files of the approved stages: their digests are in "
            f"`{manifest['manifest']}`. A change of scope goes through the Studio and produces a "
            "new version of this folder.",
            f"- The feedback of the twins lives in `{manifest['feedback']['folder']}/`.",
        ]
    )
    if isinstance(state, Mapping):
        lines.append(
            f"- The state of the development is in `{state['text']}` and `{state['document']}`: "
            "the commits recorded in the Studio, the critiques of the twins on them, the "
            "decisions of the owner and the tasks for the code."
        )
    return lines


def _twin_lines(manifest: Mapping[str, object]) -> list[str]:
    if "twins" not in present_stages(manifest):
        return []
    return [
        "## User twins",
        "",
        *markdown_table(
            ("Twin", "Text", "Portable copy", "Version", "Validation status"),
            (
                (
                    twin["name"],
                    f"`{twin['text']}`",
                    f"`{twin['document']}`",
                    twin["version_number"],
                    twin["validation_status"],
                )
                for twin in manifest["twins"]
            ),
        ),
        "",
    ]


def _views_lines(manifest: Mapping[str, object]) -> list[str]:
    if not any(stage in manifest["views"] for stage in VIEW_STAGES):
        return []
    return [
        "## Views",
        "",
        "The approved requirements and design are available in three forms: text (Markdown), "
        f"tables (CSV) and diagrams (Mermaid {manifest['generator']['mermaid_version']}, linked "
        "from the Markdown documents).",
        "",
        *markdown_table(("Stage", "Form", "File", "Content"), _view_rows(manifest)),
        "",
    ]


def _feedback_lines(manifest: Mapping[str, object]) -> list[str]:
    feedback = manifest["feedback"]
    lines = ["## Twin feedback", ""]
    if feedback.get("text"):
        lines.append(
            f"`{feedback['text']}` summarises {feedback_counts(feedback)} recorded in the Studio. "
            "The exact records are in the JSON files of the same folder."
        )
    else:
        lines.append(
            "The feedback of the twins on the design comes into this folder once the design is "
            "approved."
        )
    if feedback.get("changes"):
        runs = counted(feedback.get("change_reviews") or 0, "review run", "review runs")
        lines.extend(
            ["", f"`{feedback['changes']}` holds {runs} of the twins on the code changes."]
        )
    return [*lines, ""]


def _overview_project(name: str, brief: Mapping[str, object], texts: Mapping[str, Any]) -> str:
    description = brief["fields"].get("description")
    if not isinstance(description, str) or not description.strip():
        return texts["project"].format(name=_bare(name))
    return texts["described"].format(name=_bare(name), description=excerpt(description))


def _role(profile: Mapping[str, object]) -> str | None:
    for observation in profile["observations"]:
        if observation["observation_key"] == _ROLE_KEY:
            text = observation["value"].get("text")
            return _bare(text) if isinstance(text, str) and text.strip() else None
    return None


def _twin_label(profile: Mapping[str, object]) -> str:
    name = _bare(profile["name"])
    role = _role(profile)
    if role is None or role.casefold() == name.casefold():
        return name
    return f"{name} ({role})"


def _overview_twins(twins: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    labels = [_twin_label(twin["profile"]) for twin in twins["twin_versions"]]
    return [texts["twins"].format(twins="; ".join(labels))] if labels else []


def _overview_must(specification: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    must = [item for item in specification["requirements"] if item["priority"] == _MUST]
    if not must:
        return []
    lines = [
        texts["must"],
        *(f"  - {item['code']} {_bare(item['title'])}" for item in must[:OVERVIEW_REQUIREMENTS]),
    ]
    hidden = len(must) - OVERVIEW_REQUIREMENTS
    if hidden > 0:
        one, many = texts["more"]
        lines.append(f"  - {(one if hidden == 1 else many).format(count=hidden)}")
    return lines


def _overview_design(package: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    selected = package.get("owner_selected_alternative_id")
    chosen = next((item for item in package["alternatives"] if item["id"] == selected), None)
    if chosen is None:
        return []
    title = _bare(chosen["title"])
    alternative = f"{chosen['code']} {title}"
    visual = chosen.get("visual_language")
    product = _bare(visual["product_name"]) if isinstance(visual, Mapping) else ""
    if product and product.casefold() != title.casefold():
        alternative = texts["product"].format(alternative=alternative, product=product)
    return [texts["design"].format(alternative=alternative)]


def _overview_criteria(specification: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    count = len(specification["acceptance_criteria"])
    if not count:
        return []
    one, many = texts["criteria"]
    line = one if count == 1 else many
    return [line.format(criteria=counted(count, *texts["criterion_words"]))]


def overview_lines(
    *,
    language: str,
    project_name: str,
    brief: Mapping[str, object],
    twins: Mapping[str, object] | None = None,
    specification: Mapping[str, object] | None = None,
    package: Mapping[str, object] | None = None,
) -> list[str]:
    texts = _OVERVIEW_TEXTS[language]
    lines = [texts["heading"], "", _overview_project(project_name, brief, texts)]
    if twins is not None:
        lines.extend(_overview_twins(twins, texts))
    if specification is not None:
        lines.extend(_overview_must(specification, texts))
    if package is not None:
        lines.extend(_overview_design(package, texts))
    if specification is not None:
        lines.extend(_overview_criteria(specification, texts))
    return [*lines, ""]


def index_markdown(
    manifest: Mapping[str, object],
    *,
    overview: Sequence[str] = (),
    development: Sequence[str] = (),
) -> str:
    project = manifest["project"]
    package = manifest["package"]
    lines = [
        f"# OrchesTwin knowledge folder: {project['name']}",
        "",
        f"Knowledge folder version {package['version_number']} of project {project['id']}, "
        f"written on {package['created_at']} with folder schema version "
        f"{manifest['schema_version']}. Content hash `{package['content_hash']}`.",
        "",
        *overview,
        "## What this folder is",
        "",
        f"The approved steps of this project ({_STEP_NAMES}), each approved by the owner through "
        "a human gate in OrchesTwin Studio: a step comes into this folder once it is approved. "
        f"{progress_sentence(manifest)} The project is implemented outside the Studio: this "
        "folder travels with the source code and tells people and coding agents what has to be "
        "built and for whom.",
        "",
        "## How to use it",
        "",
        *_usage_lines(manifest),
        "",
        "## Approved stages",
        "",
        *markdown_table(
            ("Stage", "Text", "Exact snapshot", "Version", "Content hash", "Gate", "Approved at"),
            _stage_rows(manifest),
        ),
        "",
        *_twin_lines(manifest),
        *_views_lines(manifest),
        *_feedback_lines(manifest),
        *development,
        "## Schema",
        "",
        f"`{manifest['manifest']}` is the machine-readable index of this folder. Every JSON "
        "document is described by a JSON Schema:",
        "",
        *markdown_table(
            ("Document", "Schema"),
            ((name, f"`{path}`") for name, path in manifest["schemas"].items()),
        ),
        "",
        "## Files",
        "",
        f"`{manifest['manifest']}` holds the SHA-256 digest of every file of this folder except "
        "itself and this index: the Studio and `ut` check the files against those digests before "
        "they accept a folder.",
        "",
    ]
    return "\n".join(lines)
