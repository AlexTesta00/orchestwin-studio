from __future__ import annotations

from orchestwin.knowledge.documents_markdown import (
    _version_lines,
    markdown_bullets,
    plain_text,
    title_text,
)
from orchestwin.knowledge.layout import STAGE_LABELS
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.workflow.gates import HumanGate


def brief_markdown(version: ProjectBriefVersion, gate: HumanGate) -> str:
    snapshot = version.brief.to_snapshot()
    lines = _version_lines(STAGE_LABELS["brief"], version, gate)
    for key, value in snapshot["fields"].items():
        lines.extend([f"## {title_text(key)}", ""])
        if isinstance(value, list):
            lines.extend(markdown_bullets(value))
        else:
            lines.append(plain_text(value))
        lines.append("")
    lines.extend(
        ["## Fields marked as unknown", "", *markdown_bullets(snapshot["unknown_fields"]), ""]
    )
    return "\n".join(lines)
