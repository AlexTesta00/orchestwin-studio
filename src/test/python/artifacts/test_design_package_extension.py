from __future__ import annotations

import asyncio
import json
import os
import selectors
import sys
from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from functools import cache
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from orchestwin.artifacts.bound_mockups import (
    BoundGeneratedMockup,
    create_bound_mockup,
    markup_requirement_codes,
)
from orchestwin.artifacts.design_packages import (
    MAX_OWNER_ASSERTION_LENGTH,
    MAX_OWNER_ASSERTIONS,
    DesignExplorationPackage,
    DesignGrounding,
    DesignPackageVersion,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.design_persistence import (
    PACKAGE_VERSIONS,
    SqlAlchemyDesignDiffRepository,
    SqlAlchemyDesignPackageRepository,
    design_diff_from_record,
    design_diff_to_record,
    design_package_version_from_record,
    design_package_version_to_record,
)
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    DesignRevisionStatus,
)
from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignRevisionDecision,
    decide_design_revision,
    propose_design_revision,
)
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.generated_mockups import GeneratedMockupError
from orchestwin.artifacts.visual_catalog import VisualChoices
from orchestwin.artifacts.visual_language import create_visual_language
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.config import DatabaseSettings
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from orchestwin.projects.requirements_primitives import canonical_uuid_tuple
from src.test.python.integration.postgres_isolation import isolated_postgres_settings

from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    critique,
    design_alternative,
    design_package,
    design_version,
    prototype,
    requirements_version,
)
from .test_generated_mockup_support import (
    BASE_FIRST,
    BASE_SECOND,
    DASHBOARD,
    FIXTURES,
    LIGHT_CHOICES,
    build,
    fixture_codes,
    fixture_data,
    fixture_mockup,
    requirement_ids,
)

ASSERTIONS = (
    "Il pulsante principale resta in alto a destra.",
    "La tabella dei prestiti mostra sempre la data di scadenza.",
)
VERDICTS = (
    ("Utile, con riserve", "Trovo subito i prestiti in ritardo, ma vorrei filtrare per sede."),
    ("Chiaro e rapido", "Capisco in un attimo cosa devo fare e quale pulsante premere."),
)
NO_VERDICTS = (None, None)
GROUNDED_CODES = tuple(f"REQ-{number:03d}" for number in range(1, 10))
WRAPPED_FIRST = '<div class="shell" data-req="REQ-009">' + BASE_FIRST + "</div>"
PACKAGE_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "grounding",
        "alternatives",
        "critiques",
        "recommended_alternative_id",
        "owner_selected_alternative_id",
        "prototype",
        "concerns",
        "open_questions",
    }
)
STORED_PACKAGE_HASHES = (
    ({}, "7621da5f47d9695599f509156110d040ad218144f45e591ae6a49f4dc0c3cf0c"),
    ({"selected": False}, "7c073579785e78e495650d950fa366a62e2dbf3c62b2a0f41981b26b93de76e3"),
    (
        {"include_prototype": False},
        "2fda7d1f9a4da7002cbcfd876cd4ece43cf029f7c50b8699010ccd32bd7bd241",
    ),
)
STORED_CRITIQUE_HASHES = (
    (1, "f36e3b65b8086c9960fcba89b7fabd76b1c5e2cd9721020ac66ced053be83a43"),
    (2, "19cc4005506710ed70fc3b60ee99be8b52bdd0940ef5740882c0e9c0bf4ecc6f"),
)
GUEST_LIST_DESIGN = (
    Path(__file__).resolve().parents[1] / "knowledge" / "data" / "guest_list" / "design.json"
)
LARGE_SCREENS = 5
LARGE_ROWS = 41
INTEGRATION_DIFF_ID = UUID("00000000-0000-4000-8000-000000000b01")
INTEGRATION_VERSION_ID = UUID("00000000-0000-4000-8000-000000000b02")


