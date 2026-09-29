"""Tests for owner-controlled immutable Design Package revisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid5

from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignPackageDiffStatus,
    DesignRevisionDecision,
    DesignRevisionDecisionStatus,
    DesignRevisionIssueCode,
    DesignRevisionProposalStatus,
    decide_design_revision,
    propose_design_revision,
)
from orchestwin.artifacts.design_serialization import (
    design_diff_from_snapshot,
    design_diff_proposal_snapshot,
)

from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    design_package,
    design_version,
)
from .test_design_package_extension import (
    NO_VERDICTS,
    VERDICTS,
    extended_package,
    fixture_bound,
    plain_package,
    support_bound,
)
from .test_generated_mockup_support import BASE_FIRST, BASE_STYLES

DIFF_ID = UUID("00000000-0000-4000-8000-000000000501")
VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000502")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000503")
THIRD = (
    '<main data-req="REQ-003"><h1>Dettaglio del prestito</h1>'
    "<p>Il prestito di Anna Riva scade il 3 ottobre e si può rinnovare una sola volta.</p>"
    '<a href="#SCR-001">Torna al registro</a></main>'
)
TOP = "Il pulsante principale resta in alto a destra."
DUE = "La tabella dei prestiti mostra sempre la data di scadenza."
LATE = "I prestiti in ritardo compaiono per primi."
QUIET = "Nessun colore acceso fuori dagli avvisi."


def proposed_diff():
    """Create one selection-and-prototype revision from an unselected base."""
    base = design_version(package=design_package(selected=False))
    proposed = design_package(selected=True)
    result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=proposed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert result.status is DesignRevisionProposalStatus.CREATED
    assert result.diff is not None

    return base, result.diff


def test_revision_exposes_selection_and_prototype_before_after_changes() -> None:
    """Create an explicit diff rather than mutating the base package."""
    base, diff = proposed_diff()

    assert base.package.owner_selected_alternative_id is None
    assert base.package.prototype is None
    assert diff.proposed_package.owner_selected_alternative_id == ALTERNATIVE_ONE_ID
    assert diff.proposed_package.prototype is not None
    assert tuple((change.artifact_kind, change.kind) for change in diff.changes) == (
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.ADD),
        (DesignArtifactKind.SELECTION, DesignChangeKind.REPLACE),
    )
    assert diff.status is DesignPackageDiffStatus.PROPOSED


def test_approved_diff_creates_version_two_without_mutating_version_one() -> None:
    """Materialize N+1 only after an explicit owner approval."""
    base, diff = proposed_diff()
    decision = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert decision.status is DesignRevisionDecisionStatus.APPLIED
    assert decision.version is not None
    assert decision.version.id == VERSION_TWO_ID
    assert decision.version.version_number == 2
    assert decision.version.based_on_version_number == 1
    assert decision.version.package.ready_for_gate is True
    assert decision.diff.status is DesignPackageDiffStatus.APPROVED
    assert decision.diff.applied_version_id == VERSION_TWO_ID
    assert base.package.ready_for_gate is False


def test_rejection_requires_reason_and_creates_no_version() -> None:
    """Keep rejected proposals auditable without materializing package content."""
    base, diff = proposed_diff()
    missing_reason = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
    )

    assert missing_reason.status is DesignRevisionDecisionStatus.REJECTED
    assert missing_reason.issue is DesignRevisionIssueCode.REASON_REQUIRED

    rejected = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        reason="The owner wants a different prototype direction.",
    )

    assert rejected.status is DesignRevisionDecisionStatus.APPLIED
    assert rejected.version is None
    assert rejected.diff.status is DesignPackageDiffStatus.REJECTED
    assert rejected.diff.decision_reason == ("The owner wants a different prototype direction.")


def test_stale_or_foreign_owner_decision_is_rejected() -> None:
    """Reject decisions outside the exact current version and owner scope."""
    base, diff = proposed_diff()
    stale = replace(
        base,
        id=UUID("00000000-0000-4000-8000-000000000599"),
    )

    stale_result = decide_design_revision(
        diff=diff,
        current_version=stale,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )
    foreign_owner = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OTHER_OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert stale_result.issue is DesignRevisionIssueCode.BASE_VERSION_STALE
    assert foreign_owner.issue is DesignRevisionIssueCode.ACTOR_NOT_OWNER


def test_revision_rejects_context_and_stable_code_changes() -> None:
    """Keep owner revisions inside one governed baseline with stable identities."""
    base = design_version()
    changed_context = replace(
        base.package,
        grounding=replace(
            base.package.grounding,
            catalog_content_hash="e" * 64,
        ),
    )
    changed_code = replace(
        base.package,
        alternatives=(
            base.package.alternatives[1],
            replace(base.package.alternatives[0], code="DES-099"),
        ),
    )

    context_result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_context,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    identifier_result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_code,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert context_result.issue is DesignRevisionIssueCode.CONTEXT_CHANGED
    assert identifier_result.issue is DesignRevisionIssueCode.IDENTIFIER_CHANGED


def propose(base, proposed):
    result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=design_version(package=base),
        proposed_package=proposed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert result.status is DesignRevisionProposalStatus.CREATED
    assert result.diff is not None

    return result.diff


def kinds(diff) -> list[tuple[DesignArtifactKind, DesignChangeKind]]:
    return [(change.artifact_kind, change.kind) for change in diff.changes]


def only(diff, artifact_kind: DesignArtifactKind):
    return [change for change in diff.changes if change.artifact_kind is artifact_kind]


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def screen_identifier(code: str) -> UUID:
    return uuid5(PROJECT_ID, f"generated-screen:{code}")


def assertion_identifier(text: str) -> UUID:
    return uuid5(PROJECT_ID, f"owner-assertion:{text}")


def test_revision_reports_an_added_mockup_together_with_its_derived_prototype() -> None:
    bound = fixture_bound()
    base = plain_package()
    proposed = extended_package(bound, assertions=(), verdicts=NO_VERDICTS)

    diff = propose(base, proposed)
    mockup, prototype = diff.changes

    assert kinds(diff) == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.ADD),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.ADD),
    ]
    assert mockup.artifact_id == bound.design_alternative_id
    assert (mockup.before, mockup.after) == (None, bound.to_snapshot())
    assert prototype.after == bound.prototype().to_snapshot()


def test_revision_reports_a_removed_mockup_together_with_its_derived_prototype() -> None:
    bound = fixture_bound()

    diff = propose(extended_package(bound, assertions=(), verdicts=NO_VERDICTS), plain_package())
    mockup = only(diff, DesignArtifactKind.GENERATED_MOCKUP)[0]

    assert kinds(diff) == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.REMOVE),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.REMOVE),
    ]
    assert mockup.artifact_id == bound.design_alternative_id
    assert (mockup.before, mockup.after) == (bound.to_snapshot(), None)


def test_revision_reports_the_screens_and_the_styles_of_a_replaced_mockup() -> None:
    before = support_bound(extra=(THIRD,))
    after = support_bound(
        BASE_FIRST.replace("Prestiti della settimana", "Prestiti del mese"),
        styles=BASE_STYLES + "h1{margin:0}",
    )

    diff = propose(
        extended_package(before, assertions=(), verdicts=NO_VERDICTS),
        extended_package(after, assertions=(), verdicts=NO_VERDICTS),
    )
    screens = {
        change.artifact_id: change for change in only(diff, DesignArtifactKind.GENERATED_SCREEN)
    }
    styles = only(diff, DesignArtifactKind.GENERATED_STYLES)
    mockup = only(diff, DesignArtifactKind.GENERATED_MOCKUP)

    assert sorted(kinds(diff), key=lambda item: (item[0].value, item[1].value)) == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.REPLACE),
        (DesignArtifactKind.GENERATED_SCREEN, DesignChangeKind.REMOVE),
        (DesignArtifactKind.GENERATED_SCREEN, DesignChangeKind.REPLACE),
        (DesignArtifactKind.GENERATED_STYLES, DesignChangeKind.REPLACE),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.REPLACE),
    ]
    assert (mockup[0].before, mockup[0].after) == (before.to_snapshot(), after.to_snapshot())
    assert set(screens) == {screen_identifier("SCR-001"), screen_identifier("SCR-003")}
    changed = screens[screen_identifier("SCR-001")]
    removed = screens[screen_identifier("SCR-003")]
    assert changed.kind is DesignChangeKind.REPLACE
    assert changed.before == {
        "code": "SCR-001",
        "title": before.mockup.screens[0].title,
        "state": before.mockup.screens[0].state.value,
        "markup_hash": text_hash(before.mockup.screens[0].markup),
    }
    assert changed.after == {
        **changed.before,
        "markup_hash": text_hash(after.mockup.screens[0].markup),
    }
    assert removed.kind is DesignChangeKind.REMOVE
    assert removed.before["code"] == "SCR-003"
    assert removed.after is None
    assert styles[0].artifact_id == PROJECT_ID
    assert (styles[0].before, styles[0].after) == (
        {"styles_hash": text_hash(before.mockup.styles)},
        {"styles_hash": text_hash(after.mockup.styles)},
    )


def test_revision_reports_an_added_screen_and_leaves_equal_screens_and_styles_out() -> None:
    before = support_bound()
    after = support_bound(extra=(THIRD,))

    diff = propose(
        extended_package(before, assertions=(), verdicts=NO_VERDICTS),
        extended_package(after, assertions=(), verdicts=NO_VERDICTS),
    )
    added = only(diff, DesignArtifactKind.GENERATED_SCREEN)

    assert kinds(diff) == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.REPLACE),
        (DesignArtifactKind.GENERATED_SCREEN, DesignChangeKind.ADD),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.REPLACE),
    ]
    assert added[0].artifact_id == screen_identifier("SCR-003")
    assert added[0].before is None
    assert added[0].after["markup_hash"] == text_hash(after.mockup.screens[2].markup)


def test_revision_reports_a_new_requirement_map_of_the_same_mockup() -> None:
    before = support_bound()
    identifiers = dict(before.requirement_ids_by_code)
    after = replace(
        before,
        requirement_ids_by_code=(
            ("REQ-001", identifiers["REQ-002"]),
            ("REQ-002", identifiers["REQ-001"]),
        ),
    )

    diff = propose(
        extended_package(before, assertions=(), verdicts=NO_VERDICTS),
        extended_package(after, assertions=(), verdicts=NO_VERDICTS),
    )

    assert kinds(diff) == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.REPLACE),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.REPLACE),
    ]


def test_revision_reports_added_and_removed_owner_assertions() -> None:
    diff = propose(
        extended_package(None, assertions=(TOP, DUE, LATE), verdicts=NO_VERDICTS),
        extended_package(None, assertions=(TOP, LATE, QUIET), verdicts=NO_VERDICTS),
    )
    changes = {change.artifact_id: change for change in diff.changes}

    assert sorted(kinds(diff), key=lambda item: item[1].value) == [
        (DesignArtifactKind.OWNER_ASSERTION, DesignChangeKind.ADD),
        (DesignArtifactKind.OWNER_ASSERTION, DesignChangeKind.REMOVE),
    ]
    assert changes[assertion_identifier(QUIET)].kind is DesignChangeKind.ADD
    assert changes[assertion_identifier(QUIET)].after == {"text": QUIET}
    assert changes[assertion_identifier(DUE)].kind is DesignChangeKind.REMOVE
    assert changes[assertion_identifier(DUE)].before == {"text": DUE}


def test_revision_reports_a_new_order_of_the_kept_owner_assertions() -> None:
    diff = propose(
        extended_package(None, assertions=(TOP, DUE, LATE), verdicts=NO_VERDICTS),
        extended_package(None, assertions=(LATE, TOP, QUIET), verdicts=NO_VERDICTS),
    )
    order = only(diff, DesignArtifactKind.OWNER_ASSERTION_ORDER)
    reordered_only = propose(
        extended_package(None, assertions=(TOP, DUE), verdicts=NO_VERDICTS),
        extended_package(None, assertions=(DUE, TOP), verdicts=NO_VERDICTS),
    )

    assert len(only(diff, DesignArtifactKind.OWNER_ASSERTION)) == 2
    assert order[0].kind is DesignChangeKind.REPLACE
    assert order[0].artifact_id == PROJECT_ID
    assert order[0].before == {"items": [TOP, DUE, LATE]}
    assert order[0].after == {"items": [LATE, TOP, QUIET]}
    assert kinds(reordered_only) == [
        (DesignArtifactKind.OWNER_ASSERTION_ORDER, DesignChangeKind.REPLACE),
    ]


def test_revision_reports_verdicts_that_appear_change_or_disappear() -> None:
    silent = extended_package(None, assertions=(), verdicts=NO_VERDICTS)
    spoken = extended_package(None, assertions=(), verdicts=VERDICTS)
    revised = extended_package(
        None,
        assertions=(),
        verdicts=(
            VERDICTS[0],
            ("Da rivedere", "Mi perdo tra troppi pulsanti nella stessa pagina."),
        ),
    )
    quote_only = extended_package(
        None,
        assertions=(),
        verdicts=(VERDICTS[0], (VERDICTS[1][0], "Capisco cosa fare, ma cerco ancora il pulsante.")),
    )

    added = propose(silent, spoken)
    changed = propose(spoken, revised)
    requoted = propose(spoken, quote_only)
    removed = propose(spoken, silent)
    second = spoken.critiques[1]

    assert sorted(kinds(added), key=lambda item: item[0].value) == [
        (DesignArtifactKind.CRITIQUE, DesignChangeKind.REPLACE),
        (DesignArtifactKind.CRITIQUE, DesignChangeKind.REPLACE),
        (DesignArtifactKind.CRITIQUE_VERDICT, DesignChangeKind.ADD),
        (DesignArtifactKind.CRITIQUE_VERDICT, DesignChangeKind.ADD),
    ]
    assert {change.artifact_id for change in only(added, DesignArtifactKind.CRITIQUE_VERDICT)} == {
        item.id for item in spoken.critiques
    }
    assert kinds(changed) == [
        (DesignArtifactKind.CRITIQUE, DesignChangeKind.REPLACE),
        (DesignArtifactKind.CRITIQUE_VERDICT, DesignChangeKind.REPLACE),
    ]
    verdict = only(changed, DesignArtifactKind.CRITIQUE_VERDICT)[0]
    assert verdict.artifact_id == second.id
    assert verdict.before == {"verdict": VERDICTS[1][0], "quote": VERDICTS[1][1]}
    assert verdict.after == {
        "verdict": "Da rivedere",
        "quote": "Mi perdo tra troppi pulsanti nella stessa pagina.",
    }
    assert kinds(requoted) == kinds(changed)
    assert {change.kind for change in only(removed, DesignArtifactKind.CRITIQUE_VERDICT)} == {
        DesignChangeKind.REMOVE
    }


def test_a_diff_with_every_new_change_kind_round_trips_through_its_snapshot() -> None:
    before = support_bound(extra=(THIRD,))
    after = support_bound(styles=BASE_STYLES + "h1{margin:0}")
    diff = propose(
        extended_package(before, assertions=(TOP, DUE), verdicts=NO_VERDICTS),
        extended_package(after, assertions=(DUE, QUIET), verdicts=VERDICTS),
    )
    stored = json.loads(json.dumps(design_diff_proposal_snapshot(diff)))

    restored = design_diff_from_snapshot(stored, status=DesignPackageDiffStatus.PROPOSED)

    assert restored == diff
    assert {change.artifact_kind for change in diff.changes} >= {
        DesignArtifactKind.GENERATED_MOCKUP,
        DesignArtifactKind.GENERATED_SCREEN,
        DesignArtifactKind.GENERATED_STYLES,
        DesignArtifactKind.OWNER_ASSERTION,
        DesignArtifactKind.CRITIQUE_VERDICT,
        DesignArtifactKind.PROTOTYPE,
    }
    assert len({(change.artifact_kind, change.artifact_id) for change in diff.changes}) == len(
        diff.changes
    )
