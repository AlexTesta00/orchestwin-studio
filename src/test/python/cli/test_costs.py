from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.costs import ESTIMATES, Estimate, confirm_spending, estimate, minutes_text
from orchestwin.cli.errors import ApiFailure, CliError

from .support.terminal import Terminal, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

BUDGET_PATH = f"{API}/model-runtime/budget"
BUDGET = {
    "currency": "USD",
    "per_generation_microusd": 5_000_000,
    "per_project_microusd": 20_000_000,
    "total_microusd": 60_000_000,
    "spent_total_microusd": 34_870_000,
    "remaining_total_microusd": 25_130_000,
    "period_start": None,
}


def prepared(
    tmp_path: Path,
    transport: ScriptedTransport,
    *,
    answers: tuple[str, ...] = (),
    assume_yes: bool = False,
    language: str = "en",
) -> tuple[CommandContext, Terminal]:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport, answers=answers)
    context = command_context(bundle.environment, language=language, assume_yes=assume_yes)
    return context, bundle


def with_budget(body: object = None, *, status: int = 200) -> ScriptedTransport:
    return ScriptedTransport().expect(
        "GET", BUDGET_PATH, status=status, body=BUDGET if body is None else body
    )


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"detail": "Not Found"}),
        (503, {"detail": {"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"}}),
        (503, {"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}}),
        (200, {"currency": "USD", "total_microusd": None}),
    ],
)
def test_without_a_budget_nothing_is_shown_or_asked(
    tmp_path: Path, status: int, body: object
) -> None:
    transport = with_budget(body, status=status)
    context, bundle = prepared(tmp_path, transport)

    confirm_spending(context, context.client(), ["MOCKUP", "MOCKUP"])

    assert bundle.output == ""
    transport.assert_done()