def fixture_choices(name: str) -> VisualChoices:
    choices = fixture_data(name)["choices"]
    assert isinstance(choices, VisualChoices)
    return choices


def fixture_alternative_id(name: str = DASHBOARD) -> UUID:
    identifier = fixture_data(name)["design_alternative_id"]
    assert isinstance(identifier, UUID)
    return identifier


@cache
def fixture_bound(name: str = DASHBOARD) -> BoundGeneratedMockup:
    return create_bound_mockup(
        mockup=fixture_mockup(name),
        requirement_ids_by_code=requirement_ids(fixture_codes(name)),
    )


def support_bound(
    first: str = BASE_FIRST,
    second: str = BASE_SECOND,
    **options: object,
) -> BoundGeneratedMockup:
    mockup = build(first, second, **options)
    return create_bound_mockup(
        mockup=mockup,
        requirement_ids_by_code=requirement_ids(markup_requirement_codes(mockup)),
    )


def large_markup(index: int, *, changed: bool = False) -> str:
    target = "SCR-001" if index == LARGE_SCREENS else f"SCR-{index + 1:03d}"
    rows = "".join(
        f"<tr><td>Lettore {index}.{row}</td><td>Volume {row}</td>"
        f"<td>{'Rinnovato' if changed and row == 1 else f'{row} ottobre'}</td></tr>"
        for row in range(1, LARGE_ROWS + 1)
    )
    items = "".join(
        f"<li>Promemoria {index}.{item} inviato ai lettori della sede centrale.</li>"
        for item in range(1, 6)
    )
    return (
        f'<main data-req="REQ-00{index}"><h1>Registro della sede {index}</h1>'
        "<p>Controlla i prestiti aperti della sede e invia un promemoria ai lettori in ritardo.</p>"
        '<table><thead><tr><th scope="col">Lettore</th><th scope="col">Titolo</th>'
        '<th scope="col">Scadenza</th></tr></thead>'
        f"<tbody>{rows}</tbody></table><ul>{items}</ul>"
        f'<a href="#{target}">Prosegui</a></main>'
    )


def large_bound(*, changed_screen: int | None = None) -> BoundGeneratedMockup:
    markups = [
        large_markup(index, changed=index == changed_screen)
        for index in range(1, LARGE_SCREENS + 1)
    ]
    return support_bound(markups[0], markups[1], extra=markups[2:])


def extended_grounding(*codes: str) -> DesignGrounding:
    base = create_design_grounding(requirements_version())
    identifiers = {*base.requirement_ids, *requirement_ids(codes or GROUNDED_CODES).values()}
    return replace(
        base,
        requirement_ids=canonical_uuid_tuple(
            identifiers,
            label="extended grounding requirement IDs",
            require_items=True,
        ),
    )


def selected_alternative(alternative_id: UUID, choices: VisualChoices | None = None):
    language = create_visual_language(
        choices=choices or LIGHT_CHOICES,
        product_name="Registro prestiti",
        rationale="Una dashboard civica e ordinata aiuta il banco prestiti a lavorare in fretta.",
    )
    return replace(design_alternative(index=2), id=alternative_id, visual_language=language)


def with_verdict(value, verdict: tuple[str, str] | None):
    if verdict is None:
        return value
    return replace(value, verdict=verdict[0], quote=verdict[1])


def extended_package(
    bound: BoundGeneratedMockup | None,
    *,
    alternative_id: UUID | None = None,
    choices: VisualChoices | None = None,
    assertions: Iterable[str] = ASSERTIONS,
    verdicts: tuple[tuple[str, str] | None, tuple[str, str] | None] = VERDICTS,
    grounding: DesignGrounding | None = None,
) -> DesignExplorationPackage:
    selected = (
        bound.design_alternative_id
        if bound is not None
        else alternative_id or fixture_alternative_id()
    )
    first, second = verdicts
    base = design_package()
    return create_design_exploration_package(
        project_id=PROJECT_ID,
        grounding=grounding or extended_grounding(),
        alternatives=(design_alternative(index=1), selected_alternative(selected, choices)),
        critiques=(
            with_verdict(critique(index=1), first),
            with_verdict(replace(critique(index=2), design_alternative_id=selected), second),
        ),
        recommended_alternative_id=ALTERNATIVE_ONE_ID,
        owner_selected_alternative_id=selected,
        prototype=None if bound is None else bound.prototype(),
        concerns=base.concerns,
        open_questions=base.open_questions,
        generated_mockup=bound,
        owner_assertions=assertions,
    )


