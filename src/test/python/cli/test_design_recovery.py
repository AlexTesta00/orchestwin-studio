from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestwin.cli import messages

from .support.terminal import run_ut
from .test_api_design import Session, design_session
from .test_design_command import menu, posts
from .test_design_generate import Unreachable
from .test_status_command import ALL_FINE

SECTIONS = "/projects/{project_id}/sections"
REGENERATIONS = "/design/regenerations"


def said(key: str, language: str = "en", **values: object) -> str:
    return messages.text(key, language, **values)


def removed(session: Session) -> dict[str, object]:
    session.project.seed_requirement_removed()
    return session.project.sections()


def design_section(document: dict[str, object]) -> dict[str, object]:
    return next(item for item in document["sections"] if item["key"] == "DESIGN")


@pytest.mark.parametrize("language", ["en", "it"])
def test_removed_requirements_offer_explicit_regeneration_without_mutating_on_entry(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, through="design", language=language) as session:
        document = removed(session)
        before = posts(session)
        run = session.ut("design", language=language, answers=["leave"])
        after = posts(session)
        version = session.project.current("design")

    assert run.status == 0, run.errors
    assert (
        said(
            "design.recovery_requirement_removed",
            language,
            codes=", ".join(design_section(document)["codes"]),
        )
        in run.output
    )
    assert said("design.menu_regenerate", language) in run.output
    for action in ["change", "choose", "approve", "review", "apply"]:
        assert said(f"design.menu_{action}", language, request="-") not in run.output
    assert before == after
    assert version["version_number"] == 2
    assert run.opened == ()


@pytest.mark.parametrize("guided", [False, True])
@pytest.mark.parametrize("schema_version", [1, 2])
def test_regeneration_uses_real_route_async_polling_and_returns_to_ordinary_choice(
    tmp_path: Path, guided: bool, schema_version: int
) -> None:
    with design_session(
        tmp_path, through="design", requirements_schema_version=schema_version
    ) as session:
        removed(session)
        specification = copy.deepcopy(session.project.current("requirements")["specification"])
        before = session.project.current("design")
        arguments = ("design",) if guided else ("design", "regenerate")
        answers = ["regenerate", "y", "leave"] if guided else ["y"]
        run = session.ut(*arguments, answers=answers)
        current = session.project.current("design")
        next_menu = session.ut("design", answers=["leave"])
        requests = session.requests("POST", REGENERATIONS)
        polling = [
            item
            for item in session.studio.requests
            if item.method == "GET" and "/generation-jobs/" in item.path
        ]
        writes = session.writes()
        history = list(session.project.designs)
        requirements = session.project.current("requirements")
        assert requirements["specification"] == specification
        assert requirements["specification"]["schema_version"] == schema_version
        assert (
            current["package"]["grounding"]["requirements_reference"]["content_hash"]
            == requirements["content_hash"]
        )

    assert run.status == 0, run.errors
    assert len(requests) == 1
    assert not requests[0].body
    assert current["id"] != before["id"]
    assert current["version_number"] == before["version_number"] + 1
    assert current["package"]["owner_selected_alternative_id"] is None
    assert any(item["id"] == before["id"] for item in history)
    assert said("design.menu_choose") in next_menu.output
    assert said("design.menu_regenerate") not in next_menu.output
    assert not any("/gate/" in path or "/revisions" in path for path in writes)
    assert polling
    assert next_menu.status == 0, next_menu.errors
    assert run.output.count("Go ahead with this spending?") == 1


def test_declining_the_regeneration_keeps_history_and_starts_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        removed(session)
        before = posts(session)
        run = session.ut("design", answers=["regenerate", "n", "leave"])
        after = posts(session)

    assert run.status == 0
    assert "spending was not confirmed" in run.errors
    assert before == after
    assert run.output.count("What do you want to do?") == 2


@pytest.mark.parametrize("action", ["change", "choose", "approve", "review"])
def test_explicit_obsolete_actions_stop_before_provider_or_post(
    tmp_path: Path, action: str
) -> None:
    with design_session(tmp_path, through="design") as session:
        removed(session)
        before = posts(session)
        value = (
            ["Bigger button"] if action == "change" else ["DES-001"] if action == "choose" else []
        )
        run = session.ut("--yes", "design", action, *value)
        after = posts(session)

    assert run.status == 1
    assert "`ut design regenerate`" in run.errors
    assert before == after
    assert "Go ahead with this spending?" not in run.output


@pytest.mark.parametrize(
    "block", ["UPSTREAM_NOT_READY", "REVISION_PENDING", "DESIGN_REVISION_PENDING"]
)
def test_upstream_or_pending_revision_blocks_regeneration_without_post(
    tmp_path: Path, block: str
) -> None:
    with design_session(tmp_path, through="design") as session:
        document = removed(session)
        if block == "UPSTREAM_NOT_READY":
            upstream = next(item for item in document["sections"] if item["key"] == "REQUIREMENTS")
            upstream.update(state="IN_PROGRESS", blocked=None)
        else:
            design_section(document)["blocked"] = block
        session.studio.fail_next("GET", SECTIONS, status=200, body=document, times=10)
        before = posts(session)
        run = session.ut("--yes", "design", "regenerate")
        guided = session.ut("design", answers=["leave"])
        after = posts(session)

    assert run.status == 1
    assert guided.status == 0
    assert before == after
    assert said("design.menu_regenerate") not in guided.output
    assert "Go ahead with this spending?" not in run.output
    assert (
        "`ut sections`" in run.errors
        if block == "UPSTREAM_NOT_READY"
        else "web Studio" in run.errors
    )


