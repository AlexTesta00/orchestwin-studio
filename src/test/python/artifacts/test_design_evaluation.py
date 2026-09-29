from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts import design_evaluation as module
from orchestwin.artifacts.design_evaluation import (
    ANCHOR_LABEL_LENGTH,
    HOSTED_DOCUMENT_BYTES,
    MAX_ELEMENT_ANCHORS,
    AnchoredSyntheticFinding,
    DesignEvaluationError,
    anchor_finding,
    compare_design_evaluations,
    create_design_evaluation_run,
    design_evaluation_run_from_snapshot,
    design_review_anchors,
    design_review_view,
    evaluation_bundle,
    evaluation_document,
    finding_anchor_key,
    finding_key,
    finding_similarity,
    ordered_screens,
    remaining_rows_text,
    synthetic_finding_from_snapshot,
)
from orchestwin.artifacts.design_static_check import static_check_document, static_check_target
from orchestwin.artifacts.prototypes import create_prototype_element, create_prototype_screen
from orchestwin.evaluation.artifact_content import MAX_VIEW_BYTES, prepare_artifact_content
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

from . import design_fixtures
from .test_design_package_extension import (
    LARGE_ROWS,
    extended_package,
    fixture_package,
    large_bound,
    large_markup,
    support_bound,
)
from .test_generated_mockup_support import FIXTURES

NOW = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
TWIN_A = UUID("00000000-0000-4000-8000-000000000911")
TWIN_B = UUID("00000000-0000-4000-8000-000000000912")
CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="fake-design-evaluator",
    evaluator_version="1",
    model_config_ref="config-1",
    prompt_version_ref="prompt-1",
)


def twin_profile(twin_id: UUID, name: str) -> EvaluationUserTwinProfile:
    snapshot = '{"name": "' + name + '"}'
    return EvaluationUserTwinProfile(
        twin_id=twin_id,
        version_number=1,
        name=name,
        lifecycle_status=next(iter(UserTwinLifecycleStatus)),
        content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        snapshot_json=snapshot,
    )


def template(
    finding_id: str,
    location: str,
    summary: str,
    criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
):
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        location=location,
        summary=summary,
        rationale="Simulated rationale.",
        criterion=criterion,
        severity=SyntheticFindingSeverity.MODERATE,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.6,
        recommended_action="Add a visible label.",
        requires_human_validation=True,
    )


def relocated(finding, location):
    return create_synthetic_finding(
        finding_id=finding.finding_id,
        twin_id=finding.twin_id,
        twin_version=finding.twin_version,
        artifact_id=finding.artifact_id,
        artifact_version=finding.artifact_version,
        location=location,
        summary=finding.summary,
        rationale=finding.rationale,
        criterion=finding.criterion,
        severity=finding.severity,
        epistemic_status=finding.epistemic_status,
        evidence_refs=finding.evidence_refs,
        confidence=finding.confidence,
        recommended_action=finding.recommended_action,
        requires_human_validation=finding.requires_human_validation,
        model_config_ref=finding.model_config_ref,
        prompt_version_ref=finding.prompt_version_ref,
    )


async def evaluate_async(version, templates_by_twin, *, run_id=RUN_ID, clock=NOW):
    document = evaluation_document(version)
    bundle = evaluation_bundle(version, document, locale="it-IT", created_at=clock)
    evaluator = FakeUserTwinEvaluator(
        configuration=CONFIGURATION,
        templates_by_twin=templates_by_twin,
        summaries_by_twin={TWIN_A: "Summary A.", TWIN_B: "Summary B."},
        clock=lambda: clock,
    )
    responses = []
    for twin_id, name in ((TWIN_A, "Ada"), (TWIN_B, "Bruno")):
        request = UserTwinEvaluationRequest(
            evaluation_run_id=run_id,
            project_id=version.project_id,
            workflow_run_id=version.id,
            artifact_bundle=bundle,
            twin=twin_profile(twin_id, name),
            evidence=(),
            requested_at=clock,
        )
        prepared = prepare_artifact_content(
            request,
            selected=((document.reference.artifact_id, document.reference.version_number),),
            read_content=document.read,
        )
        responses.append(await evaluator.evaluate(prepared.request))
    return create_design_evaluation_run(
        run_id=run_id,
        owner_user_id=design_fixtures.OWNER_ID,
        version=version,
        bundle=bundle,
        responses=responses,
        started_at=clock,
        completed_at=clock + timedelta(seconds=5),
    )


