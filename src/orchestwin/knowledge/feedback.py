from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from orchestwin.knowledge.documents import (
    UNSET,
    feedback_counts,
    markdown_bullets,
    markdown_table,
    title_text,
)
from orchestwin.knowledge.layout import (
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_INSIGHTS,
    FEEDBACK_REVIEWS,
    KNOWLEDGE_SCHEMA_VERSION,
)
from orchestwin.knowledge.sources import KnowledgeSources

REVIEWS_KIND: Final = "orchestwin.twin-reviews"
DISCUSSIONS_KIND: Final = "orchestwin.twin-discussions"
INSIGHTS_KIND: Final = "orchestwin.insight-applications"
_DECISIONS: Final = {
    "OWNER_CONFIRMED": "confirmed by the owner",
    "OWNER_DISMISSED": "dismissed by the owner",
}
_UNDECIDED: Final = "not decided"


def _design_reference(sources: KnowledgeSources) -> dict[str, object]:
    return {
        "version_id": str(sources.design.id),
        "version_number": sources.design.version_number,
        "content_hash": sources.design.content_hash,
    }


def feedback_documents(sources: KnowledgeSources) -> dict[str, dict[str, object]]:
    feedback = sources.feedback
    project_id = str(sources.project_id)
    return {
        FEEDBACK_REVIEWS: {
            "schema_version": KNOWLEDGE_SCHEMA_VERSION,
            "kind": REVIEWS_KIND,
            "project_id": project_id,
            "design": _design_reference(sources),
            "runs": [item.to_snapshot() for item in feedback.runs],
            "decisions": [item.to_snapshot() for item in feedback.validations],
        },
        FEEDBACK_DISCUSSIONS: {
            "schema_version": KNOWLEDGE_SCHEMA_VERSION,
            "kind": DISCUSSIONS_KIND,
            "project_id": project_id,
            "design": _design_reference(sources),
            "discussions": [item.to_snapshot() for item in feedback.discussions],
        },
        FEEDBACK_INSIGHTS: {
            "schema_version": KNOWLEDGE_SCHEMA_VERSION,
            "kind": INSIGHTS_KIND,
            "project_id": project_id,
            "applications": [item.to_snapshot() for item in feedback.applications],
        },
    }


def feedback_summary(sources: KnowledgeSources) -> dict[str, int]:
    feedback = sources.feedback
    return {
        "reviews": len(feedback.runs),
        "findings": sum(len(item.findings) for item in feedback.runs),
        "decisions": len(current_decisions(sources)),
        "discussions": len(feedback.discussions),
        "insights": len(feedback.applications),
    }


def current_decisions(sources: KnowledgeSources) -> dict[tuple[str, str, str], Mapping]:
    decisions: dict[tuple[str, str, str], Mapping] = {}
    for validation in sources.feedback.validations:
        snapshot = validation.to_snapshot()
        key = (snapshot["evaluation_run_id"], snapshot["twin_id"], snapshot["finding_id"])
        known = decisions.get(key)
        if known is None or known["sequence_number"] < snapshot["sequence_number"]:
            decisions[key] = snapshot
    return decisions


def twin_names(sources: KnowledgeSources) -> dict[str, str]:
    return {
        str(version.twin_id): version.profile.name
        for version in sources.modeling.snapshot.twin_versions
    }


def _scope(item: Mapping[str, object], sources: KnowledgeSources) -> str:
    exported = (
        "the design approved in this folder"
        if item["design_content_hash"] == sources.design.content_hash
        else "an earlier design"
    )
    return (
        f"design version {item['design_version_number']}, alternative "
        f"{item['alternative_code']} ({exported})"
    )


def _decision(decision: Mapping[str, object] | None) -> str:
    if decision is None:
        return _UNDECIDED
    text = _DECISIONS.get(str(decision["decision"]), str(decision["decision"]))
    return text if not decision["note"] else f"{text}: {decision['note']}"


def _review_lines(sources: KnowledgeSources) -> list[str]:
    names = twin_names(sources)
    decisions = current_decisions(sources)
    lines = ["## Reviews", ""]
    for run in sources.feedback.runs:
        snapshot = run.to_snapshot()
        evaluator = snapshot["responses"][0]["evaluator"]
        lines.extend(
            [
                f"### Review of {_scope(snapshot, sources)}",
                "",
                f"Run {snapshot['id']}, completed on {snapshot['completed_at']}, evaluator "
                f"{evaluator['evaluator_id']} {evaluator['evaluator_version']}, prompt "
                f"{evaluator['prompt_version_ref']}.",
                "",
            ]
        )
        for response in snapshot["responses"]:
            twin = str(response["twin_id"])
            lines.extend(
                [
                    f"#### {names.get(twin, twin)}",
                    "",
                    str(response["summary"]),
                    "",
                    *markdown_table(
                        (
                            "Finding",
                            "Severity",
                            "Criterion",
                            "Location",
                            "Summary",
                            "Recommended action",
                            "Owner decision",
                        ),
                        (
                            (
                                finding["finding_id"],
                                finding["severity"],
                                title_text(finding["criterion"]),
                                finding["location"],
                                finding["summary"],
                                finding["recommended_action"],
                                _decision(
                                    decisions.get((snapshot["id"], twin, finding["finding_id"]))
                                ),
                            )
                            for finding in response["findings"]
                        ),
                    ),
                    "",
                    "Evidence gaps:",
                    *markdown_bullets(response["evidence_gaps"]),
                    "",
                ]
            )
    if not sources.feedback.runs:
        lines.extend([f"{UNSET}.", ""])
    return lines