def fixture_package(name: str = DASHBOARD, **options) -> DesignExplorationPackage:
    return extended_package(fixture_bound(name), choices=fixture_choices(name), **options)


def plain_package(**options) -> DesignExplorationPackage:
    return extended_package(None, assertions=(), verdicts=NO_VERDICTS, **options)


def extended_version(
    package: DesignExplorationPackage,
    *,
    version_number: int = 1,
) -> DesignPackageVersion:
    return design_version(version_number=version_number, package=package)


def through_json(record: dict[str, object], column: str) -> dict[str, object]:
    return {**record, column: json.loads(json.dumps(record[column]))}


def stored_snapshot(package: DesignExplorationPackage) -> dict:
    return json.loads(package.canonical_json())


def selected_entry(snapshot: dict) -> dict:
    return next(
        item
        for item in snapshot["alternatives"]
        if item["id"] == snapshot["owner_selected_alternative_id"]
    )


@pytest.mark.parametrize(("options", "expected"), STORED_PACKAGE_HASHES)
def test_packages_built_from_the_existing_fixtures_keep_their_hash(
    options: dict[str, bool],
    expected: str,
) -> None:
    package = design_package(**options)
    snapshot = package.to_snapshot()

    assert package.content_hash == expected
    assert package.generated_mockup is None
    assert package.owner_assertions == ()
    assert set(snapshot) == PACKAGE_KEYS
    assert design_package_from_snapshot(json.loads(package.canonical_json())).content_hash == (
        expected
    )


@pytest.mark.parametrize(("index", "expected"), STORED_CRITIQUE_HASHES)
def test_critiques_built_from_the_existing_fixtures_keep_their_hash(
    index: int,
    expected: str,
) -> None:
    value = critique(index=index)

    assert value.content_hash == expected
    assert (value.verdict, value.quote) == (None, None)
    assert {"verdict", "quote"}.isdisjoint(value.to_snapshot())


def test_a_design_version_stored_by_the_studio_reloads_with_its_recorded_hash() -> None:
    stored = json.loads(GUEST_LIST_DESIGN.read_text(encoding="utf-8"))
    record = {
        **{key: value for key, value in stored.items() if key != "package"},
        "schema_version": 1,
        "package_snapshot": stored["package"],
    }

    package = design_package_from_snapshot(stored["package"])
    version = design_package_version_from_record(record)

    assert package.to_snapshot() == stored["package"]
    assert package.content_hash == stored["content_hash"]
    assert version.package == package
    assert version.content_hash == stored["content_hash"]
    assert package.generated_mockup is None
    assert package.owner_assertions == ()
    assert all((item.verdict, item.quote) == (None, None) for item in package.critiques)


@pytest.mark.parametrize("name", FIXTURES)
def test_a_package_carries_the_generated_mockup_the_assertions_and_the_verdicts(
    name: str,
) -> None:
    bound = fixture_bound(name)

    package = fixture_package(name)
    snapshot = package.to_snapshot()

    assert package.generated_mockup == bound
    assert package.prototype == bound.prototype()
    assert package.owner_selected_alternative_id == bound.design_alternative_id
    assert package.ready_for_gate is True
    assert package.owner_assertions == ASSERTIONS
    assert set(snapshot) == PACKAGE_KEYS | {"generated_mockup", "owner_assertions"}
    assert snapshot["generated_mockup"] == bound.to_snapshot()
    assert snapshot["owner_assertions"] == list(ASSERTIONS)
    assert [(item.verdict, item.quote) for item in package.critiques] == list(VERDICTS)
    assert [(item["verdict"], item["quote"]) for item in snapshot["critiques"]] == list(VERDICTS)


