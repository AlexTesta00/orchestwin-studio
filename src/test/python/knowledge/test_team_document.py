from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.perspectives import GuidanceStage, perspective_guidance
from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.agents.selection_rules import TeamRoleConstraintKind, determine_team_constraints
from orchestwin.knowledge.archive import verify_folder
from orchestwin.knowledge.documents import team_markdown
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.layout import STAGES, stage_text
from orchestwin.models.team_proposals import (
    ProposedTeamMember,
    TeamProposalMemberSource,
    deterministic_justification,
)
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.gates import HumanGate

from .knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_DATA,
    partial_sources,
    real_sources,
    sources,
)

TEAM_TEXT = stage_text("team")
FORBIDDEN = re.compile(
    r"\b(squadra|team|agente|agenti|agent|agents|assistente|assistenti|assistant|assistants|"
    r"specialista|specialisti|specialist|specialists|ruolo|ruoli|role|roles|membro|membri|"
    r"member|members)\b",
    re.IGNORECASE,
)
SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
IDENTITY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGEST = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
KEY = re.compile(r"\b[A-Z]{2,}(?:_[A-Z0-9]+)*\b")
INTRODUCTION = (
    "The perspectives are the competences through which this project is looked at. Each applied "
    "perspective adds its considerations when the requirements and the design alternatives are "
    "written."
)
NAMES = {
    "UX": "User experience (UX)",
    "ACCESSIBILITY": "Accessibility",
    "SOFTWARE_ENGINEERING": "Software engineering",
    "PRODUCT": "Product",
    "SECURITY": "Security",
}
LINES = {
    "UX": (
        "Looks at the project through the eyes of the people who will use it: goals, context, "
        "places where they may get stuck."
    ),
    "ACCESSIBILITY": (
        "Checks that everyone can use it: keyboard, contrast, readable text, clear messages."
    ),
    "SOFTWARE_ENGINEERING": (
        "Keeps the project feasible within its technical constraints, time and budget, and "
        "verifiable."
    ),
    "PRODUCT": "Keeps the priorities: what the first version needs and what can wait.",
    "SECURITY": "Protects data and access: who may see and do what.",
}
GUIDANCE_HEADINGS = (
    (GuidanceStage.DEFINITION, "In the definition:"),
    (GuidanceStage.DESIGN, "In the design:"),
)
CONTESTED_BRIEF = "Una app con database ma senza backend."
PASSWORD_REQUIREMENT = "Ogni volontario entra con una password."
COMPLETE_BRIEF = "Una web app con login e database, per telefono android, con un webhook."


def headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("#")]


def section(text: str, heading: str) -> str:
    rest = text.split(f"\n{heading}\n", 1)[1]
    ends = [rest.index(mark) for mark in ("\n### ", "\n## ") if mark in rest]
    return rest[: min(ends)] if ends else rest


def bullets(block: str, heading: str) -> list[str]:
    listed = block.split(f"\n{heading}\n", 1)[1].split("\n\n", 1)[0]
    return [line.removeprefix("- ") for line in listed.splitlines()]


def body(text: str) -> str:
    return "\n".join(text.splitlines()[3:])


def folder_text(package) -> str:
    built = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)
    return built.files[TEAM_TEXT]


def ruled_version(description: str, **fields: object) -> tuple[TeamProposalVersion, HumanGate]:
    package = sources()
    constraints = determine_team_constraints(
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        brief=create_project_brief(name="Lista ospiti", description=description, **fields),
    )
    members = tuple(
        ProposedTeamMember(
            agent_id=constraint.agent_id,
            source=TeamProposalMemberSource.DETERMINISTIC_MANDATORY,
            justifications=tuple(
                deterministic_justification(reason) for reason in constraint.reasons
            ),
        )
        for constraint in constraints.role_constraints
        if constraint.kind is TeamRoleConstraintKind.MANDATORY
    )
    proposal = replace(package.team.proposal, constraints=constraints, members=members)
    return replace(package.team, proposal=proposal), package.team_gate


def assert_guidance(text: str, version: TeamProposalVersion) -> None:
    selected = version.proposal.selected_agent_ids
    for stage, heading in GUIDANCE_HEADINGS:
        guidance = perspective_guidance(selected, stage)
        assert [NAMES[item["perspective"]] for item in guidance] == [
            line.removeprefix("### ") for line in headings(text) if line.startswith("### ")
        ]
        for item in guidance:
            block = section(text, f"### {NAMES[item['perspective']]}")
            assert bullets(block, heading) == item["considerations"]


def assert_plain(text: str) -> None:
    assert FORBIDDEN.search(text) is None
    assert SECOND_PERSON.search(text) is None
    assert IDENTITY.search(body(text)) is None
    assert DIGEST.search(body(text)) is None
    assert KEY.findall(body(text).replace("(UX)", "")) == []
    assert "|" not in text


