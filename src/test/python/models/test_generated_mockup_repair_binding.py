from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts.bound_mockups import bound_mockup_from_snapshot
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockupError,
    create_generated_mockup,
    generated_mockup_from_snapshot,
)
from orchestwin.artifacts.visual_language import visual_language_from_snapshot
from orchestwin.models.generated_mockup_drafts import (
    MOCKUP_QUALITY_REJECTED,
    GeneratedIterationDraft,
    GeneratedMockupDraft,
    GeneratedMockupRejection,
    bind_generated_mockup,
)
from src.test.python.models.test_generated_mockup_support import (
    FIXTURES,
    GUIDED_ID,
    applied_package,
    draft_payload,
    iteration_payload,
    package,
    requirements_version,
    with_markup,
)

RECORDED = FIXTURES / "recorded-94b28b96.json"
LOGO = '<img src="https://example.org/logo.png" alt="Logo">'


def recorded() -> dict[str, object]:
    return json.loads(RECORDED.read_text(encoding="utf-8"))


def recorded_payload(data: dict[str, object]) -> str:
    chunks = data["payload_json"]
    assert isinstance(chunks, list)
    return "".join(chunks)


def recorded_context(data: dict[str, object]) -> tuple[SimpleNamespace, SimpleNamespace]:
    identifiers = {code: UUID(value) for code, value in data["requirement_ids_by_code"].items()}
    alternative = SimpleNamespace(
        id=UUID(str(data["alternative_id"])),
        code=data["alternative_code"],
        visual_language=visual_language_from_snapshot(data["visual_language"]),
        requirement_ids=tuple(identifiers[code] for code in data["declared_codes"]),
    )
    requirements = SimpleNamespace(
        specification=SimpleNamespace(
            requirements=tuple(
                SimpleNamespace(code=code, id=identifier)
                for code, identifier in identifiers.items()
            )
        )
    )
    return alternative, requirements


def chosen():
    return next(item for item in package().alternatives if item.id == GUIDED_ID)


def bind(payload, model=GeneratedMockupDraft):
    return bind_generated_mockup(
        model.model_validate(payload),
        alternative=chosen(),
        requirements=requirements_version(),
        language="it",
    )


def test_the_fixture_is_the_exact_answer_of_the_recorded_generation():
    data = recorded()
    payload = recorded_payload(data)
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == data["payload_sha256"]
    assert data["generation_id"] == "94b28b96-0471-4583-ab89-3fabaa337fa0"


def test_the_recorded_answer_is_accepted_at_the_first_attempt_without_any_issue():
    data = recorded()
    draft = GeneratedMockupDraft.model_validate_json(recorded_payload(data))
    alternative, requirements = recorded_context(data)
    tokens = alternative.visual_language.token_values
    with pytest.raises(GeneratedMockupError) as strict:
        create_generated_mockup(
            design_alternative_id=alternative.id,
            title=alternative.visual_language.product_name,
            styles=draft.css,
            screens=[
                {
                    "code": screen.code,
                    "title": screen.heading,
                    "state": screen.kind,
                    "markup": screen.markup,
                }
                for screen in draft.screens
            ],
            token_names=tokens,
        )
    assert (strict.value.code, strict.value.detail) == (
        "ATTRIBUTE_FORBIDDEN",
        "SCR-001: attribute autocomplete on input",
    )
    binding = bind_generated_mockup(
        draft, alternative=alternative, requirements=requirements, language=data["language"]
    )
    assert binding.report.issues == ()
    assert binding.report.is_acceptable
    assert binding.warnings == ()
    mockup = binding.mockup.mockup
    assert [screen.code for screen in mockup.screens] == [screen.code for screen in draft.screens]
    assert mockup.styles == draft.css
    assert all("autocomplete" not in screen.markup for screen in mockup.screens)
    assert binding.mockup.requirement_codes == tuple(data["declared_codes"])
    assert len(binding.prototype.screens) == 5


def test_the_notes_of_the_repair_arrive_as_warnings_of_the_result():
    payload = with_markup(draft_payload(), "<h1>", LOGO + '<h1 style="color:red">')
    binding = bind(payload)
    assert binding.report.is_acceptable
    snapshots = binding.warning_snapshots()
    for code in ("SCR-001", "SCR-002", "SCR-003", "SCR-004"):
        assert {"code": "ATTRIBUTE_REMOVED", "screen_code": code, "detail": "style"} in snapshots
        assert {"code": "ELEMENT_REMOVED", "screen_code": code, "detail": "img"} in snapshots
    assert snapshots[:2] == (
        {"code": "ATTRIBUTE_REMOVED", "screen_code": "SCR-001", "detail": "style"},
        {"code": "ELEMENT_REMOVED", "screen_code": "SCR-001", "detail": "img"},
    )
    assert all(set(item) == {"code", "screen_code", "detail"} for item in snapshots)
    stored = "".join(screen.markup for screen in binding.mockup.mockup.screens)
    assert "<img" not in stored and "style=" not in stored


