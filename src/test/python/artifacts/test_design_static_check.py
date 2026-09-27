from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import pytest

from orchestwin.artifacts import design_static_check as module
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_static_check import (
    MAX_STATIC_CONTROLS,
    STATIC_CHECK_MEDIA_TYPE,
    STATIC_CHECK_NOT_APPLICABLE,
    STATIC_CHECKS,
    STATIC_PROFILE_CONSTRAINT,
    StaticCheckTarget,
    StaticControl,
    static_check_bundle,
    static_check_document,
    static_check_profile,
    static_check_scope,
    static_check_target,
)
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)
from orchestwin.evaluation.artifact_content import MAX_VIEW_BYTES
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.training.complete_interface_curriculum import CHECKS, _request
from orchestwin.training.complete_interface_fixtures import localized, render, scenario
from orchestwin.training.complete_interface_validation import observe
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

from . import design_fixtures

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
OPAQUE = re.compile(r"[cf]-[0-9a-f]{10}")
INTERACTIVE = frozenset(
    {
        PrototypeElementKind.TEXT_INPUT,
        PrototypeElementKind.SELECT,
        PrototypeElementKind.BUTTON,
        PrototypeElementKind.LINK,
    }
)
HEADING = PrototypeElementKind.HEADING
TEXT = PrototypeElementKind.TEXT
TEXT_INPUT = PrototypeElementKind.TEXT_INPUT
SELECT = PrototypeElementKind.SELECT
BUTTON = PrototypeElementKind.BUTTON
LINK = PrototypeElementKind.LINK
LIST = PrototypeElementKind.LIST
CARD = PrototypeElementKind.CARD
STATUS = PrototypeElementKind.STATUS


def element(ordinal, kind, content, *, field_name=None, options=()):
    interactive = kind in INTERACTIVE
    return create_prototype_element(
        element_id=UUID(int=800 + ordinal),
        code=f"ELM-{ordinal:03d}",
        kind=kind,
        content=content,
        accessible_name=content if interactive else None,
        requirement_ids=(design_fixtures.REQUIREMENT_ID,) if interactive else (),
        field_name=field_name,
        options=options,
    )


def screen(ordinal, state, elements, *, title=None):
    return create_prototype_screen(
        screen_id=UUID(int=900 + ordinal),
        code=f"SCR-{ordinal:03d}",
        title=title or f"Screen {ordinal}",
        state=state,
        elements=elements,
        requirement_ids=(design_fixtures.REQUIREMENT_ID,),
    )


def transition(ordinal, source, trigger, target):
    return create_prototype_transition(
        transition_id=UUID(int=950 + ordinal),
        code=f"TRN-{ordinal:03d}",
        source_screen_id=source.id,
        trigger_element_id=trigger.id,
        target_screen_id=target.id,
        outcome=f"{target.title} opens.",
    )


def version_with(*screens, entry=None, transitions=()):
    version = design_fixtures.design_version()
    prototype = replace(
        version.package.prototype,
        entry_screen_id=(entry or screens[0]).id,
        screens=tuple(sorted(screens, key=lambda item: item.code)),
        transitions=transitions,
    )
    return design_fixtures.design_version(package=replace(version.package, prototype=prototype))


def opaque(prefix, identifier):
    return f"{prefix}-{hashlib.sha256(str(identifier).encode('utf-8')).hexdigest()[:10]}"


def controls_of(target):
    return [{"target": item.target, "family": item.family} for item in target.controls]


def booking_version():
    back = element(8, LINK, "Back to start")
    start_button = element(13, BUTTON, "Start")
    start = screen(
        1,
        PrototypeScreenState.DEFAULT,
        (element(12, TEXT, "Welcome"), start_button, element(14, LINK, "Help")),
        title="Start",
    )
    form = screen(
        2,
        PrototypeScreenState.ERROR,
        (
            element(1, HEADING, "Check the booking"),
            element(2, TEXT_INPUT, "Guest name", field_name="guest_name"),
            element(3, SELECT, "Room type", field_name="room_type", options=("Single", "Double")),
            element(4, BUTTON, "Retry booking"),
            element(5, BUTTON, "Cancel"),
            element(6, STATUS, "The dates overlap an existing booking."),
            element(7, STATUS, "Second alert"),
            back,
            element(9, LIST, "Arrival · Departure"),
            element(10, CARD, "Two nights"),
            element(11, TEXT, "Fix the dates and retry."),
        ),
        title="Booking error",
    )
    return version_with(
        start,
        form,
        transitions=(transition(1, form, back, start), transition(2, start, start_button, form)),
    )


