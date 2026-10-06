from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.knowledge_alignment import (
    MAX_ANY_REQUEST_LENGTH,
    MAX_COMMITS,
    MAX_CONTEXT_DIFF_TOTAL,
    MAX_EXCERPT_LENGTH,
    MAX_EXCERPT_LINES,
    MAX_NOTE_LENGTH,
    MAX_ORIGIN_FILES,
    MAX_PROPOSALS,
    MAX_PROPOSALS_PER_SECTION,
    MAX_RATIONALE_LENGTH,
    MAX_REQUEST_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    PROPOSAL_CODE_PATTERN,
    AlignmentProposal,
    KnowledgeAlignmentRun,
    ProposalAlreadyDecided,
    ProposalOrigin,
    ProposalSection,
    ProposalStatus,
    ProposalSubjects,
    ProposedUpdate,
    create_proposed_update,
    create_run,
    normalize_commits,
    normalize_excerpt,
    normalize_files,
    normalize_note,
    normalize_request,
    proposal_code,
    proposal_from_snapshot,
    proposal_number,
    run_from_snapshot,
    waiting_proposals,
)
from src.test.python.artifacts import design_fixtures

PROJECT = design_fixtures.PROJECT_ID
OWNER = design_fixtures.OWNER_ID
RUN_ID = UUID("00000000-0000-4000-8000-000000000a20")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000a30")
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
EXCERPT = "-const guests = [];\n+const guests = load();"
TITLE = "Registrare la data di arrivo"
REQUEST = "Aggiungere il requisito della data di arrivo degli ospiti alla prenotazione."
RATIONALE = "Il diff salva la data di arrivo che la Definizione non nomina."
SUMMARY = "Il codice salva la data di arrivo degli ospiti, che la Definizione non prevede."
PROPOSAL_KEYS = [
    "id",
    "run_id",
    "code",
    "section",
    "title",
    "request",
    "rationale",
    "subjects",
    "origin",
    "status",
    "created_at",
    "decided_at",
    "decision_note",
    "applied_text",
    "applied_diff_id",
]
RUN_KEYS = [
    "id",
    "project_id",
    "from_commit",
    "to_commit",
    "commits",
    "locale",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
    "created_at",
    "cost_microusd",
    "generation_ids",
    "proposals",
]


def origin(**values):
    arguments = {"commits": (FIRST,), "files": ("src/app.js",), "excerpt": EXCERPT}
    arguments.update(values)
    return ProposalOrigin(**arguments)


def subjects(**values):
    arguments = {"requirements": ("REQ-001",), "screens": ("SCR-001",), "criteria": ("AC-001",)}
    arguments.update(values)
    return ProposalSubjects(**arguments)


def update(section=ProposalSection.REQUIREMENTS, **values):
    arguments = {
        "section": section,
        "title": TITLE,
        "request": REQUEST,
        "rationale": RATIONALE,
        "subjects": subjects(),
        "origin": origin(),
    }
    arguments.update(values)
    return ProposedUpdate(**arguments)


def proposal(number=1, **values):
    arguments = {
        "id": UUID(int=0xA100 + number),
        "run_id": RUN_ID,
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "number": number,
        "section": ProposalSection.REQUIREMENTS,
        "title": TITLE,
        "request": REQUEST,
        "rationale": RATIONALE,
        "subjects": subjects(),
        "origin": origin(),
        "status": ProposalStatus.PROPOSED,
        "created_at": NOW,
    }
    arguments.update(values)
    return AlignmentProposal(**arguments)


def alignment_run(**values):
    arguments = {
        "id": RUN_ID,
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "from_commit": None,
        "to_commit": SECOND,
        "commits": (FIRST, SECOND),
        "locale": "it-IT",
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
        "summary": SUMMARY,
        "created_at": NOW,
        "cost_microusd": 250_000,
        "generation_ids": (UUID(int=0xE201),),
        "proposals": (proposal(1), proposal(2, section=ProposalSection.DESIGN)),
    }
    arguments.update(values)
    return KnowledgeAlignmentRun(**arguments)


def updates(count, section=ProposalSection.REQUIREMENTS):
    return [update(section, title=f"{TITLE} {index}") for index in range(count)]