def evaluate(version, templates_by_twin, *, run_id=RUN_ID, clock=NOW):
    return asyncio.run(evaluate_async(version, templates_by_twin, run_id=run_id, clock=clock))


def test_evaluation_document_is_a_compact_html_dom_snapshot():
    version = design_fixtures.design_version()
    document = evaluation_document(version)
    text = document.content.decode("utf-8")
    assert len(document.content) <= MAX_VIEW_BYTES
    assert text.startswith("<!doctype html>")
    assert "<style" not in text and "<script" not in text
    assert "Create reservation" in text and 'name="guest_name" required' in text
    assert document.reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert document.reference.artifact_id == version.package.prototype.id
    assert document.reference.location == "design/mockup.html"
    assert document.read(document.reference.storage_key, MAX_VIEW_BYTES) == document.content
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_UNAVAILABLE"):
        document.read("sha256/00/" + "0" * 64, MAX_VIEW_BYTES)


def test_evaluation_document_requires_a_selected_prototype_and_bounds_its_size(monkeypatch):
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    with pytest.raises(DesignEvaluationError, match="DESIGN_PROTOTYPE_REQUIRED"):
        evaluation_document(bare)
    prototype = version.package.prototype
    first = prototype.screens[0]
    long_elements = tuple(
        create_prototype_element(
            element_id=UUID(int=700 + index),
            code=f"ELM-{index + 101:03d}",
            kind=first.elements[0].kind,
            content=("parola " * 500).strip(),
            accessible_name="x" * 3000,
            requirement_ids=first.elements[0].requirement_ids,
            field_name=f"field_{index}",
            required=False,
        )
        for index in range(12)
    )
    screen = create_prototype_screen(
        screen_id=first.id,
        code=first.code,
        title=first.title,
        state=first.state,
        elements=long_elements,
        requirement_ids=first.requirement_ids,
        user_story_ids=first.user_story_ids,
    )
    heavy = design_fixtures.design_version(
        package=replace(
            version.package,
            prototype=replace(prototype, screens=(screen, prototype.screens[1]), transitions=()),
        )
    )
    monkeypatch.setattr(module, "CONTENT_STEPS", (None,))
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_TOO_LARGE"):
        evaluation_document(heavy)


def test_evaluation_bundle_describes_the_design_version_and_its_scenario():
    version = design_fixtures.design_version()
    document = evaluation_document(version)
    bundle = evaluation_bundle(version, document, locale="it-IT", created_at=NOW)
    assert bundle.project_id == version.project_id
    assert bundle.workflow_run_id == version.id
    assert [item.kind for item in bundle.artifacts] == [
        EvaluationArtifactKind.DESIGN_SPECIFICATION,
        EvaluationArtifactKind.DOM_SNAPSHOT,
    ]
    assert bundle.scenario.task == "Create a reservation"
    assert bundle.scenario.expected_outcomes == ("Review availability.", "Save the reservation.")
    assert bundle.scenario.name == "Guided reservation flow"
    again = evaluation_bundle(
        version, document, locale="it-IT", created_at=NOW, bundle_id=bundle.id
    )
    assert again.content_hash == bundle.content_hash


