from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from orchestwin.cli import messages
from orchestwin.cli.flows.changes import git_command

from .support.fake_studio import FakeStudio
from .support.processes import ScriptedProcesses
from .support.terminal import Run
from .test_verify_command import (
    ALIGNED_PAIR,
    FIRST,
    SECOND,
    THIRD,
    Session,
    commit,
    folder_commit,
    no_writes,
    session,
)

WIDE = {"COLUMNS": "400"}
HEADING = 'Knowledge of "Calcolo mancia" aligned with the code'
START_ALL = (
    "Starting point: no earlier review, every commit of the repository is considered (the "
    "newest 50 at most)."
)
HYPOTHESIS = "  A hypothesis of the model drawn from the code diff: no person has verified it."
MENU = [
    "What do you do with this proposal?",
    "  1. Apply",
    "  2. Edit the text and apply",
    "  3. Skip",
    "  4. Later",
]
LATER = (
    "The proposal stays waiting: decide it whenever you want with `ut align --pending` or in "
    "the web Studio."
)
REQUIREMENTS_TITLE = "Update the Definition after “Add the amount field”"
DESIGN_TITLE = "Update the Design after “Add the amount field”"
TESTS_TITLE = "Update the test plan after “Add the amount field”"
TESTS_REQUEST = "Cover the criterion AC-001 with a test path after “Add the amount field”."
CUSTOM_TEXT = "Add the split of the bill among friends to the Definition."
KNOWLEDGE_LINE = re.compile(
    r"^Knowledge: aligned with the code up to commit ([0-9a-f]{7}) \((.+)\); proposals "
    r"waiting: (\d+)\.$"
)


def ut(
    current: Session,
    *arguments: str,
    processes: ScriptedProcesses | None = None,
    answers: Sequence[str] = (),
    language: str = "en",
) -> Run:
    return current.ut(
        "align",
        *arguments,
        processes=processes,
        answers=answers,
        language=language,
        variables=WIDE,
    )


def proposals_by_code(current: Session) -> dict[str, dict[str, object]]:
    return {str(item["code"]): item for item in current.project.alignment_proposals()}


def run_bodies(studio: FakeStudio) -> list[dict[str, object]]:
    return [
        json.loads(request.body)
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/alignment/runs")
    ]


def read_local(current: Session, *parts: str) -> dict[str, object]:
    path = current.root.joinpath(".orchestwin", *parts)
    return json.loads(path.read_text(encoding="utf-8"))


def knowledge_of(lines: list[str]) -> tuple[str, int]:
    match = KNOWLEDGE_LINE.match(lines[-1])
    assert match is not None, lines[-3:]
    return match.group(1), int(match.group(3))