def _round_lines(round_: Mapping[str, object], names: Mapping[str, str]) -> list[str]:
    lines = [f"#### Round {round_['ordinal']}", ""]
    if round_["owner_note"]:
        lines.extend([f"Owner's note: {round_['owner_note']}", ""])
    for statement in round_["statements"]:
        lines.append(
            f"- {statement['twin_name']} ({title_text(statement['stance'])}): "
            f"{statement['statement']}"
        )
        if statement.get("answer_to_owner"):
            lines.append(f"  - Answer to the owner: {statement['answer_to_owner']}")
        lines.extend(
            f"  - To {names.get(str(reaction['twin_id']), reaction['twin_id'])} "
            f"({title_text(reaction['verdict'])}): {reaction['reason']}"
            for reaction in statement.get("reactions", ())
        )
        lines.extend(f"  - Proposal: {proposal}" for proposal in statement["proposals"])
    synthesis = round_["synthesis"]
    lines.extend(["", "Agreements:", *markdown_bullets(synthesis["agreements"]), ""])
    lines.append("Conflicts:")
    for conflict in synthesis["conflicts"]:
        lines.append(f"- {conflict['topic']}")
        lines.extend(
            f"  - {names.get(str(position['twin_id']), position['twin_id'])}: "
            f"{position['position']}"
            for position in conflict["positions"]
        )
    if not synthesis["conflicts"]:
        lines.append(f"- {UNSET}")
    lines.extend(["", "Proposals:"])
    lines.extend(
        f"- {proposal['code']} for the {title_text(proposal['target']).lower()}: "
        f"{proposal['text']} (supported by "
        f"{', '.join(names.get(str(twin), str(twin)) for twin in proposal['supported_by'])})"
        for proposal in synthesis["proposals"]
    )
    if not synthesis["proposals"]:
        lines.append(f"- {UNSET}")
    lines.extend(
        ["", "Questions for the owner:", *markdown_bullets(synthesis["questions_for_owner"]), ""]
    )
    return lines


def _speakers(discussion: Mapping[str, object]) -> dict[str, str]:
    return {
        str(statement["twin_id"]): str(statement["twin_name"])
        for round_ in discussion["rounds"]
        for statement in round_["statements"]
    }


def _discussion_lines(sources: KnowledgeSources) -> list[str]:
    known = twin_names(sources)
    lines = ["## Approved discussions", ""]
    for discussion in sources.feedback.discussions:
        snapshot = discussion.to_snapshot()
        names = {**_speakers(snapshot), **known}
        lines.extend(
            [
                f"### Discussion on {_scope(snapshot, sources)}",
                "",
                f"Discussion {snapshot['id']}, approved on {snapshot['decided_at']}.",
                "",
            ]
        )
        for round_ in snapshot["rounds"]:
            lines.extend(_round_lines(round_, names))
    if not sources.feedback.discussions:
        lines.extend([f"{UNSET}.", ""])
    return lines


def _insight_lines(sources: KnowledgeSources) -> list[str]:
    names = twin_names(sources)
    rows = []
    for application in sources.feedback.applications:
        snapshot = application.to_snapshot()
        twin = snapshot["source_twin_id"]
        rows.append(
            (
                snapshot["created_at"],
                title_text(snapshot["source_kind"]),
                None if twin is None else names.get(str(twin), twin),
                f"{title_text(snapshot['target'])} v{snapshot['target_version_number']}",
                snapshot["target_code"] or snapshot["target_field"],
                snapshot["text"],
            )
        )
    return [
        "## Applied insights",
        "",
        *markdown_table(("Applied on", "Source", "Twin", "Target", "Item", "Text"), rows),
        "",
    ]


def feedback_markdown(sources: KnowledgeSources) -> str:
    counts = feedback_summary(sources)
    lines = [
        "# Twin feedback",
        "",
        "History of the simulated feedback that the user twins gave on the design inside the "
        "Studio. Every finding and every statement is a model inference about a modelled user: "
        "it becomes a fact of the project only through the owner's decision recorded next to it.",
        "",
        f"This folder holds {feedback_counts(counts)}.",
        "",
        *_review_lines(sources),
        *_discussion_lines(sources),
        *_insight_lines(sources),
    ]
    return "\n".join(lines)


__all__ = [
    "DISCUSSIONS_KIND",
    "INSIGHTS_KIND",
    "REVIEWS_KIND",
    "current_decisions",
    "feedback_documents",
    "feedback_markdown",
    "feedback_summary",
    "twin_names",
]