def test_each_addition_enters_the_snapshot_only_when_it_has_a_value() -> None:
    plain = plain_package()
    only_mockup = fixture_package(assertions=(), verdicts=NO_VERDICTS)
    only_assertions = extended_package(None, verdicts=NO_VERDICTS)
    only_verdicts = extended_package(None, assertions=())

    assert set(plain.to_snapshot()) == PACKAGE_KEYS
    assert set(only_mockup.to_snapshot()) == PACKAGE_KEYS | {"generated_mockup"}
    assert set(only_assertions.to_snapshot()) == PACKAGE_KEYS | {"owner_assertions"}
    assert set(only_verdicts.to_snapshot()) == PACKAGE_KEYS
    assert all(
        {"verdict", "quote"}.isdisjoint(item)
        for package in (plain, only_mockup, only_assertions)
        for item in package.to_snapshot()["critiques"]
    )
    assert all(
        {"verdict", "quote"} <= set(item) for item in only_verdicts.to_snapshot()["critiques"]
    )
    assert len({package.content_hash for package in (plain, only_mockup, only_assertions)}) == 3


def test_a_generated_mockup_requires_an_owner_selection_and_a_prototype() -> None:
    package = fixture_package()

    with pytest.raises(ValueError, match="requires an owner-selected alternative and a prototype"):
        replace(package, prototype=None)

    with pytest.raises(ValueError, match="requires an owner-selected alternative and a prototype"):
        replace(package, owner_selected_alternative_id=None, prototype=None)


def test_a_generated_mockup_must_belong_to_the_selected_alternative() -> None:
    package = fixture_package()

    with pytest.raises(ValueError, match="must represent the owner-selected alternative"):
        replace(package, owner_selected_alternative_id=ALTERNATIVE_ONE_ID, prototype=prototype())


def test_the_selected_alternative_of_a_generated_mockup_needs_a_visual_language() -> None:
    package = fixture_package()
    alternatives = tuple(
        replace(item, visual_language=None)
        if item.id == package.owner_selected_alternative_id
        else item
        for item in package.alternatives
    )

    with pytest.raises(ValueError, match="visual language of the owner-selected alternative"):
        replace(package, alternatives=alternatives)


def test_every_requirement_of_the_map_belongs_to_the_grounding() -> None:
    bound = support_bound(WRAPPED_FIRST)
    package = extended_package(bound)
    narrow = extended_grounding(*(code for code in GROUNDED_CODES if code != "REQ-009"))

    assert bound.requirement_codes == ("REQ-001", "REQ-002", "REQ-009")
    assert package.generated_mockup == bound

    with pytest.raises(ValueError, match="generated mockup requirement IDs contain unknown"):
        replace(package, grounding=narrow)


def test_the_prototype_must_be_the_one_derived_from_the_generated_mockup() -> None:
    package = fixture_package()
    other = support_bound()

    with pytest.raises(ValueError, match="prototype derived from the generated mockup"):
        replace(package, prototype=replace(package.prototype, title="Un altro prototipo"))

    with pytest.raises(ValueError, match="bound generated mockup"):
        replace(package, generated_mockup=package.generated_mockup.mockup)

    with pytest.raises(ValueError, match="must represent the owner-selected alternative"):
        replace(package, generated_mockup=other)


def test_owner_assertions_are_normalized_unique_and_keep_the_order_of_the_owner() -> None:
    package = extended_package(
        None,
        assertions=("  Zeta   resta in alto ", "Alfa segue Zeta", "Beta chiude"),
        verdicts=NO_VERDICTS,
    )

    assert package.owner_assertions == ("Zeta resta in alto", "Alfa segue Zeta", "Beta chiude")
    assert package.to_snapshot()["owner_assertions"] == list(package.owner_assertions)