def test_a_first_run_reads_the_commits_and_each_proposal_gets_its_own_decision(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        processes = current.repository(ALIGNED_PAIR)
        run = ut(current, processes=processes, answers=["4", "3", "", "1"])
        proposals = proposals_by_code(current)
        runs = current.project.alignment_runs()
        recorded = {str(item["commit"]) for item in current.project.code_changes}
        bodies = run_bodies(current.studio)
        latest = read_local(current, "align", "latest.json")
        stored = read_local(current, "align", f"{runs[0]['id']}.json")
        redo = read_local(current, "tests", "redo.json")

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert lines[:2] == [HEADING, "=" * len(HEADING)]
    assert START_ALL in lines
    assert "Commits to review: 2." in lines
    assert "- 1111111  2026-09-29 10:15  Add the amount field  (files: 2)" in lines
    assert "- 2222222  2026-09-29 10:15  Show the tip  (files: 2)" in lines
    assert "Commits recorded now in the Studio: 2." in lines
    assert "Estimate: 0.20-0.40 USD, about 2 min. Credit left in the Studio: 60.00 USD." in lines
    assert "Go ahead with this spending?" not in run.output
    assert "What the code changed (2 commits, up to 2222222)" in lines
    assert "The code of 2 commits changes what the knowledge says about “Show the tip”." in lines
    assert (
        lines.index("Proposals for the Definition")
        < lines.index("Proposals for the Design")
        < lines.index("Proposals for the test plan")
    )
    assert f"ALN-001: {REQUIREMENTS_TITLE}" in lines
    assert f"ALN-002: {DESIGN_TITLE}" in lines
    assert f"ALN-003: {TESTS_TITLE}" in lines
    assert "  Commits: 1111111 Add the amount field; 2222222 Show the tip" in lines
    assert "  Files: src/app.js" in lines
    assert "  Excerpt of the diff:" in lines
    assert "    diff --git a/src/app.js b/src/app.js" in lines
    requirement = proposals["ALN-001"]["subjects"]["requirements"][0]
    assert f"  Requirements concerned: {requirement}" in lines
    assert "  Criteria concerned: AC-001" in lines
    assert lines.count(HYPOTHESIS) == 3
    assert f"Your decision on ALN-001: {REQUIREMENTS_TITLE}" in lines
    position = lines.index(MENU[0])
    assert lines[position : position + 5] == MENU
    assert "Write the number of your choice: [4] " in run.output
    assert LATER in lines
    assert "Why do you skip it? (Enter to leave it unsaid) " in run.output
    assert "Proposal ALN-002 skipped: nothing changes." in lines
    assert "Proposal ALN-003 applied." in lines
    assert (
        "The test plan must be made again: at the next `ut test` the Studio writes a new plan "
        "that takes this proposal into account." in lines
    )
    assert knowledge_of(lines) == ("2222222", 1)
    assert recorded == {FIRST, SECOND}
    assert bodies == [
        {"locale": "en-US", "from_commit": None, "to_commit": SECOND, "commits": [FIRST, SECOND]}
    ]
    assert [proposals[code]["status"] for code in ("ALN-001", "ALN-002", "ALN-003")] == [
        "PROPOSED",
        "SKIPPED",
        "APPLIED",
    ]
    assert proposals["ALN-002"]["decision_note"] is None
    assert proposals["ALN-003"]["applied_text"] == TESTS_REQUEST
    assert len(runs) == 1
    assert stored["id"] == runs[0]["id"]
    assert [item["status"] for item in stored["proposals"]] == ["PROPOSED", "SKIPPED", "APPLIED"]
    assert latest == {
        "schema_version": 1,
        "run_id": runs[0]["id"],
        "finished_at": latest["finished_at"],
        "from_commit": None,
        "to_commit": SECOND,
        "proposals": 3,
        "waiting": 1,
        "applied": 1,
        "skipped": 1,
    }
    assert latest["finished_at"].startswith("2026-09-29T")
    assert redo["schema_version"] == 1
    assert redo["proposals"] == [{"code": "ALN-003", "request": TESTS_REQUEST}]
    assert no_writes(processes)


def test_a_second_launch_starts_after_the_latest_run_and_a_dry_run_spends_nothing(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        first = ut(current, processes=current.repository(ALIGNED_PAIR), answers=["4", "4", "4"])
        later = commit(THIRD, "Round the tip", parent=SECOND)
        second = ut(current, "--dry-run", processes=current.repository([later], since=SECOND))
        nothing = ut(current, processes=current.repository([], since=SECOND))
        runs = current.project.alignment_runs()
        recorded = {str(item["commit"]) for item in current.project.code_changes}

    assert (first.status, second.status, nothing.status) == (0, 0, 0), second.errors
    lines = second.output.splitlines()
    assert "Starting point: commit 2222222, the latest one reviewed by `ut align`." in lines
    assert "- 3333333  2026-09-29 10:15  Round the tip  (files: 2)" in lines
    assert "Commits recorded now in the Studio: 1." in lines
    assert "Trial without spending (--dry-run). Commits the model would read: 1." in lines
    assert (
        "Estimate of this review: 0.20-0.40 USD, about 2 min. Without --dry-run it really "
        "starts." in lines
    )
    assert "Proposals still waiting for a decision: 3. Decide them with `ut align --pending`." in (
        lines
    )
    assert "What the code changed" not in second.output
    assert "There is no new commit to review." in nothing.output.splitlines()
    assert len(runs) == 1
    assert recorded == {FIRST, SECOND, THIRD}


def test_since_starts_after_a_commit_and_the_options_that_go_alone(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        later = commit(THIRD, "Round the tip", parent=SECOND)
        processes = current.repository([later], since=SECOND)
        processes.expect(
            git_command("rev-parse", "--verify", "--quiet", f"{SECOND[:7]}^{{commit}}"),
            output=f"{SECOND}\n",
        )
        run = ut(current, "--since", SECOND[:7], "--dry-run", processes=processes)
        unknown = current.repository([])
        unknown.expect(
            git_command("rev-parse", "--verify", "--quiet", "nowhere^{commit}"), status=1
        )
        missing = ut(current, "--since", "nowhere", processes=unknown)
        alone = ut(current, "--pending", "--since", SECOND[:7])
        dry = ut(current, "--pending", "--dry-run")

    assert run.status == 0, run.errors
    assert "Starting point: commit 2222222, given with --since." in run.output.splitlines()
    assert missing.status == 2
    assert missing.errors == (
        "The commit nowhere given with --since is not in this repository: check the hash or "
        "the name.\n"
    )
    assert (alone.status, dry.status) == (2, 2)
    assert (
        alone.errors
        == dry.errors
        == ("--pending goes alone: it cannot be used with --since or --dry-run.\n")
    )


def test_commits_of_the_knowledge_folder_alone_are_left_out(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = ut(current, processes=current.repository([folder_commit(FIRST)]))
        recorded = current.project.code_changes

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Commits that change only the knowledge folder, left out: 1 (1111111)." in lines
    assert "There is no new commit to review." in lines
    assert recorded == []


def test_pending_applies_each_section_and_approves_the_definition_and_the_design(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        seeded = current.project.seed_alignment_run()
        run = ut(current, "--pending", answers=["2", CUSTOM_TEXT, "y", "y", "1", "y", "1"])
        proposals = proposals_by_code(current)
        requirements = current.project.current("requirements")
        requirements_approved = current.project.approved("requirements")
        design = current.project.current("design")
        design_approved = current.project.approved("design")
        published = current.project.knowledge_versions()
        latest = read_local(current, "align", "latest.json")
        redo = read_local(current, "tests", "redo.json")

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Proposals waiting for a decision: 3." in lines
    assert lines.count(HYPOTHESIS) == 3
    assert "Text proposed by the model:" in lines
    assert "Press Enter to send it as it is, or write your own text: " in run.output
    assert "Proposal ALN-001 applied." in lines
    assert "Do you apply this change? [Y/n] " in run.output
    assert messages.text("init.change_applied", "en", version=2) in lines
    assert (
        "Do you approve the requirements at version 2? Then the approved design is re-anchored "
        "to this version, with its content unchanged. [Y/n] " in run.output
    )
    assert messages.text("verify.design_realigned", "en", version=3) in lines
    assert "Proposal ALN-002 applied." in lines
    assert "What changes in the design:" in lines
    assert any(line.startswith("  - The alternative “") for line in lines)
    assert (
        "Do you approve this change of the design? It becomes a new version, approved at once. "
        "[Y/n] " in run.output
    )
    assert "The design is now at version 4." in lines
    assert "Proposal ALN-003 applied." in lines
    assert knowledge_of(lines) == (str(seeded["to_commit"])[:7], 0)
    assert requirements is not None and requirements["version_number"] == 2
    assert requirements_approved
    assert design is not None and design["version_number"] == 4
    assert design_approved
    assert proposals["ALN-001"]["status"] == "APPLIED"
    assert proposals["ALN-001"]["applied_text"] == CUSTOM_TEXT
    assert proposals["ALN-001"]["applied_diff_id"] is not None
    assert proposals["ALN-002"]["status"] == proposals["ALN-003"]["status"] == "APPLIED"
    assert proposals["ALN-002"]["applied_text"] == proposals["ALN-002"]["request"]
    assert len(published) == 2
    assert (latest["run_id"], latest["proposals"], latest["waiting"]) == (seeded["id"], 3, 0)
    assert (latest["applied"], latest["skipped"]) == (3, 0)
    assert [item["code"] for item in redo["proposals"]] == ["ALN-003"]


def test_a_rejected_diff_and_a_design_left_waiting_change_only_the_proposals(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        current.project.seed_alignment_run()
        run = ut(current, "--pending", answers=["1", "n", "1", "n", "4"])
        proposals = proposals_by_code(current)
        requirements = current.project.current("requirements")
        design = current.project.current("design")
        pending_diffs = [diff["status"] for diff in current.project.design_diffs]
        published = current.project.knowledge_versions()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert messages.text("init.change_discarded", "en", version=1) in lines
    assert "Do you approve the requirements" not in run.output
    assert (
        "The change of the design waits for your decision in the Design section of the web "
        "Studio." in lines
    )
    assert LATER in lines
    assert knowledge_of(lines)[1] == 1
    assert requirements is not None and requirements["version_number"] == 1
    assert design is not None and design["version_number"] == 2
    assert pending_diffs == ["PROPOSED"]
    assert [proposals[code]["status"] for code in ("ALN-001", "ALN-002", "ALN-003")] == [
        "APPLIED",
        "APPLIED",
        "PROPOSED",
    ]
    assert published == []


def test_requirements_left_waiting_after_the_diff_send_no_gesture(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.project.seed_alignment_run()
        run = ut(current, "--pending", answers=["1", "y", "n", "4", "4"])
        requirements = current.project.current("requirements")
        approved = current.project.approved("requirements")
        gestures = [
            request.path
            for request in current.studio.requests
            if request.method == "POST" and request.path.endswith("/sections/alignment")
        ]

    assert run.status == 0, run.errors
    assert messages.text("align.requirements_left", "en", version=2) in run.output.splitlines()
    assert requirements is not None and requirements["version_number"] == 2
    assert not approved
    assert gestures == []


def test_pending_without_waiting_proposals_says_so(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = ut(current, "--pending")
        written = (current.root / ".orchestwin" / "align").exists()

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-1] == "No proposal waits for a decision."
    assert not written


def test_yes_never_decides_a_proposal(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.project.seed_alignment_run()
        run = current.ut("--yes", "align", "--pending", variables=WIDE)
        proposals = proposals_by_code(current)

    assert run.status == 1
    assert run.errors == f"{messages.text('errors.INPUT_CLOSED', 'en')}\n"
    assert MENU[0] in run.output.splitlines()
    assert all(item["status"] == "PROPOSED" for item in proposals.values())


def test_refusals_of_the_studio_leave_the_proposal_waiting_and_are_said_in_one_line(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        current.project.seed_alignment_run()
        studio = current.studio
        studio.fail_next(
            "POST",
            "/projects/{project_id}/alignment/proposals/ALN-001/apply",
            status=409,
            body={"detail": {"code": "REQUIREMENTS_UNCHANGED"}},
        )
        studio.fail_next(
            "POST",
            "/projects/{project_id}/alignment/proposals/ALN-002/apply",
            status=409,
            body={"detail": {"code": "DESIGN_REVISION_PENDING"}},
        )
        studio.fail_next(
            "POST",
            "/projects/{project_id}/alignment/proposals/ALN-003/skip",
            status=409,
            body={"detail": {"code": "ALIGNMENT_PROPOSAL_DECIDED"}},
        )
        run = ut(current, "--pending", answers=["1", "1", "3", ""])
        proposals = proposals_by_code(current)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "The model found nothing to change with this request: the proposal stays waiting." in lines
    )
    assert (
        "A change of this section already waits for your approval: approve or discard it "
        "first, then try again." in lines
    )
    assert (
        "Proposal ALN-003 was already decided, perhaps in the web Studio: nothing changes." in lines
    )
    assert all(item["status"] == "PROPOSED" for item in proposals.values())
    assert knowledge_of(lines)[1] == 3


def test_without_a_model_the_commits_stay_recorded_and_the_run_does_not_start(
    tmp_path: Path,
) -> None:
    with session(tmp_path, hosted=False) as current:
        run = ut(current, processes=current.repository(ALIGNED_PAIR))
        runs = current.project.alignment_runs()
        recorded = len(current.project.code_changes)

    assert run.status == 1
    assert "Commits recorded now in the Studio: 2." in run.output.splitlines()
    assert run.errors == (
        "This Studio cannot read the code changes, because no model is connected. The commits "
        "stay recorded; whoever runs the Studio can connect a model.\n"
    )
    assert runs == []
    assert recorded == 2


def test_a_ceiling_of_the_studio_is_named(tmp_path: Path) -> None:
    with session(tmp_path, budget_usd=0.25) as current:
        run = ut(current, processes=current.repository([commit(FIRST, "Add the amount field")]))
        runs = current.project.alignment_runs()

    assert run.status == 5
    assert "The estimate is above the credit left: the Studio may refuse the generation." in (
        run.output.splitlines()
    )
    assert run.errors == (
        "The Studio reached its overall spending ceiling (0.25 USD): the review did not start. "
        "The commits stay recorded; whoever runs the Studio can raise the ceiling; then launch "
        "`ut align` again.\n"
    )
    assert runs == []


def test_the_run_in_italian(tmp_path: Path) -> None:
    with session(tmp_path, language="it", link_language="it") as current:
        run = ut(
            current,
            processes=current.repository([commit(FIRST, "Aggiunge il campo")]),
            answers=["4", "4", "4"],
            language="it",
        )
        bodies = run_bodies(current.studio)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Conoscenza di «Calcolo mancia» allineata al codice" in lines
    assert "Proposte per la Definizione" in lines
    assert "Proposte per il Design" in lines
    assert "Proposte per il piano dei test" in lines
    assert (
        "  Ipotesi del modello ricavata dal diff del codice: nessuna persona l'ha verificata."
        in lines
    )
    assert "  4. Più tardi" in lines
    assert bodies[0]["locale"] == "it-IT"
    assert lines[-1].startswith("Conoscenza: allineata al codice fino al commit 1111111 (")
    assert lines[-1].endswith("); proposte in attesa: 3.")
