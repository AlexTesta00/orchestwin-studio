from __future__ import annotations

import asyncio
import hashlib
import os
import selectors
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orchestwin.api import design_review_pins
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_review_pins import (
    PIN_LABEL_LENGTH,
    DesignReviewPinsApplication,
    ReviewPin,
    UnanchoredReviewPin,
    create_design_review_pins_router,
    pin_label,
    review_pins,
)
from orchestwin.artifacts.design_evaluation import (
    anchor_finding,
    create_design_evaluation_run,
    design_review_anchors,
    evaluation_bundle,
    evaluation_document,
    finding_anchor_key,
)
from orchestwin.artifacts.design_evaluation_persistence import (
    FINDINGS,
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    create_finding_validation,
)
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.generated_mockup_document import CONTENT_SECURITY_POLICY
from orchestwin.artifacts.generated_mockup_structure import derive_elements
from orchestwin.artifacts.prototypes import PrototypeElementKind
from orchestwin.evaluation.evaluator import (
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
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.config import DatabaseSettings
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_package_extension import fixture_package
from src.test.python.integration.postgres_isolation import isolated_postgres_settings

OWNER_ID = design_fixtures.OWNER_ID
PROJECT_ID = design_fixtures.PROJECT_ID
RUN_ID = UUID("00000000-0000-4000-8000-000000000e01")
BUNDLE_ID = UUID("00000000-0000-4000-8000-000000000e02")
TWIN_A = UUID("00000000-0000-4000-8000-000000000ea1")
TWIN_B = UUID("00000000-0000-4000-8000-000000000eb2")
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
PATH = f"/projects/{PROJECT_ID}/design/evaluations/{RUN_ID}"
CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="proposer-design-twin-review",
    evaluator_version="1.0.0",
    model_config_ref="c" * 64,
    prompt_version_ref="s22-design-twin-review-v2",
)
CONCERN = "Il filtro dello stato non dice quanti prestiti sono in ritardo."
LONG_CONCERN = (
    "Il riepilogo dei prestiti in ritardo "
    + "non mostra la sede del lettore e mi costringe a cercarla altrove " * 3
).strip()
HIDDEN_CHARACTER = "Il pulsante\x07Invia promemoria è troppo in basso."


def generated_version(version_number: int = 1):
    return design_fixtures.design_version(version_number=version_number, package=fixture_package())


def first_element(version, screen_code: str, *, kind=None) -> str:
    screen = next(item for item in version.package.prototype.screens if item.code == screen_code)
    return next(item.code for item in screen.elements if kind is None or item.kind is kind)


def first_row(version) -> str:
    mockup = version.package.generated_mockup.mockup
    return next(
        item.code
        for item in derive_elements(mockup)
        if item.node_name == "tr" and item.kind is PrototypeElementKind.LIST
    )


def finding(
    version,
    twin_id,
    number,
    *,
    anchor=None,
    location=None,
    summary=CONCERN,
    severity=SyntheticFindingSeverity.MAJOR,
):
    anchors = design_review_anchors(version, hosted=True, language="it")
    plain = create_synthetic_finding(
        finding_id=f"UTF-{number:03d}",
        twin_id=twin_id,
        twin_version=1,
        artifact_id=version.package.prototype.id,
        artifact_version=version.version_number,
        location=location if location is not None else anchors[anchor],
        summary=summary,
        rationale="Al banco devo capire subito cosa fare.",
        criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
        severity=severity,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{version.package.prototype.id}:v{version.version_number}",),
        confidence=0.6,
        recommended_action="Mostra il numero dei prestiti in ritardo.",
        requires_human_validation=True,
        model_config_ref=CONFIGURATION.model_config_ref,
        prompt_version_ref=CONFIGURATION.prompt_version_ref,
    )
    return plain if location is not None else anchor_finding(plain, anchor)