def test_owner_assertions_respect_their_length_and_count() -> None:
    longest = "a" * MAX_OWNER_ASSERTION_LENGTH
    many = tuple(f"Asserzione numero {index}" for index in range(1, MAX_OWNER_ASSERTIONS + 1))

    assert extended_package(None, assertions=(longest,)).owner_assertions == (longest,)
    assert len(extended_package(None, assertions=many).owner_assertions) == MAX_OWNER_ASSERTIONS

    for assertions, message in (
        (("a" * (MAX_OWNER_ASSERTION_LENGTH + 1),), "exceeds maximum length"),
        ((*many, "Asserzione numero 21"), "at most 20 owner assertions"),
        (("Resta in alto", "  Resta   in alto "), "must be unique"),
        (("   ",), "must not be empty"),
        (("Resta\x00 in alto",), "control characters"),
        (("Resta\x9b in alto",), "control characters"),
    ):
        with pytest.raises(ValueError, match=message):
            extended_package(None, assertions=assertions, verdicts=NO_VERDICTS)


def test_the_constructor_rejects_assertions_that_are_not_in_their_stored_form() -> None:
    package = extended_package(None)

    for assertions in ((" Resta in alto",), ["Resta in alto"]):
        with pytest.raises(ValueError, match="owner assertions must be normalized"):
            replace(package, owner_assertions=assertions)


@pytest.mark.parametrize("name", FIXTURES)
def test_the_stored_snapshot_reloads_to_the_same_package_and_hash(name: str) -> None:
    package = fixture_package(name)
    stored = stored_snapshot(package)

    restored = design_package_from_snapshot(stored)

    assert restored == package
    assert restored.to_snapshot() == stored
    assert restored.content_hash == package.content_hash
    assert restored.generated_mockup == fixture_bound(name)


def test_the_snapshot_rejects_empty_values_written_for_the_additions() -> None:
    stored = stored_snapshot(fixture_package())
    without_quote = [
        {key: value for key, value in item.items() if key != "quote"}
        for item in stored["critiques"]
    ]
    null_verdicts = [{**item, "verdict": None, "quote": None} for item in stored["critiques"]]

    for payload in (
        {**stored, "generated_mockup": None},
        {**stored, "owner_assertions": []},
    ):
        with pytest.raises(ValueError, match="Design Package snapshot is not canonical"):
            design_package_from_snapshot(payload)

    with pytest.raises(ValueError, match="Design critique snapshot is not canonical"):
        design_package_from_snapshot({**stored, "critiques": null_verdicts})

    with pytest.raises(ValueError, match="verdict and quote must be present together"):
        design_package_from_snapshot({**stored, "critiques": without_quote})

    with pytest.raises(ValueError, match="owner assertions"):
        design_package_from_snapshot({**stored, "owner_assertions": None})


def test_the_snapshot_reads_the_mockup_with_the_tokens_of_the_selected_alternative() -> None:
    stored = stored_snapshot(fixture_package())
    del selected_entry(stored)["visual_language"]["tokens"]["--vl-color-primary"]

    with pytest.raises(GeneratedMockupError, match=r"^STYLES_CUSTOM_PROPERTY"):
        design_package_from_snapshot(stored)


def test_a_snapshot_with_a_mockup_needs_a_selected_alternative_with_a_visual_language() -> None:
    stored = stored_snapshot(fixture_package())
    without_selection = {**stored, "owner_selected_alternative_id": None, "prototype": None}
    without_language = stored_snapshot(fixture_package())
    del selected_entry(without_language)["visual_language"]

    for payload in (without_selection, without_language):
        with pytest.raises(ValueError, match="visual language of the owner-selected alternative"):
            design_package_from_snapshot(payload)