def test_target_selects_the_entry_form_of_the_fixture_with_opaque_identifiers():
    version = design_fixtures.design_version()
    entry = version.package.prototype.screens[0]
    target = static_check_target(version, locale="it-IT")
    assert target.screen_code == "SCR-001"
    assert target.task == "Create a reservation"
    assert target.locale == "it"
    assert target.form == opaque("f", entry.id)
    assert target.controls == (
        StaticControl("ELM-001", opaque("c", entry.elements[0].id), "input_label"),
        StaticControl("ELM-002", opaque("c", entry.elements[1].id), "button_name"),
    )
    identifiers = (target.form, *(item.target for item in target.controls))
    assert all(OPAQUE.fullmatch(value) for value in identifiers)
    assert len(set(identifiers)) == 3
    assert target.checks == (
        f"#{target.controls[0].target}: {STATIC_CHECKS['input_label'][1]}",
        f"#{target.controls[1].target}: {STATIC_CHECKS['button_name'][1]}",
    )
    assert static_check_target(version, locale="it-IT") == target
    english = static_check_target(version, locale="en-US")
    assert replace(english, locale="it") == target
    assert english.checks[0] == f"#{target.controls[0].target}: {STATIC_CHECKS['input_label'][0]}"


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("it-IT", "it"), ("IT", "it"), ("it", "it"), ("en-GB", "en"), ("fr-FR", "en"), ("de", "en")],
)
def test_target_keeps_only_the_two_trained_languages(locale, expected):
    assert static_check_target(design_fixtures.design_version(), locale=locale).locale == expected


def test_target_skips_incomplete_screens_and_selects_one_control_per_family():
    version = booking_version()
    form = version.package.prototype.screens[1]
    target = static_check_target(version, locale="en-GB")
    assert target.screen_code == "SCR-002"
    assert target.form == opaque("f", form.id)
    assert [(item.element_code, item.family) for item in target.controls] == [
        ("ELM-002", "input_label"),
        ("ELM-004", "button_name"),
        ("ELM-001", "heading"),
        ("ELM-006", "error_guidance"),
    ]
    assert len(target.controls) == MAX_STATIC_CONTROLS == 4
    assert all(
        item.target == opaque("c", UUID(int=800 + int(item.element_code[4:])))
        for item in target.controls
    )


def test_target_prefers_the_entry_screen_and_ignores_status_outside_errors():
    first = screen(
        1,
        PrototypeScreenState.DEFAULT,
        (element(1, TEXT_INPUT, "Guest name", field_name="guest_name"), element(2, BUTTON, "Save")),
    )
    entry = screen(
        2,
        PrototypeScreenState.SUCCESS,
        (
            element(3, SELECT, "Room type", field_name="room_type", options=("Single",)),
            element(4, BUTTON, "Confirm"),
            element(5, STATUS, "Saved"),
        ),
    )
    target = static_check_target(version_with(first, entry, entry=entry), locale="en")
    assert target.screen_code == "SCR-002"
    assert [(item.element_code, item.family) for item in target.controls] == [
        ("ELM-003", "input_label"),
        ("ELM-004", "button_name"),
    ]


def test_target_requires_a_selected_prototype_with_a_field_and_a_button_on_one_screen():
    fields = screen(
        1, PrototypeScreenState.DEFAULT, (element(1, TEXT_INPUT, "Guest name", field_name="guest"),)
    )
    buttons = screen(2, PrototypeScreenState.ERROR, (element(2, BUTTON, "Save"),))
    with pytest.raises(DesignEvaluationError, match=STATIC_CHECK_NOT_APPLICABLE) as failure:
        static_check_target(version_with(fields, buttons), locale="en")
    assert failure.value.code == STATIC_CHECK_NOT_APPLICABLE
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    with pytest.raises(DesignEvaluationError, match="DESIGN_PROTOTYPE_REQUIRED"):
        static_check_target(bare, locale="en")