def test_unknown_requirement_codes_are_removed_and_reported_instead_of_rejecting_the_answer():
    binding = bind(with_markup(draft_payload(), "REQ-006", "REQ-006 REQ-099"))
    assert binding.report.is_acceptable
    assert {
        (item["code"], item["detail"])
        for item in binding.warning_snapshots()
        if item["code"] == "REQUIREMENT_CODE_REMOVED"
    } == {("REQUIREMENT_CODE_REMOVED", "REQ-099")}
    assert "REQ-099" not in binding.mockup.mockup.canonical_json()


def test_an_iteration_draft_is_repaired_like_a_mockup():
    payload = with_markup(iteration_payload(), "<h1>", LOGO + "<h1>")
    binding = bind(payload, model=GeneratedIterationDraft)
    assert binding.report.is_acceptable
    assert {item["code"] for item in binding.warning_snapshots()} == {"ELEMENT_REMOVED"}


def test_a_rejected_answer_lists_the_notes_of_the_repair_after_its_errors():
    payload = with_markup(draft_payload(), "<h1>", LOGO + "<h1>Lorem ipsum ")
    with pytest.raises(GeneratedMockupRejection) as failure:
        bind(payload)
    rejection = failure.value
    assert rejection.code == MOCKUP_QUALITY_REJECTED
    codes = [reason.code for reason in rejection.reasons]
    assert codes[:4] == ["PLACEHOLDER_TEXT"] * 4
    assert codes[4:8] == ["ELEMENT_REMOVED"] * 4
    assert "ELEMENT_REMOVED SCR-001 img" in rejection.reason_text()


def test_a_valid_answer_is_bound_exactly_as_before_the_repair_existed():
    payload = draft_payload()
    binding = bind(payload)
    direct = create_generated_mockup(
        design_alternative_id=GUIDED_ID,
        title=chosen().visual_language.product_name,
        styles=payload["css"],
        screens=[
            {
                "code": screen["code"],
                "title": screen["heading"],
                "state": screen["kind"],
                "markup": screen["markup"],
            }
            for screen in payload["screens"]
        ],
        token_names=chosen().visual_language.token_values,
    )
    assert binding.mockup.mockup == direct
    assert binding.warnings == ()


def edited_snapshot(change) -> dict[str, object]:
    snapshot = copy.deepcopy(applied_package().generated_mockup.to_snapshot())
    change(snapshot["mockup"])
    return snapshot


def slipped_markup(mockup: dict[str, object]) -> None:
    screen = mockup["screens"][0]
    screen["markup"] = screen["markup"].replace("<input ", '<input autocomplete="off" ', 1)


def slipped_styles(mockup: dict[str, object]) -> None:
    mockup["styles"] = mockup["styles"] + "p{color:red}"


def unknown_element(mockup: dict[str, object]) -> None:
    screen = mockup["screens"][0]
    screen["markup"] = screen["markup"].replace("<h1>", "<h1><u>Nota</u>", 1)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (slipped_markup, "ATTRIBUTE_FORBIDDEN"),
        (slipped_styles, "STYLES_COLOUR"),
        (unknown_element, "ELEMENT_FORBIDDEN"),
    ],
)
def test_a_stored_mockup_is_validated_strictly_and_never_repaired(change, code):
    tokens = chosen().visual_language.token_values
    snapshot = edited_snapshot(change)
    with pytest.raises(GeneratedMockupError) as mockup_error:
        generated_mockup_from_snapshot(snapshot["mockup"], token_names=tokens)
    assert mockup_error.value.code == code
    with pytest.raises(GeneratedMockupError) as bound_error:
        bound_mockup_from_snapshot(snapshot, token_names=tokens)
    assert bound_error.value.code == code
    stored = applied_package().to_snapshot()
    stored["generated_mockup"] = snapshot
    with pytest.raises((GeneratedMockupError, ValueError)):
        design_package_from_snapshot(stored)


def test_the_unchanged_stored_mockup_still_loads():
    applied = applied_package()
    tokens = chosen().visual_language.token_values
    snapshot = applied.generated_mockup.to_snapshot()
    assert bound_mockup_from_snapshot(snapshot, token_names=tokens) == applied.generated_mockup
    assert design_package_from_snapshot(applied.to_snapshot()) == applied