def test_the_enumerations_and_the_limits_follow_the_contract():
    assert tuple(item.value for item in ProposalSection) == ("REQUIREMENTS", "DESIGN", "TESTS")
    assert tuple(item.value for item in ProposalStatus) == ("PROPOSED", "APPLIED", "SKIPPED")
    assert (MAX_PROPOSALS, MAX_PROPOSALS_PER_SECTION, MAX_TITLE_LENGTH) == (12, 6, 200)
    assert dict(MAX_REQUEST_LENGTH) == {
        ProposalSection.REQUIREMENTS: 2000,
        ProposalSection.DESIGN: 1000,
        ProposalSection.TESTS: 600,
    }
    assert MAX_REQUEST_LENGTH["TESTS"] == 600
    assert MAX_ANY_REQUEST_LENGTH == 2000
    assert (MAX_RATIONALE_LENGTH, MAX_SUMMARY_LENGTH, MAX_EXCERPT_LENGTH) == (400, 600, 1500)
    assert (MAX_EXCERPT_LINES, MAX_ORIGIN_FILES, MAX_NOTE_LENGTH, MAX_COMMITS) == (15, 20, 300, 50)
    assert MAX_CONTEXT_DIFF_TOTAL == 96_000
    assert PROPOSAL_CODE_PATTERN == r"^ALN-[0-9]{3,6}$"


@pytest.mark.parametrize(
    ("number", "code"),
    [(1, "ALN-001"), (42, "ALN-042"), (999, "ALN-999"), (1000, "ALN-1000"), (999999, "ALN-999999")],
)
def test_proposal_codes_follow_the_number_and_read_back(number, code):
    assert proposal_code(number) == code
    assert proposal_number(code) == number
    assert proposal_number(code.lower()) == number


@pytest.mark.parametrize("number", [0, -1, 1000000, True, "1"])
def test_a_proposal_number_outside_the_range_is_refused(number):
    with pytest.raises(ValueError):
        proposal_code(number)


@pytest.mark.parametrize("code", ["ALN-01", "ALN-0001", "TSK-001", "ALN-1234567", None, 1, "ALN-"])
def test_an_unknown_proposal_code_reads_as_none(code):
    assert proposal_number(code) is None


def test_the_excerpt_keeps_its_lines_and_drops_only_the_blank_edges():
    assert normalize_excerpt("\n\n  -old  \r\n+new\n\n") == "  -old\n+new"
    assert normalize_excerpt("x" * MAX_EXCERPT_LENGTH) == "x" * MAX_EXCERPT_LENGTH
    assert normalize_excerpt("\n".join(["a"] * MAX_EXCERPT_LINES)) == "\n".join(["a"] * 15)
    for value in (
        "",
        "   \n  ",
        "a\x00b",
        "\n".join(["a"] * (MAX_EXCERPT_LINES + 1)),
        "x" * (MAX_EXCERPT_LENGTH + 1),
        None,
        ["-old"],
    ):
        with pytest.raises(ValueError):
            normalize_excerpt(value)


def test_the_request_limit_depends_on_the_section():
    long = "x" * 1001
    assert normalize_request(f"  {long}\n", ProposalSection.REQUIREMENTS) == long
    with pytest.raises(ValueError, match="design request exceeds 1000"):
        normalize_request(long, ProposalSection.DESIGN)
    with pytest.raises(ValueError, match="tests request exceeds 600"):
        normalize_request("x" * 601, ProposalSection.TESTS)
    with pytest.raises(ValueError):
        normalize_request("   ", ProposalSection.TESTS)
    with pytest.raises(ValueError):
        normalize_request("x" * 2001, ProposalSection.REQUIREMENTS)


def test_notes_commits_and_files_are_normalized_and_bounded():
    assert normalize_note(None) is None
    assert normalize_note("   ") is None
    assert normalize_note("  Non serve.  ") == "Non serve."
    with pytest.raises(ValueError):
        normalize_note("x" * (MAX_NOTE_LENGTH + 1))
    with pytest.raises(ValueError):
        normalize_note(3)
    assert normalize_commits(["A" * 40, FIRST]) == ("a" * 40, FIRST)
    for commits in ([], [FIRST] * 2, [f"{index:040x}" for index in range(51)], FIRST, ["xyz"]):
        with pytest.raises(ValueError):
            normalize_commits(commits)
    assert normalize_files(["src/app.js", "src/b.js"]) == ("src/app.js", "src/b.js")
    for files in ([], ["src/app.js"] * 2, [f"src/{index}.js" for index in range(21)], "src/a.js"):
        with pytest.raises(ValueError):
            normalize_files(files)


