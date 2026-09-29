from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.bound_mockups import BoundGeneratedMockup
from orchestwin.artifacts.generated_mockup_repair import repair_generated_mockup
from orchestwin.artifacts.generated_mockups import MAX_SCREENS
from orchestwin.artifacts.prototypes import DeclarativePrototype
from orchestwin.artifacts.visual_catalog import LayoutArchetype
from orchestwin.models.generated_mockup_drafts import (
    GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE,
    MAX_REJECTION_REASONS,
    MOCKUP_COVERAGE_TOO_LOW,
    MOCKUP_LANGUAGE_MISMATCH,
    MOCKUP_QUALITY_REJECTED,
    MOCKUP_SCREEN_COUNT,
    REQUIREMENTS_NOT_COVERED,
    SCREEN_COUNT,
    UNSAFE_MOCKUP_OUTPUT,
    GeneratedIterationDraft,
    GeneratedMockupDraft,
    GeneratedMockupRejection,
    GeneratedScreenDraft,
    bind_generated_mockup,
    declared_requirement_codes,
    requirement_codes,
    screen_limits,
)
from src.test.python.models.test_generated_mockup_support import (
    APPROACH,
    DASHBOARD,
    DASHBOARD_ID,
    GUIDED,
    GUIDED_CODES,
    GUIDED_ID,
    draft_payload,
    iteration_payload,
    package,
    requirements_version,
    with_markup,
)

LOANS = (
    ("Il nome della rosa", "Maria Bianchi", "2026-10-03", "3 ottobre 2026"),
    ("La coscienza di Zeno", "Luca Ferri", "2026-10-05", "5 ottobre 2026"),
    ("Il barone rampante", "Giulia Conti", "2026-10-07", "7 ottobre 2026"),
    ("Le città invisibili", "Paolo Greco", "2026-10-09", "9 ottobre 2026"),
    ("La luna e i falò", "Anna Russo", "2026-10-12", "12 ottobre 2026"),
    ("Il giorno della civetta", "Marco Villa", "2026-10-14", "14 ottobre 2026"),
)
CARD_TABLE_STYLES = (
    "main{padding:var(--vl-space)}"
    ".m-columns{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);"
    "gap:var(--vl-gap)}"
    ".m-columns>section{min-width:0}"
    ".m-loans{width:100%;border-collapse:collapse}"
    ".m-loans th,.m-loans td{padding:var(--vl-gap);text-align:left;vertical-align:top}"
    ".m-date{white-space:nowrap;font-variant-numeric:lining-nums tabular-nums}"
    ".m-label{display:none}"
    "@media (max-width:719px){"
    ".m-columns{grid-template-columns:minmax(0,1fr)}"
    ".m-loans,.m-loans tbody,.m-loans tr,.m-loans td{display:block}"
    ".m-loans thead tr{position:absolute;left:-10000px;top:auto;width:1px;height:1px;"
    "overflow:hidden}"
    ".m-loans tr{margin-bottom:var(--vl-gap)}"
    ".m-label{display:block;font-weight:600}"
    "}"
)


def card_cell(label: str, content: str, kind: str = "") -> str:
    marker = f" class='{kind}'" if kind else ""
    return f"<td{marker}><span class='m-label' aria-hidden='true'>{label}</span>{content}</td>"


def card_table_markup(codes: str) -> str:
    rows = "".join(
        "<tr>"
        + card_cell("Titolo", title)
        + card_cell("Lettore", reader)
        + card_cell("Scadenza", f"<time datetime='{moment}'>{day}</time>", "m-date")
        + card_cell("Azione", "<a href='#SCR-002'>Invia un promemoria</a>")
        + "</tr>"
        for title, reader, moment, day in LOANS
    )
    return (
        f"<main data-req='{codes}'>"
        "<h1>Prestiti da controllare oggi</h1>"
        "<p>La volontaria vede i prestiti in scadenza questa settimana e invia un promemoria a "
        "chi deve restituire il libro.</p>"
        "<div class='m-columns'><section>"
        "<h2>Prestiti in scadenza</h2>"
        "<table class='m-loans'><thead><tr>"
        "<th scope='col'>Titolo</th><th scope='col'>Lettore</th>"
        "<th scope='col'>Scadenza</th><th scope='col'>Azione</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
        "</section><section>"
        "<h2>Riepilogo della settimana</h2>"
        "<p>Sei prestiti scadono entro il 14 ottobre e nessun lettore ha ancora ricevuto un "
        "promemoria.</p>"
        "</section></div>"
        "</main>"
    )


