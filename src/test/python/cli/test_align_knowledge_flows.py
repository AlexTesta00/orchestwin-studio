from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import alignment as alignment_api
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import align_apply, align_knowledge
from orchestwin.cli.flows.changes import git_command
from orchestwin.cli.flows.verify_review import Titles, Workspace

from .support.processes import ScriptedProcesses
from .support.terminal import PROJECT_ID, command_context, environment, link_folder
from .support.transports import NoNetwork

RUN_ID = "00000000-0000-4000-8000-00000000a001"
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
WIDE = {"COLUMNS": "400"}
LINES = {FIRST: "Add the amount field", SECOND: "Show the tip"}
PROPOSAL = {
    "code": "ALN-001",
    "section": "REQUIREMENTS",
    "status": "PROPOSED",
    "title": "Update the Definition after the split",
    "request": "Add a requirement about splitting the bill.",
    "rationale": "The diff adds a split function.",
    "subjects": {"requirements": ["REQ-001"], "screens": ["SCR-001"], "criteria": ["AC-001"]},
    "origin": {
        "commits": [FIRST, SECOND],
        "files": ["src/app.js", "src/split.js"],
        "excerpt": "\n".join(f"+line {number}" for number in range(1, 11)),
    },
}
RUN = {
    "id": RUN_ID,
    "project_id": PROJECT_ID,
    "from_commit": None,
    "to_commit": SECOND,
    "commits": [FIRST, SECOND],
    "created_at": "2026-09-29T10:15:00+00:00",
    "summary": "The code adds a split.",
    "proposals": [
        {"code": "ALN-001", "section": "REQUIREMENTS", "status": "PROPOSED"},
        {"code": "ALN-002", "section": "DESIGN", "status": "APPLIED"},
        {"code": "ALN-003", "section": "TESTS", "status": "SKIPPED"},
    ],
}


def workspace(tmp_path: Path, alignment: dict[str, object], **options: object) -> tuple:
    processes = options.pop("processes", None)
    answers = options.pop("answers", ())
    context = command_context(
        environment(
            tmp_path,
            transport=NoNetwork(),
            processes=processes,
            answers=answers,
            variables=WIDE,
        )
    )
    project = link_folder(tmp_path / "project")
    found = Workspace(project, context.client(), PROJECT_ID, project.root, alignment)
    return context, found


def test_the_paths_and_bodies_of_the_alignment_routes() -> None:
    base = f"/projects/{PROJECT_ID}/alignment"

    assert alignment_api.runs_path(PROJECT_ID) == f"{base}/runs"
    assert alignment_api.run_path(PROJECT_ID, RUN_ID) == f"{base}/runs/{RUN_ID}"
    assert alignment_api.proposals_path(PROJECT_ID) == f"{base}/proposals"
    assert alignment_api.proposals_path(PROJECT_ID, status="all") == f"{base}/proposals?status=all"
    assert alignment_api.apply_path(PROJECT_ID, "ALN-001") == f"{base}/proposals/ALN-001/apply"
    assert alignment_api.skip_path(PROJECT_ID, "ALN-001") == f"{base}/proposals/ALN-001/skip"
    assert alignment_api.run_body("en-US", [FIRST, SECOND], None) == {
        "locale": "en-US",
        "from_commit": None,
        "to_commit": SECOND,
        "commits": [FIRST, SECOND],
    }
    assert alignment_api.apply_body("it-IT", None) == {"locale": "it-IT", "text": None}
    assert alignment_api.skip_body("  too   long  ") == {"reason": "too long"}
    assert alignment_api.skip_body("") == alignment_api.skip_body(None) == {"reason": None}
    assert len(alignment_api.skip_body("x" * 400)["reason"]) == 300
    assert alignment_api.pending_code("DESIGN_REVISION_PENDING")
    assert alignment_api.pending_code("REVISION_PENDING")
    assert not alignment_api.pending_code("DESIGN_UNCHANGED")
    assert alignment_api.unchanged_code("REQUIREMENTS_UNCHANGED")
    assert not alignment_api.unchanged_code("ALIGNMENT_PROPOSAL_DECIDED")