def test_subjects_and_origin_are_validated_and_round_trip_through_snapshots():
    assert subjects().to_snapshot() == {
        "requirements": ["REQ-001"],
        "screens": ["SCR-001"],
        "criteria": ["AC-001"],
    }
    assert ProposalSubjects().to_snapshot() == {"requirements": [], "screens": [], "criteria": []}
    for values in (
        {"requirements": ("REQ-1",)},
        {"screens": ("REQ-001",)},
        {"criteria": ("AC-001", "AC-001")},
        {"requirements": ["REQ-001"]},
    ):
        with pytest.raises(ValueError):
            subjects(**values)
    assert origin().to_snapshot() == {
        "commits": [FIRST],
        "files": ["src/app.js"],
        "excerpt": EXCERPT,
    }
    for values in (
        {"commits": ("1" * 6,)},
        {"commits": [FIRST]},
        {"files": ()},
        {"files": ("src/app.js", "src/app.js")},
        {"excerpt": ""},
        {"excerpt": f"{EXCERPT}\n"},
    ):
        with pytest.raises(ValueError):
            origin(**values)


def test_a_proposed_update_is_normalized_by_its_factory_and_checked_by_its_class():
    created = create_proposed_update(
        section="DESIGN",
        title="  Mostrare   la data  ",
        request=f"\n{REQUEST}\n",
        rationale=f" {RATIONALE} ",
        origin=origin(),
    )
    assert created.section is ProposalSection.DESIGN
    assert (created.title, created.request, created.rationale) == (
        "Mostrare la data",
        REQUEST,
        RATIONALE,
    )
    assert created.subjects == ProposalSubjects()
    for values in (
        {"section": "DESIGN"},
        {"title": "  x"},
        {"request": "x" * 2001},
        {"rationale": "x" * 401},
        {"subjects": {"requirements": []}},
        {"origin": None},
    ):
        with pytest.raises(ValueError):
            update(**values)
    with pytest.raises(ValueError):
        update(ProposalSection.TESTS, request="x" * 601)


def test_a_proposal_carries_a_decision_only_when_it_is_decided():
    waiting = proposal()
    assert waiting.code == "ALN-001"
    assert waiting.waiting is True
    for values in (
        {"decided_at": LATER},
        {"status": ProposalStatus.APPLIED},
        {"decision_note": "Nota."},
        {"applied_text": REQUEST},
        {"applied_diff_id": DIFF_ID},
        {"status": ProposalStatus.SKIPPED, "decided_at": LATER, "applied_text": REQUEST},
        {"status": ProposalStatus.SKIPPED, "decided_at": LATER, "applied_diff_id": DIFF_ID},
        {"status": ProposalStatus.APPLIED, "decided_at": LATER, "applied_text": " x "},
        {"status": ProposalStatus.APPLIED, "decided_at": datetime(2026, 10, 6)},
        {"status": "APPLIED", "decided_at": LATER},
        {"number": 0},
        {"created_at": datetime(2026, 10, 6)},
        {"run_id": str(RUN_ID)},
    ):
        with pytest.raises(ValueError):
            proposal(**values)
    applied = proposal(
        status=ProposalStatus.APPLIED,
        decided_at=LATER,
        decision_note="Testo rivisto.",
        applied_text=REQUEST,
        applied_diff_id=DIFF_ID,
    )
    assert applied.waiting is False


def test_with_decision_applies_or_skips_once():
    applied = proposal().with_decision(
        status=ProposalStatus.APPLIED,
        decided_at=LATER,
        note="  ",
        applied_text=f" {REQUEST} ",
        applied_diff_id=DIFF_ID,
    )
    assert (applied.status, applied.decided_at, applied.decision_note) == (
        ProposalStatus.APPLIED,
        LATER,
        None,
    )
    assert (applied.applied_text, applied.applied_diff_id) == (REQUEST, DIFF_ID)
    skipped = proposal().with_decision(
        status=ProposalStatus.SKIPPED, decided_at=LATER, note="Non riguarda la Definizione."
    )
    assert (skipped.status, skipped.decision_note) == (
        ProposalStatus.SKIPPED,
        "Non riguarda la Definizione.",
    )
    assert (skipped.applied_text, skipped.applied_diff_id) == (None, None)
    with pytest.raises(ValueError):
        proposal().with_decision(status=ProposalStatus.PROPOSED, decided_at=LATER)
    with pytest.raises(ValueError):
        proposal().with_decision(
            status=ProposalStatus.SKIPPED, decided_at=LATER, applied_text=REQUEST
        )
    with pytest.raises(ValueError):
        proposal().with_decision(status="APPLIED", decided_at=LATER)
    with pytest.raises(ValueError):
        proposal(section=ProposalSection.TESTS).with_decision(
            status=ProposalStatus.APPLIED, decided_at=LATER, applied_text="x" * 601
        )
    for decided in (applied, skipped):
        with pytest.raises(ProposalAlreadyDecided) as refused:
            decided.with_decision(status=ProposalStatus.SKIPPED, decided_at=LATER)
        assert (refused.value.proposal, refused.value.status) == ("ALN-001", decided.status)