def test_alignable_design_offers_and_executes_existing_sections_gesture(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        session.project.seed_requirements_change()
        run = session.ut("--yes", "design", answers=["update_sections", "leave"])
        alignment = session.requests("POST", "/sections/alignment")
        regenerations = session.requests("POST", REGENERATIONS)

    assert run.status == 0, run.errors
    assert said("design.menu_update_sections") in run.output
    assert any(said("design.menu_change") in option for option in menu(run.output))
    assert len(alignment) == 1
    assert regenerations == []


@pytest.mark.parametrize("action", ["show", "open"])
def test_historical_design_can_be_read_after_requirement_removal(
    tmp_path: Path, action: str
) -> None:
    with design_session(tmp_path, through="design") as session:
        removed(session)
        before = posts(session)
        run = session.ut("design", action)
        after = posts(session)

    assert run.status == 0, run.errors
    assert before == after
    if action == "show":
        assert "`ut design regenerate`" in run.output
    else:
        assert len(run.opened) == 1


@pytest.mark.parametrize("status", [404, 405])
def test_missing_sections_route_preserves_the_historical_menu(tmp_path: Path, status: int) -> None:
    with design_session(tmp_path, through="design") as session:
        session.studio.fail_next("GET", SECTIONS, status=status, body={"detail": "Not found"})
        before = posts(session)
        run = session.ut("design", answers=["leave"])
        after = posts(session)

    assert run.status == 0, run.errors
    assert said("design.menu_change") in run.output
    assert said("design.menu_regenerate") not in run.output
    assert before == after


def test_sections_authentication_error_is_not_hidden_or_sent_to_provider(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        session.studio.fail_next(
            "GET", SECTIONS, status=403, body={"detail": {"code": "FORBIDDEN"}}
        )
        before = posts(session)
        run = session.ut("--yes", "design", "change", "Bigger button")
        after = posts(session)

    assert run.status != 0
    assert before == after


def test_prepare_again_design_offers_regeneration_only_when_upstream_is_ready(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, through="design") as session:
        document = copy.deepcopy(ALL_FINE)
        design_section(document).update(state="TO_UPDATE", blocked="PREPARE_AGAIN")
        session.studio.fail_next("GET", SECTIONS, status=200, body=document)
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert said("design.recovery_prepare_again") in run.output
    assert said("design.menu_regenerate") in run.output


def test_subscription_regeneration_waits_for_the_explicit_menu_gesture(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design", billing="SUBSCRIPTION") as session:
        removed(session)
        before = posts(session)
        entry = session.ut("design", answers=["leave"])
        after_entry = posts(session)
        run = session.ut("design", answers=["regenerate", "leave"])
        started = session.count("POST", REGENERATIONS)

    assert entry.status == 0 and run.status == 0, run.errors
    assert before == after_entry
    assert started == 1
    assert "Go ahead with this spending?" not in run.output
    assert "USD" not in run.output


def test_an_actual_pending_design_revision_prevents_regeneration(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        session.project.seed_design_revision()
        before = posts(session)
        run = session.ut("--yes", "design", "regenerate")
        after = posts(session)

    assert run.status == 1
    assert said("design.recovery_revision_pending") in run.errors
    assert before == after


def test_sections_network_failure_is_not_treated_as_an_old_studio(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        before = posts(session)
        run = run_ut(
            ["--lang", "en", "--yes", "design", "change", "Bigger button"],
            tmp_path,
            transport=Unreachable("/sections"),
        )
        after = posts(session)

    assert run.status != 0
    assert before == after
    assert "does not answer" in run.errors


@pytest.mark.parametrize("status", [401, 404])
def test_sections_session_or_missing_project_errors_do_not_enable_mutations(
    tmp_path: Path, status: int
) -> None:
    with design_session(tmp_path, through="design") as session:
        code = "PROJECT_NOT_FOUND" if status == 404 else "SESSION_EXPIRED"
        session.studio.fail_next(
            "GET", SECTIONS, status=status, body={"detail": {"code": code}}, times=2
        )
        before = session.writes()
        run = session.ut("--yes", "design", "regenerate")
        after = session.writes()

    assert run.status != 0
    assert before == after


def test_a_rejected_regeneration_does_not_redraw_the_old_alternatives(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        removed(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/design/regenerations",
            status=201,
            body={
                "status": "REJECTED",
                "issue": "PROPOSAL_REJECTED",
                "version": None,
                "proposal_issue": "INVALID_PROVIDER_OUTPUT",
            },
        )
        before = session.count("POST", "/design/mockups/jobs")
        run = session.ut("design", answers=["regenerate", "y", "leave"])
        after = session.count("POST", "/design/mockups/jobs")
        version = session.project.current("design")

    assert run.status == 0
    assert "cannot be used" in run.errors
    assert before == after
    assert version["version_number"] == 2


def test_a_success_response_without_a_new_version_does_not_redraw_stale_design(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, through="design") as session:
        removed(session)
        version = session.project.current("design")
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/design/regenerations",
            status=201,
            body={"status": "CREATED", "version": version, "issue": None},
        )
        before = session.count("POST", "/design/mockups/jobs")
        run = session.ut("--yes", "design", "regenerate")
        after = session.count("POST", "/design/mockups/jobs")

    assert run.status == 1
    assert before == after


@pytest.mark.parametrize(
    "first", ["orchestwin.cli.flows.design_recovery", "orchestwin.cli.commands.design"]
)
def test_recovery_and_command_import_orders_support_the_public_regeneration_action(
    first: str,
) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    program = (
        "import argparse; import importlib; "
        f"importlib.import_module({first!r}); "
        "from orchestwin.cli.commands.design import configure; "
        "from orchestwin.cli.flows.design_recovery import Recovery; "
        "parser = argparse.ArgumentParser(); configure(parser); "
        "assert parser.parse_args(['regenerate']).action == 'regenerate'; "
        "assert Recovery(None).action is None"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