def review_run(version, findings_by_twin, *, run_id=RUN_ID):
    document = evaluation_document(version, language="it", hosted=True)
    bundle = evaluation_bundle(
        version, document, locale="it-IT", created_at=NOW, bundle_id=BUNDLE_ID
    )
    responses = []
    for twin_id, findings in findings_by_twin.items():
        values = {
            "evaluation_run_id": run_id,
            "artifact_bundle_id": bundle.id,
            "artifact_bundle_hash": bundle.content_hash,
            "twin_id": twin_id,
            "twin_version": 1,
            "evaluator": CONFIGURATION,
            "findings": tuple(findings),
            "summary": "Il registro mi aiuta, ma alcuni dettagli mancano.",
            "evidence_gaps": (),
        }
        responses.append(
            UserTwinEvaluationResponse(
                **values,
                completed_at=NOW,
                content_hash=user_twin_evaluation_response_hash(**values),
            )
        )
    return create_design_evaluation_run(
        run_id=run_id,
        owner_user_id=OWNER_ID,
        version=version,
        bundle=bundle,
        responses=responses,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=9),
    )


def scenario_run(version, run_id=RUN_ID):
    first = first_element(version, "SCR-001")
    second = first_element(version, "SCR-002", kind=PrototypeElementKind.HEADING)
    row = first_row(version)
    return review_run(
        version,
        {
            TWIN_B: (
                finding(version, TWIN_B, 1, anchor=f"SCR-001/{row}"),
                finding(version, TWIN_B, 2, location="dom:#f-4c1d2e"),
            ),
            TWIN_A: (
                finding(
                    version,
                    TWIN_A,
                    1,
                    anchor=f"SCR-001/{first}",
                    summary=LONG_CONCERN,
                    severity=SyntheticFindingSeverity.CRITICAL,
                ),
                finding(version, TWIN_A, 2, anchor="SCR-002"),
                finding(version, TWIN_A, 3, anchor=f"SCR-001/{first}"),
                finding(
                    version,
                    TWIN_A,
                    4,
                    anchor=f"SCR-002/{second}",
                    summary=HIDDEN_CHARACTER,
                    severity=SyntheticFindingSeverity.MINOR,
                ),
                finding(version, TWIN_A, 5, location="SCR-003 Dettaglio del prestito"),
            ),
        },
        run_id=run_id,
    )


def decision(twin_id, finding_id, choice, sequence, run_id=RUN_ID):
    return create_finding_validation(
        evaluation_run_id=run_id,
        twin_id=twin_id,
        finding_id=finding_id,
        sequence_number=sequence,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        decision=choice,
        note=None,
        decided_at=NOW + timedelta(minutes=sequence),
    )


DECISIONS = (
    decision(TWIN_A, "UTF-003", FindingDecision.OWNER_DISMISSED, 1),
    decision(TWIN_A, "UTF-002", FindingDecision.OWNER_DISMISSED, 2),
    decision(TWIN_A, "UTF-002", FindingDecision.OWNER_CONFIRMED, 3),
    decision(TWIN_B, "UTF-001", FindingDecision.OWNER_CONFIRMED, 4),
)


def expected_pins(version):
    first = first_element(version, "SCR-001")
    second = first_element(version, "SCR-002", kind=PrototypeElementKind.HEADING)
    row = first_row(version)
    return (
        (
            ReviewPin(
                number=1,
                element_code=first,
                screen_code="SCR-001",
                twin_id=TWIN_A,
                finding_id="UTF-001",
                severity="critical",
                label=LONG_CONCERN[: PIN_LABEL_LENGTH - 1].rstrip() + "…",
            ),
            ReviewPin(
                number=3,
                element_code=second,
                screen_code="SCR-002",
                twin_id=TWIN_A,
                finding_id="UTF-004",
                severity="minor",
                label="Il pulsante Invia promemoria è troppo in basso.",
            ),
            ReviewPin(
                number=5,
                element_code=row,
                screen_code="SCR-001",
                twin_id=TWIN_B,
                finding_id="UTF-001",
                severity="major",
                label=CONCERN,
            ),
        ),
        (
            UnanchoredReviewPin(
                number=2, screen_code="SCR-002", twin_id=TWIN_A, finding_id="UTF-002"
            ),
            UnanchoredReviewPin(
                number=4, screen_code="SCR-003", twin_id=TWIN_A, finding_id="UTF-005"
            ),
            UnanchoredReviewPin(
                number=6, screen_code="SCR-001", twin_id=TWIN_B, finding_id="UTF-002"
            ),
        ),
    )


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class MemoryRuns:
    runs: ClassVar[dict] = {}

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, run_id):
        run = MemoryRuns.runs.get(run_id)
        if run is None or (run.project_id, run.owner_user_id) != (project_id, self.owner_user_id):
            return None
        return run