def test_the_proposal_snapshot_has_the_keys_of_the_contract_and_reads_back():
    applied = proposal(
        status=ProposalStatus.APPLIED,
        decided_at=LATER,
        decision_note="Testo rivisto.",
        applied_text=REQUEST,
        applied_diff_id=DIFF_ID,
    )
    snapshot = applied.to_snapshot()
    assert list(snapshot) == PROPOSAL_KEYS
    assert snapshot["code"] == "ALN-001"
    assert snapshot["section"] == "REQUIREMENTS"
    assert snapshot["subjects"] == subjects().to_snapshot()
    assert snapshot["origin"] == origin().to_snapshot()
    assert snapshot["status"] == "APPLIED"
    assert snapshot["created_at"] == "2026-10-06T09:00:00+00:00"
    assert snapshot["decided_at"] == "2026-10-06T10:00:00+00:00"
    assert snapshot["applied_diff_id"] == str(DIFF_ID)
    assert proposal_from_snapshot(snapshot, project_id=PROJECT, owner_user_id=OWNER) == applied
    placeholder = proposal_from_snapshot(proposal().to_snapshot())
    assert (placeholder.project_id, placeholder.owner_user_id) == (UUID(int=0), UUID(int=0))
    assert placeholder.decided_at is None
    with pytest.raises(ValueError):
        proposal_from_snapshot({**snapshot, "code": "ALN-01"})


def test_a_run_ends_with_its_last_commit_and_starts_before_the_first():
    run = alignment_run()
    assert run.waiting == run.proposals
    assert run.reference_snapshot() == {
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
    }
    assert alignment_run(from_commit=THIRD).from_commit == THIRD
    for values in (
        {"to_commit": FIRST},
        {"commits": (FIRST, "a" * 40), "to_commit": "A" * 40},
        {"from_commit": FIRST},
        {"from_commit": "abc"},
        {"commits": (FIRST, SECOND, FIRST)},
        {"commits": [FIRST, SECOND]},
        {"locale": "italiano"},
        {"alternative_code": "DES-1"},
        {"requirements_version_number": 0},
        {"design_version_number": True},
        {"summary": "x" * 601},
        {"summary": " spazi "},
        {"cost_microusd": -1},
        {"generation_ids": (UUID(int=1), UUID(int=1))},
        {"created_at": datetime(2026, 10, 6)},
        {"proposals": (proposal(1), proposal(1))},
        {"proposals": (proposal(2), proposal(1))},
        {"proposals": (proposal(1, run_id=UUID(int=9)),)},
        {"proposals": (proposal(1, project_id=UUID(int=9)),)},
        {"proposals": [proposal(1)]},
    ):
        with pytest.raises(ValueError):
            alignment_run(**values)


def test_a_run_holds_at_most_twelve_proposals_and_six_per_section():
    many = tuple(
        proposal(index + 1, section=section)
        for index, section in enumerate(
            [ProposalSection.REQUIREMENTS] * 6 + [ProposalSection.DESIGN] * 6
        )
    )
    assert len(alignment_run(proposals=many).proposals) == MAX_PROPOSALS
    with pytest.raises(ValueError, match="at most 12 proposals"):
        alignment_run(proposals=(*many, proposal(13, section=ProposalSection.TESTS)))
    seven = tuple(proposal(index + 1, section=ProposalSection.TESTS) for index in range(7))
    with pytest.raises(ValueError, match="per section"):
        alignment_run(proposals=seven)