def test_the_perspectives_of_the_fixture_say_what_applies_and_why() -> None:
    package = sources()

    text = folder_text(package)

    assert text.splitlines()[:5] == [
        "# Perspectives",
        "",
        f"Version 2, content hash `{package.team.content_hash}`, approved by the owner on "
        f"{package.team_gate.updated_at.isoformat()}.",
        "",
        INTRODUCTION,
    ]
    assert headings(text) == [
        "# Perspectives",
        "## Applied",
        "### User experience (UX)",
        "### Accessibility",
        "### Software engineering",
        "### Product",
        "## Not applied",
    ]
    for key in ("UX", "ACCESSIBILITY", "SOFTWARE_ENGINEERING", "PRODUCT"):
        assert section(text, f"### {NAMES[key]}").startswith(
            f"\n{LINES[key]}\n\nAlways applied.\n\n"
        )
    assert bullets(section(text, "### Software engineering"), "Applied aspects:") == [
        "Web interface: The brief asks for it (“browser”, “frontend”, “vue” in The idea, "
        "Technical constraints).",
        "Services and data: The brief asks for it (“backend”, “database”, “postgresql” in "
        "Technical constraints).",
        "Mobile: Applied, optional.",
    ]
    assert section(text, "## Not applied") == (
        "\n- Connections to other systems (aspect of software engineering): Optional.\n"
        "- Security: Optional.\n"
    )
    assert_guidance(text, package.team)
    assert_plain(text)


def test_a_proposal_stored_before_the_perspectives_gives_a_correct_view() -> None:
    stored = json.loads((REAL_PROJECT_DATA / "team.json").read_text(encoding="utf-8"))
    package = real_sources()

    text = folder_text(package)

    assert "perspectives" not in stored["proposal"]
    assert stored["proposal"]["constraints"]["role_constraints"][15]["kind"] == "OPTIONAL"
    assert text.splitlines()[2] == (
        "Version 1, content hash "
        "`a33b4badb0a16f53683c7bce63f2dbfe517bec709eadf734ccd7dc6a5114f884`, approved by the "
        "owner on 2026-09-27T18:02:00+00:00."
    )
    assert headings(text) == [
        "# Perspectives",
        "## Applied",
        "### User experience (UX)",
        "### Software engineering",
        "### Product",
        "## Not applied",
    ]
    assert "Applied aspects:" not in text
    assert bullets(section(text, "### Software engineering"), "In the definition:") == [
        "Keep every requirement feasible within the technical constraints, the time and the "
        "budget of the brief, and name as a risk what may not be.",
        "Write acceptance criteria that can be checked by using the application, each with one "
        "observable outcome.",
    ]
    assert section(text, "## Not applied").strip().splitlines() == [
        "- Accessibility: This version was prepared before this perspective became always applied.",
        "- Web interface (aspect of software engineering): Optional.",
        "- Services and data (aspect of software engineering): The brief rules it out "
        "(“nessun backend” in Technical constraints).",
        "- Mobile (aspect of software engineering): Optional.",
        "- Connections to other systems (aspect of software engineering): Optional.",
        "- Security: Optional.",
    ]
    assert_guidance(text, package.team)
    assert_plain(text)


def test_a_contradiction_of_the_brief_leaves_the_aspect_to_the_owner() -> None:
    version, gate = ruled_version(CONTESTED_BRIEF, functional_requirements=[PASSWORD_REQUIREMENT])

    text = team_markdown(version, gate)

    assert version.proposal.constraints.conflicting_agent_ids == (AgentIdentifier.BACKEND_ENGINEER,)
    assert headings(text) == [
        "# Perspectives",
        "## Applied",
        "### User experience (UX)",
        "### Accessibility",
        "### Software engineering",
        "### Product",
        "### Security",
        "## Not applied",
    ]
    assert section(text, "### Security").startswith(
        f"\n{LINES['SECURITY']}\n\nThe brief asks for it (“password” in What it must do).\n\n"
        "In the definition:\n"
    )
    assert section(text, "## Not applied").strip().splitlines() == [
        "- Web interface (aspect of software engineering): Optional.",
        "- Services and data (aspect of software engineering): The brief says two different "
        "things: the owner decides. It rules it out (“senza backend” in The idea) and also calls "
        "for it (“database” in The idea).",
        "- Mobile (aspect of software engineering): Optional.",
        "- Connections to other systems (aspect of software engineering): Optional.",
    ]
    assert_guidance(text, version)
    assert_plain(text)


def test_the_section_of_what_is_not_applied_is_left_out_when_everything_applies() -> None:
    version, gate = ruled_version(COMPLETE_BRIEF)

    text = team_markdown(version, gate)

    assert "## Not applied" not in text
    assert headings(text)[-1] == "### Security"
    assert bullets(section(text, "### Software engineering"), "Applied aspects:") == [
        "Web interface: The brief asks for it (“web app” in The idea).",
        "Services and data: The brief asks for it (“database”, “login” in The idea).",
        "Mobile: The brief asks for it (“android” in The idea).",
        "Connections to other systems: The brief asks for it (“webhook” in The idea).",
    ]
    assert len(bullets(section(text, "### Software engineering"), "In the design:")) == 6
    assert text.endswith("- Do not show sensitive data in full where a part is enough.\n")
    assert_guidance(text, version)
    assert_plain(text)


@pytest.mark.parametrize("through", STAGES[1:])
def test_folders_with_the_perspectives_still_verify(through: str) -> None:
    package = partial_sources(through)
    built = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    verified = verify_folder(built.files)

    assert verified.content_hash == built.content_hash
    assert verified.present_stages == package.present_stages
    assert verified.files[TEAM_TEXT].startswith("# Perspectives\n\nVersion 1, content hash `")