class MemoryVersions:
    versions: ClassVar[dict] = {}

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, version_id):
        version = MemoryVersions.versions.get(version_id)
        return version if version is not None and version.project_id == project_id else None


class MemoryValidations:
    items: ClassVar[tuple] = ()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def current(self, *, project_id):
        return tuple(item for item in MemoryValidations.items if item.project_id == project_id)


def runtime(*, database=True):
    return SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=lambda: FakeSession())
        if database
        else None
    )


def client(monkeypatch, *, runs=(), versions=(), validations=(), database=True):
    MemoryRuns.runs = {run.id: run for run in runs}
    MemoryVersions.versions = {version.id: version for version in versions}
    MemoryValidations.items = tuple(validations)
    monkeypatch.setattr(design_review_pins, "SqlAlchemyDesignEvaluationRepository", MemoryRuns)
    monkeypatch.setattr(design_review_pins, "SqlAlchemyDesignPackageRepository", MemoryVersions)
    monkeypatch.setattr(
        design_review_pins, "SqlAlchemyFindingValidationRepository", MemoryValidations
    )
    server = FastAPI()
    server.state.application_runtime = runtime(database=database)
    server.include_router(create_design_review_pins_router())
    server.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER_ID)
    return TestClient(server)


def test_pins_follow_the_twins_of_the_run_then_the_findings_without_dismissed_ones():
    version = generated_version()
    run = scenario_run(version)
    assert [response.twin_id for response in run.responses] == [TWIN_A, TWIN_B]
    dismissed = frozenset({(RUN_ID, TWIN_A, "UTF-003")})
    result = review_pins(run, version, dismissed)
    pins, unanchored = expected_pins(version)
    assert result.design_version_id == version.id
    assert result.pins == pins
    assert result.unanchored == unanchored
    everything = review_pins(run, version)
    assert [item.number for item in everything.pins] == [1, 3, 4, 6]
    assert [item.number for item in everything.unanchored] == [2, 5, 7]
    assert [item.finding_id for item in everything.pins] == [
        "UTF-001",
        "UTF-003",
        "UTF-004",
        "UTF-001",
    ]


def test_a_pin_label_is_the_concern_in_at_most_one_hundred_twenty_characters():
    version = generated_version()
    first = first_element(version, "SCR-001")
    short = finding(version, TWIN_A, 1, anchor=f"SCR-001/{first}")
    assert pin_label(short) == CONCERN
    exact = "x" * PIN_LABEL_LENGTH
    assert pin_label(finding(version, TWIN_A, 1, anchor="SCR-001", summary=exact)) == exact
    cut = pin_label(finding(version, TWIN_A, 1, anchor="SCR-001", summary=LONG_CONCERN))
    assert len(cut) == PIN_LABEL_LENGTH and cut.endswith("…")
    hidden = finding(version, TWIN_A, 1, anchor="SCR-001", summary="\x07\x08")
    assert pin_label(hidden) == "UTF-001"


def test_the_router_answers_the_pins_of_the_contract(monkeypatch):
    version = generated_version()
    http = client(
        monkeypatch, runs=(scenario_run(version),), versions=(version,), validations=DECISIONS
    )
    response = http.get(f"{PATH}/pins")
    assert response.status_code == 200
    pins, unanchored = expected_pins(version)
    assert response.json() == {
        "design_version_id": str(version.id),
        "pins": [
            {
                "number": item.number,
                "element_code": item.element_code,
                "screen_code": item.screen_code,
                "twin_id": str(item.twin_id),
                "finding_id": item.finding_id,
                "severity": item.severity,
                "label": item.label,
            }
            for item in pins
        ],
        "unanchored": [
            {
                "number": item.number,
                "screen_code": item.screen_code,
                "twin_id": str(item.twin_id),
                "finding_id": item.finding_id,
            }
            for item in unanchored
        ],
    }