def test_document_renders_the_fixture_form_as_the_training_grammar():
    version = design_fixtures.design_version()
    target = static_check_target(version, locale="it-IT")
    document = static_check_document(version, target)
    text = document.content.decode("utf-8")
    field, button = (item.target for item in target.controls)
    assert text == (
        '<html lang="it"><head><title>Create a reservation</title><meta charset="utf-8" /></head>'
        "<body><header><h1>Create a reservation</h1><nav>"
        '<a href="#scr-001">Create reservation</a><a href="#scr-002">Reservation confirmation</a>'
        '</nav></header><main><section id="scr-001"><h2>Create reservation</h2>'
        f'<form id="{target.form}"><label for="{field}">Guest name</label>'
        f'<input id="{field}" name="{field}" /><button id="{button}"><span>Save reservation</span>'
        '</button></form></section><section id="scr-002"><h2>Reservation confirmation</h2>'
        '<p role="status">Reservation saved</p></section></main>'
        "<footer>Reservation flow prototype</footer></body></html>"
    )
    assert [item["state"] for item in observe(text, target.form, controls_of(target))] == [
        "PRESENT",
        "PRESENT",
    ]
    reference = document.reference
    assert reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert reference.media_type == STATIC_CHECK_MEDIA_TYPE == "text/html"
    assert reference.location == f"dom:#{target.form}"
    assert (reference.artifact_id, reference.version_number) == (design_fixtures.PROTOTYPE_ID, 1)
    assert reference.sha256_digest == hashlib.sha256(document.content).hexdigest()
    assert reference.size_bytes == len(document.content)
    assert document.read(reference.storage_key, MAX_VIEW_BYTES) == document.content


def test_document_renders_every_selected_control_and_the_remaining_elements():
    version = booking_version()
    target = static_check_target(version, locale="en-GB")
    text = static_check_document(version, target).content.decode("utf-8")
    field, button, heading, alert = (item.target for item in target.controls)
    assert text.startswith('<html lang="en"><head><title>Create a reservation</title>')
    assert '<nav><a href="#scr-001">Start</a><a href="#scr-002">Booking error</a></nav>' in text
    assert (
        '<section id="scr-001"><h2>Start</h2><p>Welcome</p><button>Start</button>'
        "<span>Help</span></section>"
    ) in text
    assert (
        f'<section id="scr-002"><h2>Booking error</h2><form id="{target.form}">'
        f'<h2 id="{heading}"><span>Check the booking</span></h2>'
        f'<label for="{field}">Guest name</label><input id="{field}" name="{field}" />'
        '<label for="elm-003">Room type</label><input id="elm-003" name="room_type" />'
        f'<button id="{button}"><span>Retry booking</span></button><button>Cancel</button>'
        f'<p id="{alert}" role="alert"><strong>The dates overlap an existing booking.</strong></p>'
        '<p role="status">Second alert</p><a href="#scr-001">Back to start</a>'
        "<ul><li>Arrival · Departure</li></ul><div>Two nights</div>"
        "<p>Fix the dates and retry.</p></form></section>"
    ) in text
    assert text.count("<form") == 1
    assert [item["state"] for item in observe(text, target.form, controls_of(target))] == [
        "PRESENT"
    ] * 4


def test_document_escapes_model_text_and_bounds_its_size(monkeypatch):
    hostile = screen(
        1,
        PrototypeScreenState.DEFAULT,
        (
            element(1, TEXT_INPUT, '<img src=x onerror="alert(1)">', field_name="guest"),
            element(2, BUTTON, "Save & <close>"),
            element(3, TEXT_INPUT, "Notes", field_name='notes"><script>'),
        ),
        title="Title <script>",
    )
    text = static_check_document(
        version_with(hostile), static_check_target(version_with(hostile), locale="en")
    ).content.decode("utf-8")
    assert "<script" not in text and "<img" not in text
    assert '&lt;img src=x onerror="alert(1)"&gt;</label>' in text
    assert "<span>Save &amp; &lt;close&gt;</span>" in text
    assert 'name="notes&quot;&gt;&lt;script&gt;"' in text
    assert "<h2>Title &lt;script&gt;</h2>" in text
    heavy = version_with(
        screen(
            1,
            PrototypeScreenState.DEFAULT,
            (
                element(1, TEXT_INPUT, "Guest name " + "x" * 3000, field_name="guest"),
                element(2, BUTTON, "Save " + "y" * 3000),
                *(element(ordinal, TEXT, "parola " * 500) for ordinal in range(3, 9)),
            ),
        )
    )
    target = static_check_target(heavy, locale="en")
    document = static_check_document(heavy, target)
    shortened = document.content.decode("utf-8")
    assert len(document.content) <= MAX_VIEW_BYTES
    assert "…</label>" in shortened and "…</span></button>" in shortened
    assert [item["state"] for item in observe(shortened, target.form, controls_of(target))] == [
        "PRESENT",
        "PRESENT",
    ]
    monkeypatch.setattr(module, "CONTENT_STEPS", (None,))
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_TOO_LARGE"):
        static_check_document(heavy, target)


