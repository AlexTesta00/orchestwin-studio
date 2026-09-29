from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from orchestwin.knowledge.state import (
    CRITIQUE_VERDICTS,
    DECISIONS,
    FILE_KINDS,
    MAX_DIFF_LENGTH,
    MAX_FILES,
    MAX_MESSAGE_LENGTH,
    SEVERITIES,
    TASK_STATUSES,
    VERDICTS,
    ProjectStateSources,
)
from orchestwin.projects.code_changes import (
    AlignmentStatus,
    AlignmentVerdict,
    ChangeDecision,
    ChangedFile,
    ChangedFileKind,
    ChangeReviewRun,
    CodeTask,
    CritiqueFinding,
    CritiqueVerdict,
    DecisionKind,
    FindingSeverity,
    TaskStatus,
    TwinCritique,
    aligned_change,
    alignment_verdict_from_snapshot,
    changed_file_from_snapshot,
    code_task_code,
    commit_prefix,
    create_code_change,
    normalize_note,
    pending_changes,
    twin_critique_from_snapshot,
)
from src.test.python.artifacts import design_fixtures

PROJECT = design_fixtures.PROJECT_ID
OWNER = design_fixtures.OWNER_ID
TWIN_ONE = UUID("00000000-0000-4000-8000-000000000a01")
TWIN_TWO = UUID("00000000-0000-4000-8000-000000000a02")
RUN_ID = UUID("00000000-0000-4000-8000-000000000a10")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
DIFF = "diff --git a/src/app.js b/src/app.js\n@@ -1 +1 @@\n-old\n+new\n"


def changed_file(path="src/app.js", kind=ChangedFileKind.MODIFIED, added=12, removed=3):
    return ChangedFile(path=path, kind=kind, added=added, removed=removed)


def code_change(commit=FIRST, *, minutes=0, number=1, **values):
    arguments = {
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "commit": commit,
        "parent": None,
        "committed_at": NOW + timedelta(minutes=minutes),
        "author": "Ada Lovelace",
        "message": "Aggiunge la lista degli ospiti",
        "files": (changed_file(),),
        "diff": DIFF,
        "recorded_at": NOW + timedelta(minutes=minutes, seconds=30),
        "change_id": UUID(int=0xC000 + number),
    }
    arguments.update(values)
    return create_code_change(**arguments)


def finding(**values):
    arguments = {
        "severity": FindingSeverity.MEDIUM,
        "text": "Il modulo non chiede la data di arrivo.",
        "requirement": "REQ-001",
        "screen": "SCR-001",
        "file": "src/app.js",
        "action": "Aggiungere il campo della data di arrivo.",
    }
    arguments.update(values)
    return CritiqueFinding(**arguments)


def critique(twin_id=TWIN_ONE, twin_name="Receptionist Twin", **values):
    arguments = {
        "twin_id": twin_id,
        "twin_name": twin_name,
        "verdict": CritiqueVerdict.CONCERN,
        "summary": "La modifica mi aiuta ma manca un dato che uso ogni giorno.",
        "findings": (finding(),),
    }
    arguments.update(values)
    return TwinCritique(**arguments)


def verdict(status=AlignmentStatus.ALIGNED, **values):
    arguments = {
        "status": status,
        "summary": "Il codice segue il design approvato.",
        "affected_requirements": ("REQ-001",),
        "affected_screens": ("SCR-001",),
        "design_request": None,
        "requirements_request": None,
        "code_tasks": (),
    }
    if status is AlignmentStatus.DESIGN_OUTDATED:
        arguments["design_request"] = "Aggiungere al design la schermata degli arrivi."
    if status is AlignmentStatus.REQUIREMENTS_OUTDATED:
        arguments["requirements_request"] = "Aggiungere il requisito della data di arrivo."
    if status is AlignmentStatus.CODE_DRIFT:
        arguments["code_tasks"] = ("Ripristinare il pulsante di salvataggio.",)
    arguments.update(values)
    return AlignmentVerdict(**arguments)