def test_the_review_document_draws_the_numbered_pins_on_the_mockup(monkeypatch):
    version = generated_version()
    http = client(
        monkeypatch, runs=(scenario_run(version),), versions=(version,), validations=DECISIONS
    )
    response = http.get(f"{PATH}/document")
    assert response.status_code == 200
    payload = response.json()
    mockup = version.package.generated_mockup.mockup
    assert list(payload) == [
        "html",
        "content_hash",
        "source",
        "alternative_id",
        "title",
        "entry_screen",
        "screens",
    ]
    html = payload["html"]
    assert payload["content_hash"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert payload["source"] == "review"
    assert payload["alternative_id"] == str(mockup.design_alternative_id)
    assert payload["title"] == mockup.title
    assert payload["entry_screen"] == "SCR-001"
    assert payload["screens"] == [
        {"code": screen.code, "title": screen.title, "state": screen.state.value}
        for screen in mockup.screens
    ]
    assert CONTENT_SECURITY_POLICY in html
    assert "<script" not in html.lower()
    assert html.count('class="ot-pin"') == 3
    for number in (1, 3, 5):
        assert f">{number}</span>" in html
    assert 'aria-label="Il pulsante Invia promemoria è troppo in basso."' in html
    row = first_row(version)
    cell = html[html.index(f'<tr data-elm="{row}">') :]
    assert 'class="ot-pin"' in cell[: cell.index("</td>")]
    assert '<section class="ot-screen" id="SCR-001" data-state="DEFAULT"' in html
    assert http.get(f"{PATH}/document").json() == payload


def test_the_review_document_opens_the_requested_screen(monkeypatch):
    version = generated_version()
    http = client(monkeypatch, runs=(scenario_run(version),), versions=(version,))
    payload = http.get(f"{PATH}/document", params={"entry_screen": "SCR-002"}).json()
    assert payload["entry_screen"] == "SCR-002"
    html = payload["html"]
    opened = html[html.index('id="SCR-002"') :]
    assert opened[: opened.index(">")].endswith(" data-entry")
    assert html.count(" data-entry") == 1
    missing = http.get(f"{PATH}/document", params={"entry_screen": "SCR-009"})
    assert missing.status_code == 422
    assert missing.json() == {"detail": {"code": "ENTRY_SCREEN_NOT_FOUND"}}
    assert http.get(f"{PATH}/document", params={"entry_screen": "home"}).status_code == 422


def test_a_review_needs_an_owned_run_and_a_generated_mockup(monkeypatch):
    version = generated_version()
    declarative = design_fixtures.design_version()
    other = uuid4()
    plain_run = review_run(declarative, {TWIN_A: ()}, run_id=other)
    http = client(monkeypatch, runs=(scenario_run(version), plain_run), versions=(declarative,))
    for suffix in ("pins", "document"):
        missing = http.get(f"/projects/{PROJECT_ID}/design/evaluations/{uuid4()}/{suffix}")
        assert missing.status_code == 404
        assert missing.json() == {"detail": {"code": "DESIGN_EVALUATION_NOT_FOUND"}}
        foreign = http.get(f"/projects/{uuid4()}/design/evaluations/{RUN_ID}/{suffix}")
        assert foreign.json() == {"detail": {"code": "DESIGN_EVALUATION_NOT_FOUND"}}
        lost = http.get(f"{PATH}/{suffix}")
        assert lost.json() == {"detail": {"code": "DESIGN_EVALUATION_NOT_FOUND"}}
        refused = http.get(f"/projects/{PROJECT_ID}/design/evaluations/{other}/{suffix}")
        assert refused.status_code == 409
        assert refused.json() == {"detail": {"code": "GENERATED_MOCKUP_REQUIRED"}}
    offline = client(monkeypatch, database=False)
    unavailable = offline.get(f"{PATH}/pins")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": {"code": "DATABASE_UNAVAILABLE"}}


def test_the_router_registers_the_pins_and_the_document_of_a_review():
    router = create_design_review_pins_router()
    assert sorted((route.path, *sorted(route.methods)) for route in router.routes) == [
        ("/projects/{project_id}/design/evaluations/{run_id}/document", "GET"),
        ("/projects/{project_id}/design/evaluations/{run_id}/pins", "GET"),
    ]


def run_scenario(coroutine):
    if sys.platform == "win32":
        return asyncio.run(
            coroutine,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coroutine)


@pytest.fixture
def database():
    url = os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit disposable design database required")
    settings = DatabaseSettings(url=SecretStr(url), _env_file=None)
    with isolated_postgres_settings(settings) as scoped:
        yield scoped


async def seed_project(db) -> None:
    brief = create_project_brief(description="Una biblioteca di quartiere gestisce i prestiti.")
    async with db.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=OWNER_ID,
                email_normalized=f"{OWNER_ID}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=PROJECT_ID,
                owner_user_id=OWNER_ID,
                display_name="Synthetic review pins",
                mode="GREENFIELD_GENERATION",
                current_brief_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            ProjectBriefVersionRecord(
                id=uuid4(),
                project_id=PROJECT_ID,
                version_number=1,
                schema_version=brief.SCHEMA_VERSION,
                content=brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=OWNER_ID,
                created_at=NOW,
            )
        )