def test_bundle_carries_the_scope_the_checks_and_only_the_page():
    version = design_fixtures.design_version()
    target = static_check_target(version, locale="en-US")
    document = static_check_document(version, target)
    bundle = static_check_bundle(version, document, target, created_at=NOW)
    assert (bundle.project_id, bundle.workflow_run_id) == (version.project_id, version.id)
    assert bundle.artifacts == (document.reference,)
    assert bundle.created_at == NOW
    assert bundle.scenario.id == uuid5(module._SCENARIO_NAMESPACE, f"{version.id}:{target.form}")
    assert bundle.scenario.name == "Create a reservation"
    assert bundle.scenario.task == static_check_scope(target)
    assert bundle.scenario.task.startswith(
        f"Task: Create a reservation. Inspect the complete supplied page, focusing on form "
        f"#{target.form}. Check each selected control separately: {target.checks[0]}; "
    )
    assert bundle.scenario.locale == "en"
    assert bundle.scenario.expected_outcomes == target.checks
    again = static_check_bundle(version, document, target, created_at=NOW, bundle_id=bundle.id)
    assert again == bundle
    assert static_check_bundle(version, document, target, created_at=NOW).id != bundle.id


@pytest.mark.parametrize(("locale", "language"), [("en-US", 0), ("it-IT", 1)])
def test_profile_replaces_the_twin_with_the_trained_static_profile(locale, language):
    version = design_fixtures.design_version()
    target = static_check_target(version, locale=locale)
    snapshot = canonical_json({"name": "Hotel Receptionist Twin", "observations": [{"k": "v"}]})
    twin = EvaluationUserTwinProfile(
        twin_id=design_fixtures.TWIN_ID,
        version_number=2,
        name="Hotel Receptionist Twin",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        snapshot_json=snapshot,
    )
    profile = static_check_profile(twin, target)
    expected = canonical_json(
        {
            "name": "Hotel Receptionist Twin",
            "role": "Hotel Receptionist Twin",
            "goals": ["Create a reservation"],
            "operational_constraints": [STATIC_PROFILE_CONSTRAINT[language]],
        }
    )
    assert profile == EvaluationUserTwinProfile(
        twin_id=twin.twin_id,
        version_number=2,
        name=twin.name,
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        snapshot_json=expected,
    )


def test_scope_checks_and_profile_reproduce_the_training_curriculum():
    trained_checks = {key: value for key, value in CHECKS.items() if key != "image_text"}
    assert trained_checks == STATIC_CHECKS
    compared = set()
    for split in ("train", "validation", "test"):
        for ordinal in range(24):
            case = scenario(11, split, ordinal)
            if any(control.family not in STATIC_CHECKS for control in case.controls):
                continue
            for locale in ("en", "it"):
                raw = render(case, locale, "complete", ("PRESENT",) * len(case.controls))
                request, _ = _request(case, locale, raw, False)
                trained = request.artifact_bundle.scenario
                target = StaticCheckTarget(
                    screen_code="SCR-001",
                    form=case.form,
                    task=localized(case, locale)[0],
                    locale=locale,
                    controls=tuple(
                        StaticControl(f"ELM-{index:03d}", control.target, control.family)
                        for index, control in enumerate(case.controls, 1)
                    ),
                )
                assert static_check_scope(target) == trained.task
                assert target.checks == trained.expected_outcomes
                assert trained.name == target.task
                assert trained.locale == target.locale
                assert static_check_profile(request.twin, target) == request.twin
                assert request.artifact_bundle.artifacts[0].media_type == STATIC_CHECK_MEDIA_TYPE
                assert request.artifact_bundle.artifacts[0].location == f"dom:#{target.form}"
                compared.add((locale, len(case.controls)))
    assert compared == {(locale, count) for locale in ("en", "it") for count in (2, 3, 4)}


def test_static_control_targets_follow_the_training_identifier_format():
    case = scenario(11, "train", 0)
    trained = [case.form, *(control.target for control in case.controls)]
    assert all(OPAQUE.fullmatch(value) for value in trained)
    assert OPAQUE.fullmatch(opaque("c", uuid4()))