def test_a_budget_that_cannot_be_read_is_an_error(tmp_path: Path) -> None:
    transport = with_budget({"detail": {"code": "PROPOSAL_EVIDENCE_UNAVAILABLE"}}, status=503)
    context, _ = prepared(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        confirm_spending(context, context.client(), ["MOCKUP"])

    assert caught.value.code == "PROPOSAL_EVIDENCE_UNAVAILABLE"


def test_a_small_spending_is_shown_without_a_question(tmp_path: Path) -> None:
    context, bundle = prepared(tmp_path, with_budget())

    confirm_spending(context, context.client(), ["TEAM_PROPOSAL", "PERSONA_PROPOSAL"])

    assert bundle.output == (
        "Estimate: 0.07-0.08 USD, about 1 min. Credit left in the Studio: 25.13 USD.\n"
    )


@pytest.mark.parametrize("answer", ["", "y", "sì"])
def test_a_large_spending_is_asked_once(tmp_path: Path, answer: str) -> None:
    context, bundle = prepared(tmp_path, with_budget(), answers=(answer,))

    confirm_spending(context, context.client(), ["MOCKUP"])

    assert bundle.output.splitlines() == [
        "Estimate: 1.30-1.60 USD, about 10 min. Credit left in the Studio: 25.13 USD.",
        "Go ahead with this spending? [Y/n] ",
    ]


def test_a_refused_spending_raises(tmp_path: Path) -> None:
    context, _ = prepared(tmp_path, with_budget(), answers=("n",))

    with pytest.raises(CliError) as caught:
        confirm_spending(context, context.client(), ["ITERATION"])

    assert caught.value.code == "SPENDING_REFUSED"
    assert caught.value.status == 5


def test_yes_skips_the_question(tmp_path: Path) -> None:
    context, bundle = prepared(tmp_path, with_budget(), assume_yes=True)

    confirm_spending(context, context.client(), ["MOCKUP", "MOCKUP"], minutes=10.0)

    assert bundle.output.splitlines() == [
        "Estimate: 2.60-3.20 USD, about 10 min. Credit left in the Studio: 25.13 USD.",
        "Spending confirmed with --yes.",
    ]


def test_without_questions_a_large_spending_is_refused(tmp_path: Path) -> None:
    context, _ = prepared(tmp_path, with_budget(), answers=("y",))

    with pytest.raises(CliError) as caught:
        confirm_spending(context, context.client(), ["MOCKUP"], ask=False)

    assert caught.value.code == "SPENDING_REFUSED"
    assert context.environment.stdin.readline() == "y\n"


def test_italian_amounts_use_the_comma_and_warn_above_the_credit(tmp_path: Path) -> None:
    poor = {**BUDGET, "remaining_total_microusd": 1_000_000}
    context, bundle = prepared(tmp_path, with_budget(poor), answers=("s",), language="it")

    confirm_spending(context, context.client(), ["BRIEF_DIALOGUE", "MOCKUP"])

    assert bundle.output.splitlines() == [
        "Stima: 1,39-1,69 USD, circa 11 min. Credito rimasto nello Studio: 1,00 USD.",
        "La stima supera il credito rimasto: lo Studio potrebbe rifiutare la generazione.",
        "Vado avanti con questa spesa? [S/n] ",
    ]


def test_a_budget_without_the_spending_so_far_shows_only_the_estimate(tmp_path: Path) -> None:
    unknown = {**BUDGET, "spent_total_microusd": None, "remaining_total_microusd": None}
    context, bundle = prepared(tmp_path, with_budget(unknown))

    confirm_spending(context, context.client(), ["BRIEF_DIALOGUE"])

    assert bundle.output == "Estimate: 0.09 USD, about 1 min.\n"


def test_the_estimates_of_the_contract() -> None:
    assert ESTIMATES["MOCKUP"] == Estimate(1.30, 1.60, 10.0)
    assert ESTIMATES["REQUIREMENTS_PROPOSAL"] == Estimate(0.20, 0.37, 2.0)
    assert ESTIMATES["CODE_CHANGE_REVIEW"] == Estimate(0.15, 0.25, 1.0)
    assert ESTIMATES["CODE_ALIGNMENT"] == Estimate(0.15, 0.30, 1.0)
    assert ESTIMATES["TEST_PLAN"] == Estimate(0.15, 0.30, 2.0)
    assert ESTIMATES["TEST_REVIEW"] == Estimate(0.10, 0.20, 1.0)
    assert ESTIMATES["TWIN_UPDATE"] == Estimate(0.10, 0.25, 1.0)
    assert set(ESTIMATES) == {
        "BRIEF_DIALOGUE",
        "TEAM_PROPOSAL",
        "PERSONA_PROPOSAL",
        "USER_TWIN_GENERATION",
        "REQUIREMENTS_PROPOSAL",
        "REQUIREMENTS_CHANGE",
        "DESIGN_PROPOSAL",
        "MOCKUP",
        "ITERATION",
        "DESIGN_EVALUATION",
        "TWIN_CHAT",
        "CODE_CHANGE_REVIEW",
        "CODE_ALIGNMENT",
        "TEST_PLAN",
        "TEST_REVIEW",
        "TWIN_UPDATE",
    }


def test_two_twin_updates_are_shown_and_three_are_asked(tmp_path: Path) -> None:
    transport = with_budget().expect("GET", BUDGET_PATH, body=BUDGET)
    context, bundle = prepared(tmp_path, transport, answers=("",), language="it")

    confirm_spending(context, context.client(), ["TWIN_UPDATE"] * 2)
    confirm_spending(context, context.client(), ["TWIN_UPDATE"] * 3)

    assert bundle.output.splitlines() == [
        "Stima: 0,20-0,50 USD, circa 2 min. Credito rimasto nello Studio: 25,13 USD.",
        "Stima: 0,30-0,75 USD, circa 3 min. Credito rimasto nello Studio: 25,13 USD.",
        "Vado avanti con questa spesa? [S/n] ",
    ]
    transport.assert_done()


def test_a_test_plan_is_never_asked_and_three_twins_reviewing_a_run_are(tmp_path: Path) -> None:
    plan = estimate(["TEST_PLAN"])
    review = estimate(["TEST_REVIEW"] * 3)
    transport = with_budget().expect("GET", BUDGET_PATH, body=BUDGET)
    context, bundle = prepared(tmp_path, transport, answers=("n",))

    confirm_spending(context, context.client(), ["TEST_PLAN"])
    with pytest.raises(CliError) as caught:
        confirm_spending(context, context.client(), ["TEST_REVIEW"] * 3)

    assert (plan.low_usd, plan.high_usd, plan.minutes) == (0.15, 0.3, 2.0)
    assert (review.low_usd, review.high_usd, review.minutes) == (0.3, 0.6, 3.0)
    assert caught.value.code == "SPENDING_REFUSED"
    assert bundle.output.splitlines() == [
        "Estimate: 0.15-0.30 USD, about 2 min. Credit left in the Studio: 25.13 USD.",
        "Estimate: 0.30-0.60 USD, about 3 min. Credit left in the Studio: 25.13 USD.",
        "Go ahead with this spending? [Y/n] ",
    ]


def test_a_review_of_code_changes_multiplies_the_twins_and_adds_the_verdict() -> None:
    per_commit = ["CODE_CHANGE_REVIEW", "CODE_CHANGE_REVIEW", "CODE_ALIGNMENT"]
    total = estimate(per_commit * 2)

    assert (total.low_usd, total.high_usd, total.minutes) == (0.9, 1.6, 6.0)


def test_sums_add_the_amounts_and_the_minutes_unless_given() -> None:
    whole = estimate(["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP"])
    together = estimate(["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP"], minutes=13.0)

    assert (whole.low_usd, whole.high_usd, whole.minutes) == (2.91, 3.74, 23.0)
    assert together.minutes == 13.0
    assert minutes_text(0.2) == "1 min"
    assert minutes_text(3.0) == "3 min"