def test_evaluation_run_collects_twin_responses_and_round_trips():
    version = design_fixtures.design_version()
    run = evaluate(
        version,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
            ),
            TWIN_B: (
                template("UTF-002", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
    )
    assert run.design_version_id == version.id
    assert run.alternative_code == "DES-001"
    assert [item.twin_id for item in run.responses] == sorted([TWIN_A, TWIN_B], key=str)
    assert len(run.findings) == 2
    assert all(
        f"artifact:{version.package.prototype.id}:v{version.version_number}"
        in finding.evidence_refs
        for finding in run.findings
    )
    snapshot = run.to_snapshot()
    assert snapshot["schema_version"] == 1
    assert design_evaluation_run_from_snapshot(snapshot) == run
    with pytest.raises(ValueError, match=r"hash is inconsistent|not canonical"):
        design_evaluation_run_from_snapshot({**snapshot, "alternative_code": "DES-009"})
    with pytest.raises(ValueError, match="hash is inconsistent"):
        replace(run, alternative_code="DES-002")
    with pytest.raises(ValueError, match="complete after it starts"):
        replace(
            replace(run, completed_at=NOW - timedelta(seconds=1)),
            content_hash=run.content_hash,
        )


def test_comparison_separates_resolved_persisting_and_new_findings():
    version = design_fixtures.design_version()
    base = evaluate(
        version,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
                template("UTF-002", "SCR-001 Save", "The save button label is vague."),
            ),
            TWIN_B: (
                template("UTF-003", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
    )
    head = evaluate(
        version,
        {
            TWIN_A: (
                template(
                    "UTF-001", "SCR-001 guest name", "The guest name field still lacks help text."
                ),
                template("UTF-004", "SCR-001 Dates", "The date fields need a format hint."),
            ),
            TWIN_B: (),
        },
        run_id=UUID("00000000-0000-4000-8000-000000000902"),
        clock=NOW + timedelta(minutes=10),
    )
    comparison = compare_design_evaluations(base, head)
    snapshot = comparison.to_snapshot()
    assert snapshot["counts"] == {
        "base": 3,
        "head": 2,
        "resolved": 2,
        "persisting": 1,
        "introduced": 1,
        "dismissed": 0,
    }
    assert [item.finding_id for item in comparison.resolved] == ["UTF-002", "UTF-003"]
    assert comparison.persisting[0][0].location == "SCR-001 Guest name"
    assert comparison.introduced[0].finding_id == "UTF-004"
    first, second = base.findings[0], head.findings[0]
    assert finding_similarity(first, second) == 1.0
    assert finding_similarity(first, base.findings[2]) == 0.0
    assert 0.0 < finding_similarity(first, relocated(second, "elsewhere")) < 1.0


def test_comparison_excludes_the_dismissed_findings_of_each_run():
    version = design_fixtures.design_version()
    base = evaluate(
        version,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
                template("UTF-002", "SCR-001 Save", "The save button label is vague."),
            ),
            TWIN_B: (
                template("UTF-003", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
    )
    head = evaluate(
        version,
        {
            TWIN_A: (
                template(
                    "UTF-001", "SCR-001 guest name", "The guest name field still lacks help text."
                ),
                template("UTF-004", "SCR-001 Dates", "The date fields need a format hint."),
            ),
            TWIN_B: (),
        },
        run_id=UUID("00000000-0000-4000-8000-000000000902"),
        clock=NOW + timedelta(minutes=10),
    )
    saved, dates = base.findings[1], head.findings[1]
    assert finding_key(base.id, saved) == (base.id, TWIN_A, "UTF-002")
    dismissed = frozenset(
        {
            finding_key(base.id, saved),
            finding_key(head.id, dates),
            (head.id, TWIN_B, "UTF-003"),
        }
    )
    comparison = compare_design_evaluations(base, head, dismissed=dismissed)
    assert comparison.to_snapshot()["counts"] == {
        "base": 2,
        "head": 1,
        "resolved": 1,
        "persisting": 1,
        "introduced": 0,
        "dismissed": 2,
    }
    assert [item.finding_id for item in comparison.resolved] == ["UTF-003"]
    assert [pair[0].finding_id for pair in comparison.persisting] == ["UTF-001"]
    assert comparison.introduced == ()
    unrelated = frozenset({(head.id, TWIN_A, "UTF-002"), (base.id, TWIN_A, "UTF-004")})
    assert compare_design_evaluations(base, head, dismissed=unrelated) == (
        compare_design_evaluations(base, head)
    )


def dashboard_version():
    package = design_fixtures.design_package()
    return design_fixtures.design_version(
        package=replace(
            package,
            owner_selected_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID,
            prototype=replace(
                package.prototype, design_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID
            ),
        )
    )


def test_review_anchors_name_every_screen_and_element_from_the_entry_screen():
    version = design_fixtures.design_version()
    assert list(design_review_anchors(version).items()) == [
        ("SCR-001", "SCR-001 Create reservation"),
        ("SCR-001/ELM-001", "SCR-001 Create reservation · ELM-001 Guest name"),
        ("SCR-001/ELM-002", "SCR-001 Create reservation · ELM-002 Save reservation"),
        ("SCR-002", "SCR-002 Reservation confirmation"),
        ("SCR-002/ELM-003", "SCR-002 Reservation confirmation · ELM-003 Reservation saved"),
    ]
    prototype = version.package.prototype
    first, confirmation = prototype.screens
    title = "Confirmation " + "x" * 150
    named = "Guest name " + "y" * 150
    moved = design_fixtures.design_version(
        package=replace(
            version.package,
            prototype=replace(
                prototype,
                entry_screen_id=confirmation.id,
                screens=(
                    replace(
                        first,
                        elements=(
                            replace(first.elements[0], accessible_name=named),
                            first.elements[1],
                        ),
                    ),
                    replace(confirmation, title=title),
                ),
            ),
        )
    )
    anchors = design_review_anchors(moved)
    shortened = title[: ANCHOR_LABEL_LENGTH - 1] + "…"
    assert list(anchors)[:3] == ["SCR-002", "SCR-002/ELM-003", "SCR-001"]
    assert anchors["SCR-002"] == f"SCR-002 {shortened}"
    assert anchors["SCR-002/ELM-003"] == f"SCR-002 {shortened} · ELM-003 Reservation saved"
    assert anchors["SCR-001/ELM-001"] == (
        f"SCR-001 Create reservation · ELM-001 {named[: ANCHOR_LABEL_LENGTH - 1]}…"
    )
    assert len(shortened) == ANCHOR_LABEL_LENGTH


def test_review_view_describes_the_selected_alternative_and_its_screens():
    version = design_fixtures.design_version()
    view = design_review_view(version)
    assert view["alternative"] == {
        "code": "DES-001",
        "title": "Guided reservation flow",
        "summary": "Guide the receptionist through one decision at a time.",
        "rationale": "Reduce cognitive load for occasional users.",
        "information_architecture": ["Availability", "Reservation", "Confirmation"],
        "accessibility_considerations": ["All controls have persistent labels"],
        "trade_offs": ["More navigation"],
        "workflows": [
            {
                "code": "FLOW-001",
                "title": "Create a reservation",
                "steps": ["Review availability.", "Save the reservation."],
            }
        ],
    }
    assert view["visual_language"] is None
    assert view["entry_screen"] == "SCR-001"
    common = {"field_name": None, "required": False, "options": [], "leads_to": None}
    assert view["screens"] == [
        {
            "code": "SCR-001",
            "title": "Create reservation",
            "state": "DEFAULT",
            "elements": [
                {
                    **common,
                    "code": "ELM-001",
                    "kind": "TEXT_INPUT",
                    "content": "Guest name",
                    "accessible_name": "Guest name",
                    "field_name": "guest_name",
                    "required": True,
                },
                {
                    **common,
                    "code": "ELM-002",
                    "kind": "BUTTON",
                    "content": "Save reservation",
                    "accessible_name": "Save reservation",
                    "leads_to": "SCR-002",
                },
            ],
        },
        {
            "code": "SCR-002",
            "title": "Reservation confirmation",
            "state": "SUCCESS",
            "elements": [
                {
                    **common,
                    "code": "ELM-003",
                    "kind": "STATUS",
                    "content": "Reservation saved",
                    "accessible_name": None,
                }
            ],
        },
    ]
    serialized = json.dumps(view)
    assert json.loads(serialized) == view
    assert str(design_fixtures.PROTOTYPE_ID) not in serialized
    assert str(version.package.prototype.screens[0].id) not in serialized
    dashboard = design_review_view(dashboard_version())
    language = design_fixtures.visual_language()
    assert dashboard["alternative"]["code"] == "DES-002"
    assert dashboard["visual_language"] == {
        "product_name": "Reservation desk",
        "rationale": language.rationale,
        "choices": language.choices.to_snapshot(),
        "twin_fit": {
            str(design_fixtures.TWIN_ID): (
                "Large tiles and a calm palette suit a receptionist scanning the desk."
            )
        },
    }


def test_review_anchors_and_view_require_a_selected_prototype():
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    for function in (design_review_anchors, design_review_view):
        with pytest.raises(DesignEvaluationError, match="DESIGN_PROTOTYPE_REQUIRED"):
            function(bare)


def test_findings_of_regenerated_designs_match_by_content_words_whatever_the_criterion():
    version = design_fixtures.design_version()
    base = evaluate(
        version,
        {
            TWIN_A: (
                template(
                    "UTF-001",
                    "SCR-001 Aggiungi ospite",
                    "La lista degli ospiti non consente di identificare eventuali duplicati.",
                    criterion=SyntheticFindingCriterion.TRUST,
                ),
            ),
            TWIN_B: (),
        },
    )
    head = evaluate(
        version,
        {
            TWIN_A: (
                template(
                    "UTF-001",
                    "SCR-004 Lista",
                    "La lista degli ospiti non mostra se un nome è duplicato.",
                    criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
                ),
                template(
                    "UTF-002",
                    "SCR-004 Lista",
                    "Il pulsante di conferma è troppo piccolo per il tocco.",
                    criterion=SyntheticFindingCriterion.ACCESSIBILITY,
                ),
            ),
            TWIN_B: (
                template(
                    "UTF-001",
                    "SCR-004 Lista",
                    "La lista degli ospiti non mostra se un nome è duplicato.",
                    criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
                ),
            ),
        },
        run_id=UUID("00000000-0000-4000-8000-000000000903"),
        clock=NOW + timedelta(minutes=20),
    )
    earlier = base.findings[0]
    same_twin, other_problem, other_twin = head.findings
    assert module.MATCH_SIMILARITY <= finding_similarity(earlier, same_twin) < 1.0
    assert finding_similarity(earlier, other_problem) < module.MATCH_SIMILARITY
    assert finding_similarity(earlier, other_twin) == 0.0
    counts = compare_design_evaluations(base, head).to_snapshot()["counts"]
    assert (counts["resolved"], counts["persisting"], counts["introduced"]) == (0, 1, 2)


DOCUMENT_HASHES = {
    "und": "480fcca62bc634501a18a4717052811c44ac4be07b9d3625d9406883ae5f28af",
    "it": "b0c0fb45e36be9635b3ae2e252405a5a670c8f9c4284856f686d635eb4b5af93",
    "dashboard": "4920eee468d83118b93f01db6348931b0ae9b6b1f1891381fa34f67e6a372ab9",
    "generated": "fe9effbf24e49e0974be5d225d9d1a7f88d8d5569da5f0a760877bfa08cd3ef6",
}
STORED_RUN_HASH = "b83db3e4a67b6a5d550579da5c0feb4a506987d41b7c570c900eda345e7c2df2"
STORED_FINDING_HASH = "13af69773a53dab8a97b15b0388b1de05667e5676d805e11a47089eba6ce7111"
STORED_BUNDLE_ID = UUID("00000000-0000-4000-8000-000000000d01")
STORED_RUN_ID = UUID("00000000-0000-4000-8000-000000000d02")
STORED_AT = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
REVIEW_CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="proposer-design-twin-review",
    evaluator_version="1.0.0",
    model_config_ref="c" * 64,
    prompt_version_ref="s22-design-twin-review-v2",
)
HIDDEN_ROWS = LARGE_ROWS - module.TABLE_ROWS_SHOWN
VIEW_LIMIT = 40 * 1024
SEARCH_FORM = (
    '<form aria-label="Ricerca"><label for="lettore">Lettore</label>'
    '<input id="lettore" name="lettore" type="search">'
    '<button type="button">Cerca</button></form>'
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def generated_version(bound=None):
    return design_fixtures.design_version(
        package=fixture_package() if bound is None else extended_package(bound)
    )


def table_markup(index: int, rows: int, screens: int) -> str:
    target = "SCR-001" if index == screens else f"SCR-{index + 1:03d}"
    body = "".join(
        f"<tr><td>Lettore {index}.{row}</td><td>Volume {row}</td><td>{row} ottobre</td></tr>"
        for row in range(1, rows + 1)
    )
    items = "".join(f"<li>Promemoria {index}.{item} inviato ai lettori.</li>" for item in range(5))
    return (
        f'<main data-req="REQ-00{index}"><h1>Registro della sede {index}</h1>'
        "<p>Controlla i prestiti aperti della sede e invia un promemoria ai lettori in ritardo.</p>"
        '<table><thead><tr><th scope="col">Lettore</th><th scope="col">Titolo</th>'
        f'<th scope="col">Scadenza</th></tr></thead><tbody>{body}</tbody></table>'
        f'<ul>{items}</ul><a href="#{target}">Prosegui</a></main>'
    )


def stored_run(anchor: str | None = None):
    version = design_fixtures.design_version()
    document = evaluation_document(version, language="it")
    bundle = evaluation_bundle(
        version, document, locale="it-IT", created_at=STORED_AT, bundle_id=STORED_BUNDLE_ID
    )
    finding = create_synthetic_finding(
        finding_id="UTF-001",
        twin_id=design_fixtures.TWIN_ID,
        twin_version=2,
        artifact_id=design_fixtures.PROTOTYPE_ID,
        artifact_version=1,
        location="SCR-001 Create reservation · ELM-001 Guest name",
        summary="The guest name field gives no format hint.",
        rationale="At a busy desk I cannot guess the expected name format.",
        criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(
            f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",
            f"user-twin:{design_fixtures.TWIN_ID}:v2#user_twin.role",
        ),
        confidence=0.7,
        recommended_action="Show the expected format below the field.",
        requires_human_validation=True,
        model_config_ref="c" * 64,
        prompt_version_ref="s22-design-twin-review-v2",
    )
    values = {
        "evaluation_run_id": STORED_RUN_ID,
        "artifact_bundle_id": bundle.id,
        "artifact_bundle_hash": bundle.content_hash,
        "twin_id": design_fixtures.TWIN_ID,
        "twin_version": 2,
        "evaluator": REVIEW_CONFIGURATION,
        "findings": (finding if anchor is None else anchor_finding(finding, anchor),),
        "summary": "The flow suits my desk work.",
        "evidence_gaps": (),
    }
    response = UserTwinEvaluationResponse(
        **values,
        completed_at=STORED_AT,
        content_hash=user_twin_evaluation_response_hash(**values),
    )
    return create_design_evaluation_run(
        run_id=STORED_RUN_ID,
        owner_user_id=design_fixtures.OWNER_ID,
        version=version,
        bundle=bundle,
        responses=(response,),
        started_at=STORED_AT,
        completed_at=STORED_AT + timedelta(seconds=5),
    )


def test_the_document_is_byte_identical_for_the_local_route_and_a_declarative_design():
    version = design_fixtures.design_version()
    for hosted in (False, True):
        assert (
            digest(evaluation_document(version, hosted=hosted).content) == (DOCUMENT_HASHES["und"])
        )
        assert (
            digest(evaluation_document(version, language="it", hosted=hosted).content)
            == (DOCUMENT_HASHES["it"])
        )
        dashboard = evaluation_document(dashboard_version(), language="it", hosted=hosted)
        assert digest(dashboard.content) == DOCUMENT_HASHES["dashboard"]
        assert design_review_view(version, hosted=hosted) == design_review_view(version)
        assert design_review_anchors(version, hosted=hosted) == design_review_anchors(version)
    generated = evaluation_document(generated_version(), language="it")
    assert digest(generated.content) == DOCUMENT_HASHES["generated"]


def test_a_hosted_route_reviews_a_generated_mockup_that_the_local_route_refuses():
    version = generated_version(large_bound())
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_TOO_LARGE"):
        evaluation_document(version, language="it")
    document = evaluation_document(version, language="it", hosted=True)
    text = document.content.decode("utf-8")
    assert MAX_VIEW_BYTES < HOSTED_DOCUMENT_BYTES == 96 * 1024
    assert len(document.content) <= HOSTED_DOCUMENT_BYTES
    assert text.count(remaining_rows_text(HIDDEN_ROWS, "it")) == 5
    assert "Lettore 1.12 · Volume 12" in text and "Lettore 1.13 · " not in text
    assert "<script" not in text.lower() and "<style" not in text.lower()
    assert document.reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert document.reference.size_bytes == len(document.content)
    assert evaluation_document(version, language="it", hosted=True) == document


def test_every_table_keeps_twelve_rows_and_one_line_for_the_rest():
    assert remaining_rows_text(1, "it") == "… e un'altra riga della tabella"
    assert remaining_rows_text(29, "it") == "… e altre 29 righe della tabella"
    assert remaining_rows_text(29, "en") == "… and 29 more rows in the table"
    assert remaining_rows_text(1, "und") == "… and one more row in the table"
    short = generated_version(support_bound(table_markup(1, 13, 2), table_markup(2, 12, 2)))
    view = design_review_view(short, hosted=True, language="it")
    first, second = view["screens"]
    assert first["visible_text"].count("… e un'altra riga della tabella") == 1
    assert not any("riga della tabella" in text for text in second["visible_text"])
    assert sum(item["kind"] == "LIST" for item in second["elements"]) == 12 + 5


def test_the_static_check_refuses_a_generated_mockup_it_cannot_hold():
    first = large_markup(1).replace("</h1>", "</h1>" + SEARCH_FORM)
    markups = [large_markup(index) for index in range(2, 6)]
    version = generated_version(support_bound(first, markups[0], extra=markups[1:]))
    target = static_check_target(version, locale="it-IT")
    assert target.screen_code == "SCR-001"
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_TOO_LARGE"):
        static_check_document(version, target)


def test_the_anchors_of_a_large_generated_mockup_are_bounded_and_deterministic():
    version = generated_version(large_bound())
    anchors = design_review_anchors(version)
    assert anchors == design_review_anchors(version)
    elements = [key for key in anchors if "/" in key]
    total = sum(len(screen.elements) for screen in version.package.prototype.screens)
    assert total == 250 > MAX_ELEMENT_ANCHORS
    assert len(elements) == 5 * 10
    assert [key for key in anchors if key.startswith("SCR-001")] == [
        "SCR-001",
        *(f"SCR-001/ELM-{number:03d}" for number in range(1, 10)),
        "SCR-001/ELM-050",
    ]
    assert [key for key in anchors if "/" not in key] == [f"SCR-{n:03d}" for n in range(1, 6)]
    hosted = design_review_anchors(version, hosted=True, language="en")
    assert len([key for key in hosted if "/" in key]) == 5 * 22 <= MAX_ELEMENT_ANCHORS
    assert hosted["SCR-001/ELM-016"] == (
        f"SCR-001 {ordered_screens(version)[0].title} · ELM-016 "
        + remaining_rows_text(HIDDEN_ROWS, "en")
    )
    assert "SCR-001/ELM-017" not in hosted and "SCR-001/ELM-044" not in hosted
    assert "SCR-001/ELM-045" in hosted


@pytest.mark.parametrize("name", FIXTURES)
def test_a_generated_mockup_below_the_bound_anchors_every_element(name):
    version = design_fixtures.design_version(package=fixture_package(name))
    anchors = design_review_anchors(version)
    expected = [
        key
        for screen in ordered_screens(version)
        for key in (screen.code, *(f"{screen.code}/{item.code}" for item in screen.elements))
    ]
    assert list(anchors) == expected
    assert design_review_anchors(version, hosted=True, language="it") == anchors


@pytest.mark.parametrize("name", FIXTURES)
def test_the_view_of_a_generated_mockup_carries_the_visible_text_in_reading_order(name):
    version = design_fixtures.design_version(package=fixture_package(name))
    view = design_review_view(version)
    screens = ordered_screens(version)
    assert view["entry_screen"] == "SCR-001"
    assert [item["code"] for item in view["screens"]] == [screen.code for screen in screens]
    for item, screen in zip(view["screens"], screens, strict=True):
        assert list(item) == ["code", "title", "state", "visible_text", "elements"]
        assert item["visible_text"] == [element.content for element in screen.elements]
        assert [element["code"] for element in item["elements"]] == [
            element.code for element in screen.elements
        ]
        for element in item["elements"]:
            assert {"code", "kind", "content"} <= set(element)
            assert None not in element.values() and False not in element.values()
            assert element.get("options", ["x"]) != []
            assert element.get("accessible_name") != element["content"]
    targets = [
        element["leads_to"]
        for item in view["screens"]
        for element in item["elements"]
        if "leads_to" in element
    ]
    assert len(targets) == len(version.package.prototype.transitions)
    assert len(json.dumps(view).encode("utf-8")) < VIEW_LIMIT
    assert json.loads(json.dumps(view)) == view


def test_the_hosted_view_reduces_long_tables_like_the_document():
    version = generated_version(large_bound())
    local = design_review_view(version)
    hosted = design_review_view(version, hosted=True, language="it")
    first = hosted["screens"][0]
    codes = [item["code"] for item in first["elements"]]
    assert codes == [
        *(f"ELM-{number:03d}" for number in range(1, 17)),
        *(f"ELM-{number:03d}" for number in range(45, 51)),
    ]
    marker = first["elements"][15]
    assert marker == {
        "code": "ELM-016",
        "kind": "TEXT",
        "content": remaining_rows_text(HIDDEN_ROWS, "it"),
    }
    assert first["visible_text"][15] == marker["content"]
    assert len(local["screens"][0]["elements"]) == 50
    anchors = design_review_anchors(version, hosted=True, language="it")
    assert [key for key in anchors if key.startswith("SCR-001/")] == [
        f"SCR-001/{code}" for code in codes
    ]
    assert len(json.dumps(hosted).encode("utf-8")) < len(json.dumps(local).encode("utf-8"))


def test_a_view_of_about_one_hundred_forty_derived_elements_stays_below_forty_kilobytes():
    markups = [table_markup(index, 38, 3) for index in range(1, 4)]
    version = generated_version(support_bound(markups[0], markups[1], extra=markups[2:]))
    assert sum(len(screen.elements) for screen in version.package.prototype.screens) == 141
    for hosted in (False, True):
        view = design_review_view(version, hosted=hosted, language="it")
        assert len(json.dumps(view).encode("utf-8")) < VIEW_LIMIT


def test_a_finding_keeps_its_anchor_key_next_to_the_readable_location():
    finding = stored_run().findings[0]
    anchored = anchor_finding(finding, "SCR-001/ELM-001")
    snapshot = anchored.to_snapshot()
    keys = list(snapshot)
    assert keys[keys.index("location") + 1] == "anchor_key"
    assert snapshot["anchor_key"] == "SCR-001/ELM-001"
    assert {key: value for key, value in snapshot.items() if key != "anchor_key"} == (
        finding.to_snapshot()
    )
    assert anchored.content_hash == finding.content_hash == STORED_FINDING_HASH
    assert isinstance(anchored, AnchoredSyntheticFinding)
    assert (finding_anchor_key(anchored), finding_anchor_key(finding)) == ("SCR-001/ELM-001", None)
    assert synthetic_finding_from_snapshot(snapshot) == anchored
    assert synthetic_finding_from_snapshot(finding.to_snapshot()) == finding
    assert anchor_finding(finding, "SCR-002").anchor_key == "SCR-002"
    for invalid in (None, "", "ELM-001", "SCR-1", "SCR-001/ELM-001/x", "scr-001", 7):
        with pytest.raises(ValueError, match="anchor key"):
            synthetic_finding_from_snapshot({**finding.to_snapshot(), "anchor_key": invalid})


def test_stored_runs_keep_their_hash_and_anchored_runs_round_trip():
    run = stored_run()
    assert run.content_hash == STORED_RUN_HASH
    assert run.findings[0].content_hash == STORED_FINDING_HASH
    stored = json.loads(json.dumps(run.to_snapshot()))
    assert "anchor_key" not in json.dumps(stored)
    assert design_evaluation_run_from_snapshot(stored) == run
    anchored = stored_run(anchor="SCR-001/ELM-001")
    assert anchored.content_hash != run.content_hash
    reloaded = design_evaluation_run_from_snapshot(json.loads(json.dumps(anchored.to_snapshot())))
    assert reloaded == anchored
    assert finding_anchor_key(reloaded.findings[0]) == "SCR-001/ELM-001"
    tampered = json.loads(json.dumps(anchored.to_snapshot()))
    tampered["responses"][0]["findings"][0]["anchor_key"] = "SCR-002"
    with pytest.raises(ValueError, match="hash is inconsistent"):
        design_evaluation_run_from_snapshot(tampered)