def chained(count: int, codes: str = "REQ-001") -> dict[str, object]:
    screens = []
    for index in range(1, count + 1):
        target = f"SCR-{index % count + 1:03d}"
        screens.append(
            {
                "code": f"SCR-{index:03d}",
                "heading": f"Passo {index} dell'iscrizione",
                "kind": "SUCCESS" if index == count else "DEFAULT",
                "markup": (
                    f"<main data-req='{codes}'>"
                    f"<h1>Passo {index} dell'iscrizione</h1>"
                    "<p role='status'>La volontaria controlla i dati del lettore e prosegue con il "
                    "passo successivo della procedura di iscrizione alla biblioteca.</p>"
                    "<h2>Cosa serve</h2>"
                    "<ul><li>Un documento di identità valido.</li>"
                    "<li>Un indirizzo di posta elettronica.</li></ul>"
                    "<p>Ogni passo si può correggere prima della conferma finale.</p>"
                    f"<a href='#{target}' role='button'>Continua</a>"
                    "</main>"
                ),
            }
        )
    return {
        "approach": APPROACH,
        "css": "main{padding:var(--vl-space)}@media (max-width:600px){main{padding:var(--vl-gap)}}",
        "screens": screens,
    }


def chosen(identifier, language="it"):
    return next(item for item in package(language).alternatives if item.id == identifier)


def bind(payload, identifier=GUIDED_ID, *, requirements_language="it", language="it", model=None):
    draft = (model or GeneratedMockupDraft).model_validate(payload)
    return bind_generated_mockup(
        draft,
        alternative=chosen(identifier, requirements_language),
        requirements=requirements_version(requirements_language),
        language=language,
    )


def rejection(payload, identifier=GUIDED_ID, **options) -> GeneratedMockupRejection:
    with pytest.raises(GeneratedMockupRejection) as failure:
        bind(payload, identifier, **options)
    return failure.value


def card_table_payload() -> dict[str, object]:
    codes = " ".join(GUIDED_CODES)
    payload = chained(3, codes)
    screens = list(payload["screens"])
    screens[0] = {
        **screens[0],
        "heading": "Prestiti da controllare oggi",
        "markup": card_table_markup(codes),
    }
    return {**payload, "css": CARD_TABLE_STYLES, "screens": screens}


def iteration_of(count: int) -> dict[str, object]:
    return {
        **chained(count, " ".join(GUIDED_CODES)),
        "changes": ["Aggiunti i passi di verifica chiesti dal proprietario."],
    }


def test_both_fixture_drafts_are_bound_with_their_structure():
    guided = bind(draft_payload(GUIDED), GUIDED_ID)
    dashboard = bind(draft_payload(DASHBOARD), DASHBOARD_ID)
    for binding, screens, alternative_id in ((guided, 4, GUIDED_ID), (dashboard, 3, DASHBOARD_ID)):
        assert isinstance(binding.mockup, BoundGeneratedMockup)
        assert isinstance(binding.prototype, DeclarativePrototype)
        assert binding.prototype == binding.mockup.prototype()
        assert binding.mockup.design_alternative_id == alternative_id
        assert binding.mockup.mockup.title == "Biblioteca Sant'Ambrogio"
        assert len(binding.prototype.screens) == screens
        assert binding.report.is_acceptable
    assert guided.mockup.requirement_codes == tuple(f"REQ-00{index}" for index in range(1, 7))
    assert guided.warnings == ()
    assert [(item.code, item.detail) for item in dashboard.warnings] == [
        (REQUIREMENTS_NOT_COVERED, "REQ-007")
    ]
    assert dashboard.warning_snapshots() == (
        {"code": REQUIREMENTS_NOT_COVERED, "screen_code": None, "detail": "REQ-007"},
    )


def test_the_markup_is_stored_in_its_normalized_form():
    payload = draft_payload()
    assert 'data-req="REQ-001"' in payload["screens"][0]["markup"]
    original = bind(payload)
    quoted = bind(with_markup(payload, 'data-req="REQ-001"', "data-req='REQ-001'"))
    assert quoted.mockup.content_hash == original.mockup.content_hash
    assert "data-req='REQ-001'" not in quoted.mockup.mockup.screens[0].markup


def test_an_unsafe_answer_that_cannot_be_repaired_is_rejected_with_the_error_of_the_validator():
    payload = with_markup(draft_payload(), "</main>", "<section><script>alert(1)</script></main>")
    failure = rejection(payload)
    assert failure.code == UNSAFE_MOCKUP_OUTPUT
    [reason] = failure.reasons
    assert reason.code == "ELEMENT_FORBIDDEN"
    assert reason.screen_code == "SCR-001"
    assert "script" in reason.detail
    assert failure.to_snapshot()["reasons"][0]["code"] == "ELEMENT_FORBIDDEN"