def test_create_run_numbers_the_proposals_and_takes_the_last_commit_as_the_end():
    run = create_run(
        project_id=PROJECT,
        owner_user_id=OWNER,
        from_commit=THIRD.upper(),
        commits=[FIRST.upper(), SECOND],
        locale="it-IT",
        requirements_version_number=2,
        design_version_number=3,
        alternative_code="DES-002",
        summary=f"  {SUMMARY}  ",
        created_at=NOW,
        proposals=[update(), update(ProposalSection.TESTS), update(ProposalSection.DESIGN)],
        cost_microusd=10,
        generation_ids=[UUID(int=0xE201)],
        run_id=RUN_ID,
        first_number=7,
    )
    assert (run.id, run.from_commit, run.to_commit, run.commits) == (
        RUN_ID,
        THIRD,
        SECOND,
        (FIRST, SECOND),
    )
    assert run.summary == SUMMARY
    assert run.generation_ids == (UUID(int=0xE201),)
    assert [item.code for item in run.proposals] == ["ALN-007", "ALN-008", "ALN-009"]
    assert [item.section for item in run.proposals] == [
        ProposalSection.REQUIREMENTS,
        ProposalSection.TESTS,
        ProposalSection.DESIGN,
    ]
    assert all(item.run_id == RUN_ID and item.created_at == NOW for item in run.proposals)
    assert all(item.status is ProposalStatus.PROPOSED for item in run.proposals)
    assert len({item.id for item in run.proposals}) == 3
    assert run.waiting == run.proposals
    renumbered = run.renumbered(20)
    assert [item.code for item in renumbered.proposals] == ["ALN-020", "ALN-021", "ALN-022"]
    assert [item.id for item in renumbered.proposals] == [item.id for item in run.proposals]
    explicit = create_run(
        project_id=PROJECT,
        owner_user_id=OWNER,
        from_commit=None,
        to_commit=SECOND,
        commits=(FIRST, SECOND),
        locale="en-US",
        requirements_version_number=1,
        design_version_number=1,
        alternative_code="DES-001",
        summary=SUMMARY,
        created_at=NOW,
        proposals=(),
    )
    assert (explicit.to_commit, explicit.proposals, explicit.waiting) == (SECOND, (), ())
    assert explicit.id != RUN_ID
    with pytest.raises(ValueError):
        create_run(
            project_id=PROJECT,
            owner_user_id=OWNER,
            from_commit=None,
            commits=(FIRST, SECOND),
            locale="it-IT",
            requirements_version_number=1,
            design_version_number=1,
            alternative_code="DES-001",
            summary=SUMMARY,
            created_at=NOW,
            proposals=[proposal()],
        )
    with pytest.raises(ValueError):
        create_run(
            project_id=PROJECT,
            owner_user_id=OWNER,
            from_commit=None,
            commits=(FIRST, SECOND),
            locale="it-IT",
            requirements_version_number=1,
            design_version_number=1,
            alternative_code="DES-001",
            summary=SUMMARY,
            created_at=NOW,
            proposals=updates(7),
        )


def test_the_run_snapshot_has_the_keys_of_the_contract_and_reads_back():
    run = alignment_run(
        proposals=(
            proposal(1),
            proposal(2, section=ProposalSection.DESIGN).with_decision(
                status=ProposalStatus.SKIPPED, decided_at=LATER, note="Più tardi."
            ),
        )
    )
    snapshot = run.to_snapshot()
    assert list(snapshot) == RUN_KEYS
    assert snapshot["project_id"] == str(PROJECT)
    assert snapshot["commits"] == [FIRST, SECOND]
    assert snapshot["generation_ids"] == [str(UUID(int=0xE201))]
    assert [list(item) for item in snapshot["proposals"]] == [PROPOSAL_KEYS, PROPOSAL_KEYS]
    assert snapshot["proposals"][1]["status"] == "SKIPPED"
    assert run_from_snapshot(snapshot, owner_user_id=OWNER) == run
    placeholder = run_from_snapshot(snapshot)
    assert placeholder.owner_user_id == UUID(int=0)
    assert all(item.owner_user_id == UUID(int=0) for item in placeholder.proposals)
    assert placeholder.waiting == (placeholder.proposals[0],)


def test_waiting_proposals_keep_only_the_proposed_ones_in_order():
    first = proposal(1)
    second = proposal(2).with_decision(status=ProposalStatus.APPLIED, decided_at=LATER)
    third = proposal(3, section=ProposalSection.TESTS)
    assert waiting_proposals([second, first, third]) == (first, third)
    assert waiting_proposals(()) == ()
    assert replace(first, status=ProposalStatus.SKIPPED, decided_at=LATER).waiting is False