def test_the_proposals_document_gives_the_latest_run_and_the_waiting_items() -> None:
    document = {
        "items": [
            {"code": "ALN-003", "section": "TESTS", "status": "PROPOSED"},
            {"code": "ALN-002", "section": "DESIGN", "status": "SKIPPED"},
            {"code": "ALN-001", "section": "REQUIREMENTS", "status": "PROPOSED"},
            "noise",
        ],
        "latest_run": {"id": RUN_ID, "to_commit": SECOND},
    }

    waiting = alignment_api.waiting(document)
    ordered = alignment_api.by_section(waiting)

    assert [item["code"] for item in waiting] == ["ALN-003", "ALN-001"]
    assert [item["code"] for item in ordered] == ["ALN-001", "ALN-003"]
    assert alignment_api.latest_run(document) == {"id": RUN_ID, "to_commit": SECOND}
    assert alignment_api.latest_run({"items": [], "latest_run": None}) is None
    assert alignment_api.latest_run({"latest_run": {"to_commit": SECOND}}) is None
    assert alignment_api.waiting({"items": "none"}) == []
    assert alignment_api.proposals_of(RUN) == RUN["proposals"]
    assert alignment_api.code_of({}) == "-"
    assert alignment_api.section_of({"section": 3}) == ""


def test_the_starting_point_falls_back_from_since_to_the_run_to_verify_to_everything(
    tmp_path: Path,
) -> None:
    processes = ScriptedProcesses()
    processes.expect(
        git_command("rev-parse", "--verify", "--quiet", "abc^{commit}"), output=f"{FIRST}\n"
    )
    processes.expect(git_command("rev-parse", "--verify", "--quiet", "nowhere^{commit}"), status=1)
    context, aligned = workspace(tmp_path, {"aligned": {"commit": SECOND}}, processes=processes)
    nothing = Workspace(aligned.project, aligned.client, PROJECT_ID, aligned.root, {})

    since = align_knowledge.starting_point(context, aligned, "abc", None)
    after_run = align_knowledge.starting_point(context, aligned, None, {"to_commit": THIRD})
    after_verify = align_knowledge.starting_point(context, aligned, None, {"to_commit": ""})
    everything = align_knowledge.starting_point(context, nothing, None, None)
    with pytest.raises(CliError) as caught:
        align_knowledge.starting_point(context, aligned, "nowhere", None)
    for start in (since, after_run, after_verify, everything):
        align_knowledge.say_start(context, start)

    assert since == align_knowledge.Start(FIRST, "align.start_since")
    assert after_run == align_knowledge.Start(THIRD, "align.start_run")
    assert after_verify == align_knowledge.Start(SECOND, "align.start_verify")
    assert everything == align_knowledge.Start(None, "align.start_all")
    assert (caught.value.code, caught.value.status) == ("ALIGN_SINCE_UNKNOWN", 2)
    assert caught.value.values["commit"] == "nowhere"
    assert context.environment.stdout.getvalue().splitlines() == [
        "Starting point: commit 1111111, given with --since.",
        "Starting point: commit 3333333, the latest one reviewed by `ut align`.",
        "Starting point: commit 2222222, the aligned point of `ut verify`.",
        "Starting point: no earlier review, every commit of the repository is considered (the "
        "newest 50 at most).",
    ]
    processes.assert_done()


