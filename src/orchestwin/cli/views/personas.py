from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli.flows.twin_selection import observation_values

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

PERSONA_FIELDS = {
    "description": "description",
    "goals": "goals",
    "needs": "information_needs",
    "behaviours": "recurring_tasks",
    "pain_points": "pain_points",
    "constraints": "operational_constraints",
    "contexts": "context_of_use",
}
STATUSES = ("EVIDENCED", "INFERRED", "HYPOTHESIZED", "CONTESTED", "UNKNOWN")
DECLARATION_FIELDS = ("represents", "does_not_represent", "contexts", "evidence_gaps")


def display_status(observation: Mapping[str, object]) -> str:
    value = observation.get("value")
    if not isinstance(value, Mapping) or value.get("kind") in {"UNKNOWN", "ABSTAINED"}:
        return "UNKNOWN"
    status = observation.get("epistemic_status")
    if status in {"CONTESTED", "MODEL_INFERRED", "UNSUPPORTED_ASSUMPTION"}:
        return {
            "CONTESTED": "CONTESTED",
            "MODEL_INFERRED": "INFERRED",
            "UNSUPPORTED_ASSUMPTION": "HYPOTHESIZED",
        }[status]
    empirical = any(
        isinstance(item, Mapping) and item.get("source_kind") == "EMPIRICAL_RESEARCH"
        for item in observation.get("provenance") or ()
    )
    return (
        "EVIDENCED"
        if empirical and status in {"EMPIRICALLY_SUPPORTED", "HUMAN_VALIDATED"}
        else "HYPOTHESIZED"
    )


def view_of(
    version: Mapping[str, object], persona: Mapping[str, object] | None = None
) -> Mapping[str, object]:
    supplied = version.get("view")
    if isinstance(supplied, Mapping):
        return supplied
    profile = version.get("profile") or {}
    observations = {
        str(item.get("observation_key")): item for item in profile.get("observations") or ()
    }
    reference = profile.get("persona_reference") or {}
    if (
        persona is not None
        and persona.get("project_id") == version.get("project_id")
        and all(
            persona.get(key) == reference.get(key)
            for key in ("persona_id", "version_number", "content_hash")
        )
    ):
        summary = next(
            (
                item
                for item in persona.get("profile", {}).get("observations", ())
                if item.get("observation_key") == "persona.summary"
            ),
            None,
        )
        if summary is not None and "user_twin.description" not in observations:
            observations["user_twin.description"] = summary

    def claim(field):
        item = observations.get(f"user_twin.{field}") or {}
        return {
            "observation_key": f"user_twin.{field}",
            "value": item.get("value")
            or {"kind": "UNKNOWN", "text": None, "items": [], "reason": None},
            "display_status": display_status(item),
            "rationale": item.get("rationale"),
            "provenance": item.get("provenance") or [],
        }

    return {
        "basis": "PROVISIONAL",
        **{
            field: claim(source)
            for field, source in {
                "represents": "represents",
                "does_not_represent": "does_not_represent",
                "contexts": "context_of_use",
                "evidence_gaps": "evidence_gaps",
            }.items()
        },
        "empirically_supported_fields": [],
        "unsupported_fields": [
            key.removeprefix("user_twin.")
            for key, item in observations.items()
            if display_status(item) != "EVIDENCED"
        ],
        "persona": {field: claim(source) for field, source in PERSONA_FIELDS.items()},
    }


def show_claim(
    context: CommandContext, field: str, claim: Mapping[str, object], *, why: bool = False
) -> None:
    values = observation_values(claim)
    value = "; ".join(values) if values else context.text("twins.status_unknown")
    status = str(claim.get("display_status") or "UNKNOWN").lower()
    context.console.write(
        f"{context.text(f'twins.persona_{field}')}: {value} [{context.text(f'twins.status_{status}')}]"
    )
    if why:
        context.console.say("twins.why")
        context.console.write(str(claim.get("rationale") or context.text("twins.no_rationale")))
        sources = claim.get("provenance") or ()
        if not sources:
            context.console.say("twins.no_sources")
        for source in sources:
            context.console.write(
                " · ".join(
                    str(source[key])
                    for key in (
                        "source_kind",
                        "source_id",
                        "source_version",
                        "content_hash",
                        "locator",
                        "summary",
                    )
                    if source.get(key) is not None
                )
            )


def show_declaration(context: CommandContext, view: Mapping[str, object]) -> None:
    context.console.say(
        "twins.basis",
        basis=context.text("twins.basis_" + str(view.get("basis", "PROVISIONAL")).lower()),
    )
    if view.get("basis") == "PROVISIONAL":
        context.console.say("twins.provisional_note")
    for field in DECLARATION_FIELDS:
        show_claim(context, field, view.get(field) or {})


def views_of(snapshot: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    payload = snapshot.get("snapshot") or {}
    result = {}
    for version in payload.get("twin_versions") or ():
        reference = version.get("profile", {}).get("persona_reference") or {}
        persona = next(
            (
                item
                for item in payload.get("persona_versions") or ()
                if all(
                    item.get(key) == reference.get(key)
                    for key in ("persona_id", "version_number", "content_hash")
                )
            ),
            None,
        )
        result[str(version.get("twin_id"))] = view_of(version, persona)
    return result


def show(
    context: CommandContext, name: str, view: Mapping[str, object], *, why: str | None = None
) -> None:
    context.console.heading(context.text("twins.persona_heading", name=name))
    if why is None:
        show_declaration(context, view)
    else:
        context.console.say(
            "twins.basis",
            basis=context.text("twins.basis_" + str(view.get("basis", "PROVISIONAL")).lower()),
        )
        if view.get("basis") == "PROVISIONAL":
            context.console.say("twins.provisional_note")
    persona = view.get("persona") or {}
    for field in PERSONA_FIELDS if why is None else (why,):
        show_claim(context, field, persona.get(field) or {}, why=why is not None)
