from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.flows import design_generate, design_state
from orchestwin.cli.http import UrlTransport

from .support.terminal import command_context, terminal
from .test_api_design import design_session
from .test_consumers45 import WIDE, three_state

MOCKUP_JOBS = "/design/mockups/jobs"
THREE_MOCKUPS = {
    "en": ("y", "Estimate: 4.21-5.34 USD, about 13 min."),
    "it": ("s", "Stima: 4,21-5,34 USD, circa 13 min."),
}
CLOSE_PAIR = {
    "en": "Alternatives DES-002 and DES-003 look alike in the drawn style. You can regenerate them.",
    "it": "Le alternative DES-002 e DES-003 si somigliano nello stile disegnato. Puoi rigenerarle.",
}
CLOSE_TWO = {
    "en": "The two alternatives look alike in drawn style. You can regenerate them.",
    "it": "Le due alternative si somigliano nello stile disegnato. Puoi rigenerarle.",
}


def test_a_proposal_estimates_the_mockups_that_will_be_drawn_together() -> None:
    three = three_state()
    alternatives = three.package["alternatives"]
    two = replace(three, version={**three.version, "package": {"alternatives": alternatives[:2]}})
    first = replace(three, version=None, documents={})
    plain = replace(three, capabilities=design_api.NO_CAPABILITIES)

    assert design_generate.proposal_spending(three) == (
        ["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP", "MOCKUP"],
        13.0,
    )
    assert design_generate.proposal_spending(two) == (["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP"], 13.0)
    assert design_generate.proposal_spending(first) == (
        ["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP"],
        13.0,
    )
    assert design_generate.proposal_spending(plain) == (["DESIGN_PROPOSAL"], None)


@pytest.mark.parametrize("language", ["en", "it"])
def test_regenerating_a_design_with_a_design_system_estimates_its_three_mockups(
    tmp_path: Path, language: str
) -> None:
    answer, estimate = THREE_MOCKUPS[language]
    with design_session(
        tmp_path, through="design", language=language, directions=True, design_system=True
    ) as session:
        session.project.seed_requirement_removed()
        run = session.ut("design", "regenerate", answers=[answer], language=language)
        drawn = session.count("POST", MOCKUP_JOBS)

    assert run.status == 0, run.errors
    assert estimate in run.output
    assert drawn == 3


def test_the_menu_estimates_the_regeneration_of_three_alternatives(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design", directions=True, design_system=True) as session:
        session.project.seed_requirement_removed()
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert (
        "Regenerate the alternatives from the approved steps (estimate 4.21-5.34 USD, about "
        "13 min)" in run.output
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_close_pair_is_named_among_three_alternatives_and_not_between_two(
    tmp_path: Path, language: str
) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport(), language=language, variables=WIDE)
    context = command_context(bundle.environment, language=language)
    pair = {"first": "DES-002", "second": "DES-003", "verdict": "CLOSE", "declared": {}}

    assert design_state.pair_lines(context, pair, named=True)[-1] == CLOSE_PAIR[language]
    assert design_state.pair_lines(context, pair, named=False)[-1] == CLOSE_TWO[language]