@pytest.mark.integration
def test_postgresql_keeps_the_anchor_keys_and_serves_the_pins(database):
    version = generated_version()
    evaluation = scenario_run(version)

    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_project(db)
            async with db.session_factory() as session, session.begin():
                appended = await SqlAlchemyDesignPackageRepository(
                    session, owner_user_id=OWNER_ID
                ).append(version)
                assert appended.value == "APPENDED"
                written = await SqlAlchemyDesignEvaluationRepository(
                    session, owner_user_id=OWNER_ID
                ).create(evaluation)
                assert written is DesignEvaluationWriteStatus.WRITTEN
            async with db.session_factory() as session, session.begin():
                dismissal = await SqlAlchemyFindingValidationRepository(
                    session, owner_user_id=OWNER_ID
                ).append(
                    project_id=PROJECT_ID,
                    evaluation_run_id=RUN_ID,
                    twin_id=TWIN_A,
                    finding_id="UTF-003",
                    decision=FindingDecision.OWNER_DISMISSED,
                    note=None,
                    decided_at=NOW + timedelta(minutes=1),
                )
                assert dismissal.status.value == "WRITTEN"
            async with db.session_factory() as session:
                stored = await SqlAlchemyDesignEvaluationRepository(
                    session, owner_user_id=OWNER_ID
                ).get(project_id=PROJECT_ID, run_id=RUN_ID)
                rows = (
                    await session.execute(
                        sa.select(FINDINGS.c.finding_snapshot).where(
                            FINDINGS.c.evaluation_run_id == RUN_ID
                        )
                    )
                ).scalars()
                anchored_rows = sum("anchor_key" in row for row in rows)
            assert stored == evaluation
            assert [finding_anchor_key(item) for item in stored.findings] == [
                finding_anchor_key(item) for item in evaluation.findings
            ]
            assert anchored_rows == 5
            application = DesignReviewPinsApplication(SimpleNamespace(database_runtime=db))
            pins = await application.pins(
                owner_user_id=OWNER_ID, project_id=PROJECT_ID, run_id=RUN_ID
            )
            assert (pins.pins, pins.unanchored) == expected_pins(version)
            document = await application.document(
                owner_user_id=OWNER_ID,
                project_id=PROJECT_ID,
                run_id=RUN_ID,
                entry_screen="SCR-002",
            )
            assert document.entry_screen == "SCR-002"
            assert document.html.count('class="ot-pin"') == len(pins.pins)
            with pytest.raises(HTTPException) as refusal:
                await application.pins(owner_user_id=uuid4(), project_id=PROJECT_ID, run_id=RUN_ID)
            assert refusal.value.status_code == 404
            assert refusal.value.detail == {"code": "DESIGN_EVALUATION_NOT_FOUND"}
        finally:
            await db.dispose()

    run_scenario(scenario())