def test_the_snapshot_validates_the_mockup_and_its_map_like_the_output_of_a_model() -> None:
    stored = stored_snapshot(fixture_package())
    mockup = stored["generated_mockup"]["mockup"]
    identifiers = stored["generated_mockup"]["requirement_ids_by_code"]
    unsafe = json.loads(json.dumps(stored))
    unsafe["generated_mockup"]["mockup"]["screens"][0]["markup"] = (
        mockup["screens"][0]["markup"] + '<a href="https://example.invalid">Esci</a>'
    )
    foreign = json.loads(json.dumps(stored))
    foreign["generated_mockup"]["requirement_ids_by_code"]["REQ-006"] = str(uuid4())
    swapped = json.loads(json.dumps(stored))
    swapped["generated_mockup"]["requirement_ids_by_code"].update(
        {"REQ-001": identifiers["REQ-002"], "REQ-002": identifiers["REQ-001"]}
    )

    with pytest.raises(GeneratedMockupError, match=r"^LINK_TARGET"):
        design_package_from_snapshot(unsafe)

    with pytest.raises(ValueError, match="generated mockup requirement IDs contain unknown"):
        design_package_from_snapshot(foreign)

    with pytest.raises(ValueError, match="prototype derived from the generated mockup"):
        design_package_from_snapshot(swapped)


def test_a_mockup_with_two_hundred_fifty_derived_elements_fits_every_limit() -> None:
    bound = large_bound()
    package = extended_package(bound)
    elements = [element for screen in package.prototype.screens for element in screen.elements]
    version = extended_version(package)
    record = through_json(design_package_version_to_record(version), "package_snapshot")
    changed = extended_package(large_bound(changed_screen=3))

    proposal = propose_design_revision(
        diff_id=uuid4(),
        owner_user_id=OWNER_ID,
        base_version=version,
        proposed_package=changed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert len(elements) == 250
    assert [element.code for element in elements[:2]] == ["ELM-001", "ELM-002"]
    assert elements[-1].code == "ELM-250"
    assert len(package.prototype.transitions) == LARGE_SCREENS
    assert design_package_from_snapshot(stored_snapshot(package)) == package
    assert design_package_version_from_record(record) == version
    assert proposal.diff is not None
    assert [
        (change.artifact_kind, change.kind, (change.after or {}).get("code"))
        for change in proposal.diff.changes
    ] == [
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.REPLACE, None),
        (DesignArtifactKind.GENERATED_SCREEN, DesignChangeKind.REPLACE, "SCR-003"),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.REPLACE, "PRT-001"),
    ]
    diff_record = through_json(design_diff_to_record(proposal.diff), "diff_snapshot")
    assert design_diff_from_record(diff_record) == proposal.diff


def test_the_revision_service_keeps_the_additions_with_the_in_memory_repositories() -> None:
    from .test_design_revision_application import (
        _DiffRepository,
        _PackageRepository,
        _UnitOfWork,
        service,
    )

    base = extended_version(plain_package())
    proposed = fixture_package()
    packages = _PackageRepository(base)
    diffs = _DiffRepository()
    revisions = service(_UnitOfWork(packages, diffs))

    proposal = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed,
        )
    )
    assert proposal.status is DesignRevisionStatus.CREATED
    assert proposal.diff is not None
    decision = asyncio.run(
        revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=DesignRevisionDecision.APPROVE,
            reason="Il mockup generato rispetta le asserzioni del proprietario.",
        )
    )

    assert decision.status is DesignRevisionStatus.APPLIED
    assert decision.version is not None
    assert decision.version.package == proposed
    assert packages.value == decision.version
    assert {(change.artifact_kind, change.kind) for change in proposal.diff.changes} >= {
        (DesignArtifactKind.GENERATED_MOCKUP, DesignChangeKind.ADD),
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.ADD),
        (DesignArtifactKind.OWNER_ASSERTION, DesignChangeKind.ADD),
        (DesignArtifactKind.CRITIQUE_VERDICT, DesignChangeKind.ADD),
        (DesignArtifactKind.CRITIQUE, DesignChangeKind.REPLACE),
    }
    version_record = through_json(
        design_package_version_to_record(decision.version), "package_snapshot"
    )
    diff_record = through_json(design_diff_to_record(diffs.value), "diff_snapshot")
    assert design_package_version_from_record(version_record) == decision.version
    assert design_diff_from_record(diff_record) == diffs.value