def review_run(change=None, **values):
    reviewed = change if change is not None else code_change()
    arguments = {
        "id": RUN_ID,
        "change_id": reviewed.id,
        "project_id": reviewed.project_id,
        "owner_user_id": reviewed.owner_user_id,
        "commit": reviewed.commit,
        "reviewed_at": NOW + timedelta(hours=1),
        "locale": "it-IT",
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
        "critiques": (critique(),),
        "alignment": verdict(),
        "generation_ids": (UUID(int=0xE001), UUID(int=0xE002)),
        "cost_microusd": 450_000,
    }
    arguments.update(values)
    return ChangeReviewRun(**arguments)


def code_task(number=1, **values):
    arguments = {
        "id": UUID(int=0xD000 + number),
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "number": number,
        "text": "Ripristinare il pulsante di salvataggio.",
        "from_change_id": code_change().id,
        "from_commit": FIRST,
        "created_at": NOW,
        "requirements": ("REQ-001",),
        "screens": ("SCR-001",),
    }
    arguments.update(values)
    return CodeTask(**arguments)


def decided(change, kind, *, minutes=90, note=None, versions=(None, None)):
    decision = ChangeDecision(
        kind=kind, decided_at=NOW + timedelta(minutes=minutes), note=normalize_note(note)
    )
    return change.with_decision(
        decision, requirements_version=versions[0], design_version=versions[1]
    )


def test_the_enumerations_match_the_shared_contract():
    assert tuple(item.value for item in AlignmentStatus) == VERDICTS
    assert tuple(item.value for item in DecisionKind) == DECISIONS
    assert tuple(item.value for item in CritiqueVerdict) == CRITIQUE_VERDICTS
    assert tuple(item.value for item in ChangedFileKind) == FILE_KINDS
    assert tuple(item.value for item in FindingSeverity) == SEVERITIES
    assert tuple(item.value for item in TaskStatus) == TASK_STATUSES


@pytest.mark.parametrize(
    ("number", "code"),
    [(1, "TSK-001"), (42, "TSK-042"), (999, "TSK-999"), (1000, "TSK-1000"), (999999, "TSK-999999")],
)
def test_task_codes_continue_the_three_digit_sequence(number, code):
    assert code_task_code(number) == code
    assert code_task(number).code == code


@pytest.mark.parametrize("number", [0, -1, 1_000_000, True, 1.0, "1"])
def test_a_task_number_must_be_a_positive_integer_within_six_digits(number):
    with pytest.raises(ValueError):
        code_task_code(number)


def test_a_recorded_change_has_the_exact_shape_of_the_contract():
    change = code_change(
        commit="ABCDEF1" + "0" * 33,
        parent="FEDCBA9" + "0" * 33,
        committed_at=datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=2))),
        author="  Ada   Lovelace ",
        message="  Aggiunge la lista\n\ncon i dettagli  \n",
    )
    assert change.commit == "abcdef1" + "0" * 33
    assert change.parent == "fedcba9" + "0" * 33
    assert change.author == "Ada Lovelace"
    assert change.message == "Aggiunge la lista\n\ncon i dettagli"
    snapshot = change.to_snapshot()
    assert list(snapshot) == [
        "commit",
        "parent",
        "committed_at",
        "author",
        "message",
        "files",
        "recorded_at",
        "review",
        "decision",
    ]
    assert snapshot["committed_at"] == "2026-09-29T10:00:00+00:00"
    assert snapshot["recorded_at"] == "2026-09-29T10:00:30+00:00"
    assert snapshot["files"] == [
        {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}
    ]
    assert (snapshot["review"], snapshot["decision"]) == (None, None)
    assert change.to_snapshot(include_diff=True) == {**snapshot, "diff": DIFF}


def test_a_listed_change_without_its_diff_cannot_show_it():
    listed = replace(code_change(), diff=None)
    assert "diff" not in listed.to_snapshot()
    with pytest.raises(ValueError):
        listed.to_snapshot(include_diff=True)