def test_screen_codes_out_of_order_cannot_become_a_mockup():
    payload = draft_payload()
    screens = list(payload["screens"])
    screens[0], screens[1] = screens[1], screens[0]
    failure = rejection({**payload, "screens": screens})
    assert failure.code == UNSAFE_MOCKUP_OUTPUT
    assert failure.reasons[0].code == "SCREEN_CODE"


def test_quality_errors_reject_the_answer_with_the_errors_first():
    payload = with_markup(draft_payload(), "<h1>", "<h1>Lorem ipsum ")
    failure = rejection(payload)
    assert failure.code == MOCKUP_QUALITY_REJECTED
    assert failure.reasons[0].code == "PLACEHOLDER_TEXT"
    assert [reason.screen_code for reason in failure.reasons[:4]] == [
        "SCR-001",
        "SCR-002",
        "SCR-003",
        "SCR-004",
    ]
    assert len(failure.reasons) <= MAX_REJECTION_REASONS
    assert "PLACEHOLDER_TEXT" in failure.reason_text()


def test_reasons_are_bounded_to_twenty():
    payload = draft_payload()
    unreadable = "".join(
        f".x{index}{{color:var(--vl-color-surface);background:var(--vl-color-surface)}}"
        for index in range(25)
    )
    failure = rejection({**payload, "css": payload["css"] + unreadable})
    assert failure.code == MOCKUP_QUALITY_REJECTED
    assert len(failure.reasons) == MAX_REJECTION_REASONS
    assert {reason.code for reason in failure.reasons} == {"LOW_CONTRAST"}
    assert len(GeneratedMockupRejection("X", [failure.reasons[0]] * 40).reasons) == 20


def test_a_mockup_in_another_language_is_rejected_screen_by_screen():
    failure = rejection(draft_payload(), requirements_language="en", language="en")
    assert failure.code == MOCKUP_LANGUAGE_MISMATCH
    flagged = [reason for reason in failure.reasons if reason.code == "SCREEN_LANGUAGE"]
    assert [reason.screen_code for reason in flagged] == [
        "SCR-001",
        "SCR-002",
        "SCR-003",
        "SCR-004",
    ]
    assert "English" in flagged[0].detail


def test_without_a_language_no_language_check_runs():
    assert bind(draft_payload(), requirements_language="en", language=None).report.is_acceptable


def test_too_few_screens_for_the_archetype_are_rejected_with_every_other_reason():
    failure = rejection(chained(2), GUIDED_ID)
    assert failure.code == MOCKUP_SCREEN_COUNT
    codes = [reason.code for reason in failure.reasons]
    assert codes[0] == "SCREEN_COUNT"
    assert "expected 3 to 6" in failure.reasons[0].detail
    assert REQUIREMENTS_NOT_COVERED in codes


def test_more_screens_than_the_archetype_maximum_plus_two_are_a_warning():
    guided = chosen(GUIDED_ID)
    visual = guided.visual_language
    single = replace(
        guided,
        visual_language=replace(
            visual, choices=replace(visual.choices, archetype=LayoutArchetype.SINGLE_CARD)
        ),
    )
    assert screen_limits(single) == (2, 5)
    binding = bind_generated_mockup(
        GeneratedMockupDraft.model_validate(chained(6, " ".join(GUIDED_CODES))),
        alternative=single,
        requirements=requirements_version(),
        language="it",
    )
    assert len(binding.mockup.mockup.screens) == 6
    assert binding.warning_snapshots() == (
        {"code": SCREEN_COUNT, "screen_code": None, "detail": "6 screens, expected 2 to 5"},
    )
    assert screen_limits(chosen(DASHBOARD_ID)) == (2, 6)
    assert screen_limits(chosen(GUIDED_ID)) == (3, 6)


def test_an_iteration_may_reach_the_screen_limit_of_the_contract():
    guided = chosen(GUIDED_ID)
    single = replace(
        guided,
        visual_language=replace(
            guided.visual_language,
            choices=replace(guided.visual_language.choices, archetype=LayoutArchetype.SINGLE_CARD),
        ),
    )
    assert MAX_SCREENS == 8
    assert screen_limits(guided, iteration=True) == (3, MAX_SCREENS)
    assert screen_limits(chosen(DASHBOARD_ID), iteration=True) == (2, MAX_SCREENS)
    assert screen_limits(single, iteration=True) == (2, MAX_SCREENS)
    for count in (6, 7, MAX_SCREENS):
        binding = bind(iteration_of(count), model=GeneratedIterationDraft)
        assert len(binding.mockup.mockup.screens) == count
        assert binding.warnings == ()
    drawn = bind(chained(7, " ".join(GUIDED_CODES)))
    assert drawn.warning_snapshots() == (
        {"code": SCREEN_COUNT, "screen_code": None, "detail": "7 screens, expected 3 to 6"},
    )