def run(coroutine):
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
                display_name="Synthetic design package extension",
                mode="GREENFIELD_GENERATION",
                current_brief_version=1,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
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
                created_at=CREATED_AT,
            )
        )


@pytest.mark.integration
def test_postgresql_keeps_the_mockup_the_assertions_and_the_verdicts(database) -> None:
    base = extended_version(plain_package())
    proposed = fixture_package()
    proposal = propose_design_revision(
        diff_id=INTEGRATION_DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=proposed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    assert proposal.diff is not None
    decision = decide_design_revision(
        diff=proposal.diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=INTEGRATION_VERSION_ID,
        reason="Il mockup generato rispetta le asserzioni del proprietario.",
    )
    assert decision.version is not None

    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_project(db)
            async with db.session_factory() as session, session.begin():
                packages = SqlAlchemyDesignPackageRepository(session, owner_user_id=OWNER_ID)
                assert await packages.append(base) is DesignVersionAppendStatus.APPENDED
            async with db.session_factory() as session, session.begin():
                diffs = SqlAlchemyDesignDiffRepository(session, owner_user_id=OWNER_ID)
                assert await diffs.create(proposal.diff) is DesignDiffPersistenceStatus.CREATED
            async with db.session_factory() as session, session.begin():
                packages = SqlAlchemyDesignPackageRepository(session, owner_user_id=OWNER_ID)
                diffs = SqlAlchemyDesignDiffRepository(session, owner_user_id=OWNER_ID)
                assert await packages.append(decision.version) is DesignVersionAppendStatus.APPENDED
                assert (
                    await diffs.save_decision(decision.diff) is DesignDiffPersistenceStatus.UPDATED
                )
            async with db.session_factory() as session:
                packages = SqlAlchemyDesignPackageRepository(session, owner_user_id=OWNER_ID)
                diffs = SqlAlchemyDesignDiffRepository(session, owner_user_id=OWNER_ID)
                current = await packages.current(project_id=PROJECT_ID)
                history = await packages.history(project_id=PROJECT_ID)
                stored_diff = await diffs.get(project_id=PROJECT_ID, diff_id=INTEGRATION_DIFF_ID)
                rows = (
                    await session.execute(
                        sa.select(
                            PACKAGE_VERSIONS.c.version_number,
                            PACKAGE_VERSIONS.c.content_hash,
                            PACKAGE_VERSIONS.c.package_snapshot,
                        )
                        .where(PACKAGE_VERSIONS.c.project_id == PROJECT_ID)
                        .order_by(PACKAGE_VERSIONS.c.version_number)
                    )
                ).all()
            assert current == decision.version
            assert current.package.generated_mockup == fixture_bound()
            assert current.package.owner_assertions == ASSERTIONS
            assert [(item.verdict, item.quote) for item in current.package.critiques] == list(
                VERDICTS
            )
            assert history == (base, decision.version)
            assert stored_diff == decision.diff
            assert [row.content_hash for row in rows] == [base.content_hash, proposed.content_hash]
            assert set(rows[0].package_snapshot) == PACKAGE_KEYS
            assert rows[1].package_snapshot["generated_mockup"] == fixture_bound().to_snapshot()
            assert rows[1].package_snapshot["owner_assertions"] == list(ASSERTIONS)
        finally:
            await db.dispose()

    run(scenario())