@pytest.mark.parametrize(
    "values",
    [
        {"commit": "abcdef"},
        {"commit": "a" * 65},
        {"commit": "abcdefg"},
        {"parent": FIRST},
        {"parent": "123"},
        {"message": "   "},
        {"message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        {"message": "a\x00b"},
        {"author": "x" * 201},
        {"author": "Ada\x07"},
        {"files": tuple(changed_file(path=f"f{index}") for index in range(MAX_FILES + 1))},
        {"files": ({"path": "src/app.js"},)},
        {"diff": "x" * (MAX_DIFF_LENGTH + 1)},
        {"diff": "a\x00b"},
        {"committed_at": datetime(2026, 9, 29, 10, 0)},
        {"recorded_at": datetime(2026, 9, 29, 10, 0)},
    ],
)
def test_every_limit_of_a_change_is_validated(values):
    with pytest.raises(ValueError):
        code_change(**values)


def test_a_change_holds_at_most_the_limits_exactly():
    change = code_change(
        commit="a" * 64,
        parent="b" * 7,
        message="x" * MAX_MESSAGE_LENGTH,
        author="y" * 200,
        files=tuple(changed_file(path=f"f{index}") for index in range(MAX_FILES)),
        diff="z" * MAX_DIFF_LENGTH,
        committed_at=NOW,
    )
    assert len(change.files) == MAX_FILES
    assert code_change(author="   ").author is None
    assert code_change(author=None).author is None


@pytest.mark.parametrize(
    "values",
    [
        {"path": ""},
        {"path": "   "},
        {"path": "x" * 501},
        {"path": "src/\napp.js"},
        {"kind": "MODIFIED"},
        {"added": -1},
        {"removed": True},
        {"added": 1.5},
    ],
)
def test_every_limit_of_a_changed_file_is_validated(values):
    with pytest.raises(ValueError):
        changed_file(**values)


def test_a_changed_file_round_trips_its_snapshot():
    item = changed_file(path="src/nuovo file.js", kind=ChangedFileKind.RENAMED, added=0)
    assert changed_file_from_snapshot(item.to_snapshot()) == item
    assert changed_file(path="x" * 500).path == "x" * 500


def test_commit_prefixes_are_lower_case_hexadecimal_of_seven_to_sixty_four_characters():
    assert commit_prefix("ABCDEF1") == "abcdef1"
    assert commit_prefix("a" * 64) == "a" * 64
    for value in ("abcdef", "a" * 65, "abcdefg", "", "abc def1"):
        assert commit_prefix(value) is None


def test_a_decision_replaces_the_previous_one_and_keeps_versions_only_when_aligned():
    change = code_change()
    aligned = decided(change, DecisionKind.ALIGNED, versions=(2, 3), note="  Tutto bene. ")
    assert aligned.aligned
    assert aligned.decision.note == "Tutto bene."
    assert aligned.to_snapshot()["decision"] == {
        "kind": "ALIGNED",
        "decided_at": "2026-09-29T11:30:00+00:00",
        "note": "Tutto bene.",
    }
    point = aligned.aligned_point()
    assert point.to_snapshot() == {
        "commit": FIRST,
        "decided_at": "2026-09-29T11:30:00+00:00",
        "requirements_version_number": 2,
        "design_version_number": 3,
    }
    dismissed = decided(aligned, DecisionKind.DISMISSED, versions=(2, 3))
    assert not dismissed.aligned
    assert (dismissed.aligned_requirements_version, dismissed.aligned_design_version) == (
        None,
        None,
    )
    with pytest.raises(ValueError):
        dismissed.aligned_point()
    with pytest.raises(ValueError):
        replace(dismissed, aligned_design_version=3)
    with pytest.raises(ValueError):
        replace(aligned, aligned_design_version=0)


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" Una nota\nsu due righe. ", "Una nota\nsu due righe."),
    ],
)
def test_decision_notes_are_trimmed_and_blank_notes_are_absent(note, expected):
    assert normalize_note(note) == expected


def test_a_decision_note_has_a_limit_and_a_decision_needs_an_aware_time():
    with pytest.raises(ValueError):
        normalize_note("x" * 2001)
    assert normalize_note("x" * 2000) == "x" * 2000
    with pytest.raises(ValueError):
        ChangeDecision(kind=DecisionKind.DISMISSED, decided_at=datetime(2026, 9, 29, 10, 0))
    with pytest.raises(ValueError):
        ChangeDecision(kind="DISMISSED", decided_at=NOW)
    with pytest.raises(ValueError):
        ChangeDecision(kind=DecisionKind.DISMISSED, decided_at=NOW, note=" spaced ")