def test_an_iteration_with_too_few_screens_names_the_limits_of_an_iteration():
    failure = rejection(iteration_of(2), model=GeneratedIterationDraft)
    assert failure.code == MOCKUP_SCREEN_COUNT
    assert failure.reasons[0].code == SCREEN_COUNT
    assert failure.reasons[0].detail == f"2 screens, expected 3 to {MAX_SCREENS}"


def test_a_table_that_becomes_cards_below_720_pixels_is_accepted_without_notes():
    payload = card_table_payload()
    guided = chosen(GUIDED_ID)
    requirements = requirements_version()
    markups = tuple(screen["markup"] for screen in payload["screens"])
    repair = repair_generated_mockup(
        styles=payload["css"],
        screens=[(screen["code"], screen["markup"]) for screen in payload["screens"]],
        requirement_codes=requirement_codes(requirements),
        token_names=guided.visual_language.token_values,
        declared_codes=declared_requirement_codes(guided, requirements),
    )
    assert repair.notes == ()
    assert repair.styles == payload["css"]
    assert repair.markups == markups
    binding = bind(payload)
    assert binding.report.issues == ()
    assert binding.report.is_acceptable
    assert binding.warnings == ()
    mockup = binding.mockup.mockup
    assert mockup.styles == CARD_TABLE_STYLES
    table = mockup.screens[0].markup
    assert table.count('<span aria-hidden="true" class="m-label">') == 4 * len(LOANS)
    assert '<th scope="col">Titolo</th>' in table
    assert "overflow-x" not in mockup.styles and "min-width:0" in mockup.styles
    assert ".m-loans thead tr{position:absolute;left:-10000px" in mockup.styles


def test_a_mockup_covering_less_than_half_of_the_declared_requirements_is_rejected():
    failure = rejection(chained(2), DASHBOARD_ID)
    assert failure.code == MOCKUP_COVERAGE_TOO_LOW
    [reason] = failure.reasons
    assert reason.code == REQUIREMENTS_NOT_COVERED
    assert reason.detail.startswith("1 of 7 declared requirements covered; missing REQ-002")


def test_an_alternative_without_visual_language_cannot_have_a_generated_mockup():
    plain = replace(chosen(GUIDED_ID), visual_language=None)
    with pytest.raises(GeneratedMockupRejection) as failure:
        bind_generated_mockup(
            GeneratedMockupDraft.model_validate(draft_payload()),
            alternative=plain,
            requirements=requirements_version(),
            language="it",
        )
    assert failure.value.code == GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE


def test_an_iteration_draft_binds_like_a_mockup_and_lists_its_changes():
    binding = bind(iteration_payload(), model=GeneratedIterationDraft)
    assert binding.report.is_acceptable
    draft = GeneratedIterationDraft.model_validate(iteration_payload())
    assert len(draft.changes) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"changes": []},
        {"changes": ["x" * 301]},
        {"changes": [f"Cambio {index}" for index in range(9)]},
    ],
)
def test_iteration_changes_are_bounded(change):
    with pytest.raises(ValidationError):
        GeneratedIterationDraft.model_validate(iteration_payload(**change))


@pytest.mark.parametrize(
    "change",
    [
        {"approach": ""},
        {"approach": "a" * 601},
        {"css": ""},
        {"css": "a" * 60_001},
        {"extra": "field"},
    ],
)
def test_draft_limits_are_enforced(change):
    with pytest.raises(ValidationError):
        GeneratedMockupDraft.model_validate({**draft_payload(), **change})


def test_screen_limits_of_the_draft():
    payload = draft_payload()
    screen = payload["screens"][0]
    for value in (
        {**screen, "code": "SCR-1"},
        {**screen, "markup": ""},
        {**screen, "markup": "a" * 40_001},
        {**screen, "kind": "LOADING"},
        {**screen, "heading": ""},
    ):
        with pytest.raises(ValidationError):
            GeneratedScreenDraft.model_validate(value)
    with pytest.raises(ValidationError):
        GeneratedMockupDraft.model_validate({**payload, "screens": payload["screens"][:1]})
    with pytest.raises(ValidationError):
        GeneratedMockupDraft.model_validate({**payload, "screens": payload["screens"] * 3})


def test_the_fields_are_ordered_as_the_model_should_write_them():
    for model in (GeneratedMockupDraft, GeneratedIterationDraft, GeneratedScreenDraft):
        names = list(model.model_fields)
        assert names == sorted(names)
    assert list(GeneratedIterationDraft.model_fields) == ["approach", "changes", "css", "screens"]
    assert list(GeneratedScreenDraft.model_fields) == ["code", "heading", "kind", "markup"]