def test_the_local_files_of_a_run_are_written_and_read_again(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")

    run_path = align_knowledge.write_run(project, RUN)
    latest_path = align_knowledge.write_latest(
        project, RUN, waiting=1, finished_at="2026-09-29T10:20:00+00:00"
    )
    latest = json.loads(latest_path.read_bytes().decode("utf-8"))

    assert run_path == project.root / ".orchestwin" / "align" / f"{RUN_ID}.json"
    assert latest_path == project.root / ".orchestwin" / "align" / "latest.json"
    assert align_knowledge.read_run(project, RUN_ID) == RUN
    assert align_knowledge.read_run(project, "other") is None
    assert align_knowledge.read_run(project, "../project.json") is None
    assert align_knowledge.read_run(project, "") is None
    assert latest == {
        "schema_version": 1,
        "run_id": RUN_ID,
        "finished_at": "2026-09-29T10:20:00+00:00",
        "from_commit": None,
        "to_commit": SECOND,
        "proposals": 3,
        "waiting": 1,
        "applied": 1,
        "skipped": 1,
    }
    assert align_knowledge.read_latest(project) == latest
    assert align_knowledge.folder_version(project) is None


@pytest.mark.parametrize(
    "document",
    [None, "text", {"schema_version": 2, "run_id": RUN_ID}, {"schema_version": 1, "run_id": ""}],
)
def test_a_latest_file_that_cannot_be_read_counts_as_missing(
    tmp_path: Path, document: object
) -> None:
    project = link_folder(tmp_path / "project")
    target = align_knowledge.latest_file(project)
    target.parent.mkdir(parents=True)
    target.write_text("" if document is None else json.dumps(document), encoding="utf-8")

    assert align_knowledge.read_latest(project) is None


def test_a_proposal_is_shown_with_its_origin_its_subjects_and_the_hypothesis(
    tmp_path: Path,
) -> None:
    context, _ = workspace(tmp_path, {})
    names = Titles(requirements={"REQ-001": "Tip amount"}, screens={"SCR-001": "Home"})

    align_knowledge.show_proposal(context, PROPOSAL, names, LINES)

    assert context.environment.stdout.getvalue().splitlines() == [
        "",
        "ALN-001: Update the Definition after the split",
        "  Add a requirement about splitting the bill.",
        "  Why: The diff adds a split function.",
        "  Commits: 1111111 Add the amount field; 2222222 Show the tip",
        "  Files: src/app.js, src/split.js",
        "  Excerpt of the diff:",
        *(f"    +line {number}" for number in range(1, 9)),
        "    (2 more lines in the excerpt)",
        '  Requirements concerned: REQ-001 "Tip amount"',
        '  Screens concerned: SCR-001 "Home"',
        "  Criteria concerned: AC-001",
        "  A hypothesis of the model drawn from the code diff: no person has verified it.",
    ]


def test_a_run_without_proposals_says_so_after_its_summary(tmp_path: Path) -> None:
    context, _ = workspace(tmp_path, {})
    names = Titles(requirements={}, screens={})

    align_knowledge.show_run(context, {**RUN, "proposals": []}, names, LINES)

    assert context.environment.stdout.getvalue().splitlines() == [
        "",
        "What the code changed (2 commits, up to 2222222)",
        "=" * len("What the code changed (2 commits, up to 2222222)"),
        "The code adds a split.",
        "The model proposes no update: the code does not change what the knowledge says.",
    ]


def test_commit_labels_match_abbreviated_hashes() -> None:
    assert align_knowledge.commit_label(FIRST[:7], LINES) == "1111111 Add the amount field"
    assert align_knowledge.commit_label(FIRST, {FIRST[:12]: "Short"}) == "1111111 Short"
    assert align_knowledge.commit_label("abcdef0", LINES) == "abcdef0"
    assert align_knowledge.commit_label("", LINES) == ""


def test_the_menu_defaults_to_later_and_refuses_after_five_wrong_answers(tmp_path: Path) -> None:
    options = [Choice(key, key) for key in align_apply.ORDER]
    later, _ = workspace(tmp_path, {}, answers=[""])
    named, _ = workspace(tmp_path / "named", {}, answers=["skip"])
    wrong, _ = workspace(tmp_path / "wrong", {}, answers=["x", "9", "0", "x", "x"])

    chosen = align_apply.menu(later, options)
    by_name = align_apply.menu(named, options)
    with pytest.raises(CliError) as caught:
        align_apply.menu(wrong, options)

    assert chosen.key == align_apply.LATER
    assert by_name.key == align_apply.SKIP
    assert caught.value.code == "ANSWER_NOT_VALID"
    lines = later.environment.stdout.getvalue().splitlines()
    assert lines[0] == messages.text("align.decision_question", "en")
    assert lines[1:5] == [f"  {number}. {key}" for number, key in enumerate(align_apply.ORDER, 1)]
    assert lines[5].startswith(f"{messages.text('common.choose_prompt', 'en')} [4] ")


def test_the_estimate_of_a_run_names_the_amount_or_the_subscription() -> None:
    estimate = align_knowledge.costs.estimate([alignment_api.OPERATION])

    assert (estimate.low_usd, estimate.high_usd, estimate.minutes) == (0.2, 0.4, 2.0)
    assert align_knowledge.costs.ESTIMATES["DESIGN_CHANGE"].high_usd == 0.5