def test_the_pending_changes_follow_the_newest_aligned_change():
    first = decided(code_change(FIRST, number=1), DecisionKind.ALIGNED, versions=(1, 1))
    second = decided(code_change(SECOND, minutes=5, number=2), DecisionKind.ALIGNED, minutes=95)
    third = decided(code_change(THIRD, minutes=10, number=3), DecisionKind.DISMISSED)
    fourth = code_change("4" * 40, minutes=15, number=4)
    newest_first = (fourth, third, second, first)
    assert pending_changes(newest_first) == (fourth, third)
    assert aligned_change(newest_first) == second
    sources = ProjectStateSources(
        aligned=second.aligned_point().to_snapshot(),
        changes=tuple(item.to_snapshot() for item in newest_first),
    )
    assert sources.pending_changes == len(pending_changes(newest_first)) == 2
    unaligned = (fourth, third)
    assert pending_changes(unaligned) == unaligned
    assert aligned_change(unaligned) is None
    assert pending_changes(()) == ()


def test_a_finding_has_the_shape_and_the_limits_of_the_contract():
    assert finding().to_snapshot() == {
        "severity": "MEDIUM",
        "text": "Il modulo non chiede la data di arrivo.",
        "about": {"requirement": "REQ-001", "screen": "SCR-001", "file": "src/app.js"},
        "action": "Aggiungere il campo della data di arrivo.",
    }
    bare = finding(requirement=None, screen=None, file=None, action=None)
    assert bare.to_snapshot()["about"] == {"requirement": None, "screen": None, "file": None}
    for values in (
        {"text": "x" * 401},
        {"text": " spaced "},
        {"requirement": "SCR-001"},
        {"screen": "REQ-001"},
        {"requirement": "REQ-1"},
        {"action": "x" * 301},
        {"severity": "HIGH"},
        {"file": ""},
    ):
        with pytest.raises(ValueError):
            finding(**values)


def test_a_critique_has_the_shape_and_the_limits_of_the_contract():
    item = critique()
    assert item.to_snapshot() == {
        "twin_id": str(TWIN_ONE),
        "twin_name": "Receptionist Twin",
        "verdict": "CONCERN",
        "summary": "La modifica mi aiuta ma manca un dato che uso ogni giorno.",
        "findings": [finding().to_snapshot()],
    }
    assert twin_critique_from_snapshot(item.to_snapshot()) == item
    assert len(critique(findings=(finding(),) * 6).findings) == 6
    for values in (
        {"findings": (finding(),) * 7},
        {"findings": [finding()]},
        {"summary": "x" * 601},
        {"summary": ""},
        {"verdict": "FINE"},
        {"twin_name": ""},
        {"twin_id": str(TWIN_ONE)},
    ):
        with pytest.raises(ValueError):
            critique(**values)


@pytest.mark.parametrize("status", list(AlignmentStatus))
def test_each_verdict_status_carries_exactly_its_request(status):
    item = verdict(status)
    snapshot = item.to_snapshot()
    assert list(snapshot) == [
        "status",
        "summary",
        "affected",
        "design_request",
        "requirements_request",
        "code_tasks",
    ]
    assert snapshot["affected"] == {"requirements": ["REQ-001"], "screens": ["SCR-001"]}
    assert (snapshot["design_request"] is not None) == (status is AlignmentStatus.DESIGN_OUTDATED)
    assert (snapshot["requirements_request"] is not None) == (
        status is AlignmentStatus.REQUIREMENTS_OUTDATED
    )
    assert alignment_verdict_from_snapshot(snapshot) == item


@pytest.mark.parametrize(
    ("status", "values"),
    [
        (AlignmentStatus.DESIGN_OUTDATED, {"design_request": None}),
        (AlignmentStatus.ALIGNED, {"design_request": "Cambiare il design."}),
        (AlignmentStatus.REQUIREMENTS_OUTDATED, {"requirements_request": None}),
        (AlignmentStatus.CODE_DRIFT, {"requirements_request": "Cambiare i requisiti."}),
        (AlignmentStatus.CODE_DRIFT, {"code_tasks": ()}),
        (AlignmentStatus.ALIGNED, {"code_tasks": ("Uno.",) * 2}),
        (AlignmentStatus.ALIGNED, {"code_tasks": tuple(f"Compito {index}." for index in range(7))}),
        (AlignmentStatus.ALIGNED, {"code_tasks": ("x" * 301,)}),
        (AlignmentStatus.ALIGNED, {"affected_requirements": ("REQ-001", "REQ-001")}),
        (AlignmentStatus.ALIGNED, {"affected_screens": ("REQ-001",)}),
        (AlignmentStatus.ALIGNED, {"affected_requirements": ["REQ-001"]}),
        (AlignmentStatus.DESIGN_OUTDATED, {"design_request": "x" * 1001}),
        (AlignmentStatus.REQUIREMENTS_OUTDATED, {"requirements_request": "x" * 2001}),
        (AlignmentStatus.ALIGNED, {"summary": "x" * 601}),
    ],
)
def test_the_verdict_rules_of_the_contract_are_enforced(status, values):
    with pytest.raises(ValueError):
        verdict(status, **values)


def test_a_verdict_may_propose_up_to_six_code_tasks_for_any_status():
    tasks = tuple(f"Compito {index}." for index in range(6))
    assert verdict(AlignmentStatus.ALIGNED, code_tasks=tasks).code_tasks == tasks
    assert verdict(AlignmentStatus.CODE_DRIFT, code_tasks=tasks).code_tasks == tasks


def test_a_review_run_has_the_exact_shape_of_the_contract():
    run = review_run(critiques=(critique(), critique(TWIN_TWO, "Night Auditor Twin")))
    snapshot = run.to_snapshot()
    assert list(snapshot) == [
        "id",
        "commit",
        "reviewed_at",
        "locale",
        "reference",
        "critiques",
        "alignment",
        "cost_microusd",
    ]
    assert snapshot["id"] == str(RUN_ID)
    assert snapshot["reviewed_at"] == "2026-09-29T11:00:00+00:00"
    assert snapshot["reference"] == {
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
    }
    assert [item["twin_name"] for item in snapshot["critiques"]] == [
        "Receptionist Twin",
        "Night Auditor Twin",
    ]
    assert snapshot["alignment"] == verdict().to_snapshot()
    assert snapshot["cost_microusd"] == 450_000
    summary = run.summary()
    assert summary.to_snapshot() == {
        "run_id": str(RUN_ID),
        "reviewed_at": "2026-09-29T11:00:00+00:00",
        "verdict": "ALIGNED",
        "summary": "Il codice segue il design approvato.",
    }
    reviewed = code_change().with_review(summary)
    assert reviewed.to_snapshot()["review"] == summary.to_snapshot()


@pytest.mark.parametrize(
    "values",
    [
        {"critiques": ()},
        {"critiques": (critique(), critique())},
        {"critiques": tuple(critique(UUID(int=index)) for index in range(1, 10))},
        {"locale": "it_IT"},
        {"locale": "italiano"},
        {"alternative_code": "ALT-001"},
        {"requirements_version_number": 0},
        {"design_version_number": None},
        {"cost_microusd": -1},
        {"generation_ids": (UUID(int=1), UUID(int=1))},
        {"generation_ids": ("x",)},
        {"commit": "ABCDEF1"},
        {"reviewed_at": datetime(2026, 9, 29, 11, 0)},
    ],
)
def test_every_limit_of_a_review_run_is_validated(values):
    with pytest.raises(ValueError):
        review_run(**values)


def test_a_task_has_the_exact_shape_of_the_contract_and_can_be_done():
    task = code_task(12)
    assert task.code == "TSK-012"
    assert task.open
    assert task.to_snapshot() == {
        "code": "TSK-012",
        "text": "Ripristinare il pulsante di salvataggio.",
        "about": {"requirements": ["REQ-001"], "screens": ["SCR-001"]},
        "from_commit": FIRST,
        "created_at": "2026-09-29T10:00:00+00:00",
        "status": "OPEN",
    }
    done = task.done(NOW + timedelta(days=1))
    assert not done.open
    assert done.to_snapshot()["status"] == "DONE"
    for values in (
        {"status": TaskStatus.DONE},
        {"done_at": NOW},
        {"text": " spaced "},
        {"text": "x" * 301},
        {"number": 0},
        {"requirements": ("SCR-001",)},
        {"screens": ("SCR-001", "SCR-001")},
        {"from_commit": "123"},
    ):
        with pytest.raises(ValueError):
            code_task(**values)
