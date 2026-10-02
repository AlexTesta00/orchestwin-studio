from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.flows.changes import git_command
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.processes import FakeCommit, FakeFile, ScriptedProcesses, script_repository
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut

EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
DIFF = (
    "diff --git a/src/app.js b/src/app.js\n"
    "--- a/src/app.js\n"
    "+++ b/src/app.js\n"
    "@@ -1 +1 @@\n"
    "-const tip = 0;\n"
    "+const tip = choose(); // REQ-002\n"
)
WRITING_WORDS = ("commit", "add", "push", "reset", "checkout", "stash", "rebase", "merge")


def commit(hash_value: str, message: str, *, parent: str | None = None) -> FakeCommit:
    return FakeCommit(
        hash_value,
        message,
        files=(FakeFile("src/app.js", added=1, removed=1), FakeFile(".env", status="A")),
        parent=parent,
        diff=DIFF,
    )


ALIGNED_PAIR = (
    commit(FIRST, "Add the amount field"),
    commit(SECOND, "Show the tip", parent=FIRST),
)
FOLDER_DIFF = (
    "diff --git a/orchestwin/state/state.md b/orchestwin/state/state.md\n"
    "--- a/orchestwin/state/state.md\n"
    "+++ b/orchestwin/state/state.md\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


def folder_commit(hash_value: str, *, parent: str | None = None, prefix: str = "") -> FakeCommit:
    return FakeCommit(
        hash_value,
        "Update the knowledge folder",
        files=(
            FakeFile(f"{prefix}orchestwin/state/state.md"),
            FakeFile(f"{prefix}.orchestwin/steps/design.json", status="A"),
        ),
        parent=parent,
        diff=FOLDER_DIFF,
    )


def decide_command(hash_value: str) -> list[str]:
    return git_command("rev-parse", "--verify", "--quiet", f"{hash_value[:7]}^{{commit}}")


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    @property
    def root(self) -> Path:
        return self.tmp_path / "project"

    def repository(
        self, commits: Sequence[FakeCommit], *, since: str | None = None, status: str = ""
    ) -> ScriptedProcesses:
        return script_repository(
            ScriptedProcesses(), self.root, commits, since=since, status=status
        )

    def ut(
        self,
        *arguments: str,
        processes: ScriptedProcesses | None = None,
        answers: Sequence[str] = (),
        language: str = "en",
        variables: Mapping[str, str] | None = None,
    ) -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
            processes=processes,
            variables=variables,
        )

    def decisions(self) -> dict[str, object]:
        return {
            str(change["commit"]): change["decision"] and change["decision"]["kind"]
            for change in self.project.changes()
        }


@contextmanager
def session(
    tmp_path: Path,
    *,
    hosted: bool = True,
    language: str = "en",
    through: str = "design",
    budget_usd: float | None = 60.0,
    link_language: str | None = None,
    billing: str | None = None,
) -> Iterator[Session]:
    with FakeStudio(
        language=language, hosted=hosted, twins=2, budget_usd=budget_usd, billing=billing
    ) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through=through)
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(
            tmp_path / "project",
            project_id=project.id,
            name=NAME,
            studio=studio.address,
            language=link_language,
        )
        yield Session(studio=studio, project=project, tmp_path=tmp_path)
        assert studio.errors == []


def no_writes(processes: ScriptedProcesses) -> bool:
    return all(
        not any(word in call.arguments for word in WRITING_WORDS) for call in processes.calls
    )


def test_two_aligned_commits_are_recorded_reviewed_and_the_newest_becomes_the_point(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        processes = current.repository(ALIGNED_PAIR)

        run = current.ut("align", processes=processes, answers=["y", ""])

        changes = current.project.changes()
        runs = current.project.change_reviews()
        aligned = current.project.aligned()
        recorded = {str(item["commit"]): item for item in current.project.code_changes}
    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert lines[:8] == [
        'Alignment of "Calcolo mancia"',
        "=============================",
        "Approved reference: requirements version 1, design version 2 (alternative DES-002).",
        "No commit is aligned yet.",
        "Commits of the repository considered (the newest 50 at most): 2.",
        "- 1111111  2026-09-29 10:15  Add the amount field  (files: 2)",
        "- 2222222  2026-09-29 10:15  Show the tip  (files: 2)",
        "Commits recorded now in the Studio: 2.",
    ]
    assert (
        "Commits for the twins to review: 2. Twins in each review: 2. Each twin gives its "
        "opinion on each commit, then the model says whether code, design and requirements are "
        "still aligned." in lines
    )
    assert "Estimate: 0.90-1.60 USD, about 6 min. Credit left in the Studio: 60.00 USD." in lines
    assert "Review of commit 1111111: Add the amount field" in lines
    assert "Review of commit 2222222: Show the tip" in lines
    assert "Your decision on commit 2222222: Show the tip" in lines
    assert "  1. Mark this commit as aligned" in lines
    assert (
        "Commit 2222222 is now the aligned point: the open tasks for the code that come from "
        "this commit or from earlier ones are closed; those of newer commits stay open." in lines
    )
    assert "Commit 1111111: same verdict as 2222222, recorded as covered by it." in lines
    assert (
        "Knowledge folder updated in orchestwin/ (version 1): orchestwin/state holds the state "
        "of the development." in lines
    )
    assert lines[-1] == (
        "Development: commits recorded: 2; after the aligned point: 0; aligned commit: "
        "2222222; open tasks for the code: 0."
    )
    assert [change["decision"]["kind"] for change in changes] == ["ALIGNED", "DISMISSED"]
    assert changes[1]["decision"]["note"] == "covered by 2222222"
    assert len(runs) == 2
    assert aligned is not None and aligned["commit"] == SECOND
    assert recorded[FIRST]["diff"] == DIFF + "[excluded: .env]\n"
    assert recorded[FIRST]["files"] == [
        {"path": "src/app.js", "kind": "MODIFIED", "added": 1, "removed": 1},
        {"path": ".env", "kind": "ADDED", "added": 1, "removed": 0},
    ]
    assert recorded[SECOND]["parent"] == FIRST
    state = json.loads(
        (current.root / "orchestwin" / "state" / "state.json").read_text(encoding="utf-8")
    )
    assert [item["commit"] for item in state["changes"]] == [SECOND, FIRST]
    assert no_writes(processes)


def test_a_second_launch_starts_after_the_aligned_commit(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        first = current.ut("align", processes=current.repository(ALIGNED_PAIR), answers=["y", ""])
        later = commit(THIRD, "Round the tip", parent=SECOND)
        processes = current.repository([later], since=SECOND)

        second = current.ut("align", "--dry-run", processes=processes)
        nothing = current.ut("align", processes=current.repository([], since=SECOND))

    assert first.status == 0, first.errors
    assert second.status == 0, second.errors
    lines = second.output.splitlines()
    assert any(
        line.startswith("Aligned point: commit 2222222 of 2026-09-29 ")
        and line.endswith(", with requirements version 1 and design version 2.")
        for line in lines
    )
    assert "Commits after the aligned point: 1." in lines
    assert "Trial without spending (--dry-run). Commits the twins would review: 1." in lines
    assert "- 3333333  2026-09-29 10:15  Round the tip  (files: 2)" in lines
    assert (
        "Estimate of these reviews: 0.45-0.80 USD, about 3 min. Without --dry-run they really "
        "start." in lines
    )
    assert "Review of commit" not in second.output
    assert nothing.status == 0
    assert "There is no new commit to align." in nothing.output


def test_code_drift_records_the_tasks_of_the_model_as_edited(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        drift = commit(FIRST, "The tip choice drifts from the screen")
        run = current.ut(
            "align",
            processes=current.repository([drift]),
            answers=["y", "", "", "Cover the tip choice with a test"],
        )
        tasks = current.project.tasks()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "  1. Record these tasks for the code" in lines
    assert "  2. Mark it as aligned anyway" in lines
    assert (
        "Tasks recorded for the code: 2. They stay open until this commit or a later one is "
        "marked as aligned." in lines
    )
    assert [task["text"] for task in tasks] == [
        "Bring the code back in line with screen SCR-001 of the approved design.",
        "Cover the tip choice with a test",
    ]
    assert [task["code"] for task in tasks] == ["TSK-001", "TSK-002"]
    assert lines[-1] == (
        "Development: commits recorded: 1; none aligned yet (waiting: 1); open tasks for the "
        "code: 2."
    )


def test_a_task_of_the_model_can_be_dropped_and_a_blank_one_is_never_sent(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        drift = commit(FIRST, "Drift in the totals")
        run = current.ut("align", processes=current.repository([drift]), answers=["y", "", "-", ""])
        tasks = current.project.tasks()
        bodies = [
            json.loads(request.body)
            for request in current.studio.requests
            if request.path.endswith("/decision")
        ]

    assert run.status == 0, run.errors
    assert [task["text"] for task in tasks] == ["Cover requirement REQ-002 with an automated test."]
    assert bodies == [
        {
            "kind": "CODE_TASKS",
            "note": None,
            "tasks": ["Cover requirement REQ-002 with an automated test."],
        }
    ]


def test_tasks_written_by_the_owner_for_an_aligned_commit(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "2", "Add a label to the amount", "  ", ""],
        )
        tasks = current.project.tasks()

    assert run.status == 0, run.errors
    assert (
        "Write the tasks for the code, one per line (at most 10); an empty line ends the list."
        in run.output
    )
    assert [task["text"] for task in tasks] == ["Add a label to the amount"]


def test_leaving_it_for_later_records_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "5"],
        )
        decisions = current.decisions()
        publications = [
            request
            for request in current.studio.requests
            if request.method == "POST" and request.path.endswith("/knowledge-packages")
        ]

    assert run.status == 0, run.errors
    assert (
        "Nothing recorded: the commit waits for your decision. Launch `ut align` again whenever "
        "you want." in run.output
    )
    assert decisions == {FIRST: None}
    assert publications == []


def test_an_earlier_commit_with_another_verdict_gets_its_own_question(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        commits = [
            commit(FIRST, "Drift of the totals"),
            commit(SECOND, "Show the tip", parent=FIRST),
        ]
        run = current.ut("align", processes=current.repository(commits), answers=["y", "", "later"])
        decisions = current.decisions()

    assert run.status == 0, run.errors
    assert "Your decision on commit 2222222: Show the tip" in run.output
    assert "Your decision on commit 1111111: Drift of the totals" in run.output
    assert decisions == {SECOND: "ALIGNED", FIRST: None}


def test_a_design_that_is_outdated_gets_a_new_version_approved(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        evolution = commit(FIRST, "Rework the card of the design")
        run = current.ut(
            "align", processes=current.repository([evolution]), answers=["y", "", "", "y", "y"]
        )
        changes = current.project.changes()
        design = current.project.current("design")
        approved = current.project.approved("design")

    assert run.status == 0, run.errors
    assert "  1. Ask a new version of the design with this request" in run.output
    assert "Change applied: the design is now at version 3, to be approved." in run.output
    assert (
        "Decision recorded: a new version of the design was asked from commit 1111111."
        in run.output
    )
    assert "Do you approve version 3 of the design now? [Y/n] " in run.output
    assert changes[0]["decision"]["kind"] == "DESIGN_CHANGE"
    assert changes[0]["decision"]["note"].startswith("Update the design so that it describes")
    assert design is not None and design["version_number"] == 3
    assert approved
    assert (current.root / "orchestwin" / "orchestwin.json").is_file()


def test_the_new_design_version_can_wait_for_a_later_approval(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        evolution = commit(FIRST, "Rework the card of the design")
        run = current.ut(
            "align",
            processes=current.repository([evolution]),
            answers=["y", "", "Make the card larger", "y", "n"],
        )
        changes = current.project.changes()
        approved = current.project.approved("design")

    assert run.status == 0, run.errors
    assert changes[0]["decision"] == {
        "kind": "DESIGN_CHANGE",
        "decided_at": changes[0]["decision"]["decided_at"],
        "note": "Make the card larger",
    }
    assert (
        "Version 3 of the design waits for your approval: approve it with `ut design approve`."
        in run.output
    )
    assert not approved


def test_requirements_that_are_outdated_get_a_change_approved(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        evolution = commit(FIRST, "New requirement: split among friends")
        run = current.ut(
            "align", processes=current.repository([evolution]), answers=["y", "", "", "y", "y"]
        )
        changes = current.project.changes()
        requirements = current.project.current("requirements")
        saved = json.loads(
            (current.root / ".orchestwin" / "steps" / "requirements.json").read_text(
                encoding="utf-8"
            )
        )

    assert run.status == 0, run.errors
    assert "  1. Ask a change of the requirements with this request" in run.output
    assert "Change applied: the requirements are at version 2." in run.output
    assert "check the design with `ut design`" not in run.output
    assert changes[0]["decision"]["kind"] == "REQUIREMENTS_CHANGE"
    assert requirements is not None and requirements["version_number"] == 2
    assert saved["version"]["version_number"] == 2


def test_without_a_model_the_commits_are_recorded_and_the_command_ends_with_1(
    tmp_path: Path,
) -> None:
    with session(tmp_path, hosted=False) as current:
        run = current.ut("align", processes=current.repository(ALIGNED_PAIR))
        changes = current.project.changes()
        runs = current.project.change_reviews()

    assert run.status == 1
    assert "Commits recorded now in the Studio: 2." in run.output
    assert run.errors == (
        "The twins cannot review the code on this Studio, because no model is connected "
        "(CHANGE_REVIEW_MODEL_NOT_CONFIGURED). The commits stay recorded; whoever runs the "
        "Studio can connect a model.\n"
    )
    assert len(changes) == 2
    assert runs == []


def test_a_ceiling_of_the_studio_is_named(tmp_path: Path) -> None:
    with session(tmp_path, budget_usd=0.5) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y"],
        )

    assert run.status == 5
    assert "The estimate is above the credit left: the Studio may refuse the generation." in (
        run.output
    )
    assert run.errors == (
        "The Studio reached its overall spending ceiling (0.50 USD): the review did not start. "
        "The commits stay recorded; whoever runs the Studio can raise the ceiling, then launch "
        "`ut align` again.\n"
    )


def test_a_refused_spending_reviews_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut("align", processes=current.repository(ALIGNED_PAIR), answers=["n"])
        runs = current.project.change_reviews()

    assert run.status == 5
    assert runs == []
    assert "No generation started: the spending was not confirmed." in run.errors


def test_latest_reviews_only_the_newest_commit(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align", "--latest", processes=current.repository(ALIGNED_PAIR), answers=["y", ""]
        )
        runs = current.project.change_reviews()
        decisions = current.decisions()

    assert run.status == 0, run.errors
    assert [item["commit"] for item in runs] == [SECOND]
    assert decisions == {SECOND: "ALIGNED", FIRST: None}


def test_since_starts_after_a_commit_of_the_repository(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        processes = current.repository([ALIGNED_PAIR[1]], since=FIRST)
        processes.expect(
            git_command("rev-parse", "--verify", "--quiet", f"{FIRST[:7]}^{{commit}}"),
            output=f"{FIRST}\n",
        )
        unknown = current.repository([])
        unknown.expect(
            git_command("rev-parse", "--verify", "--quiet", "nothing^{commit}"), status=1
        )

        run = current.ut("align", "--since", FIRST[:7], "--dry-run", processes=processes)
        refused = current.ut("align", "--since", "nothing", processes=unknown)

    assert run.status == 0, run.errors
    assert "Commits after 1111111: 1." in run.output
    assert refused.status == 2
    assert refused.errors == (
        "The commit nothing given with --since is not in this repository: check the hash or the "
        "name.\n"
    )


def test_changes_not_committed_are_mentioned_but_not_those_of_ut(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        dirty = current.ut(
            "align",
            "--dry-run",
            processes=current.repository(ALIGNED_PAIR, status=" M src/app.js\x00"),
        )
        own = current.ut(
            "align",
            "--dry-run",
            processes=current.repository(
                ALIGNED_PAIR, status="?? .orchestwin/\x00 M orchestwin/state/state.md\x00"
            ),
        )

    sentence = "The folder has changes not saved in a commit yet: ut align considers only commits."
    assert sentence in dirty.output
    assert sentence not in own.output


def test_a_design_not_yet_approved_is_asked_first(tmp_path: Path) -> None:
    with session(tmp_path, through="requirements") as current:
        processes = current.repository(ALIGNED_PAIR)
        run = current.ut("align", processes=processes)

    assert run.status == 1
    assert run.errors == (
        "The design is not approved yet (ALIGN_DESIGN_REQUIRED): choose and approve it with "
        "`ut design`, then the code can be aligned with it.\n"
    )
    assert [call.arguments[-1] for call in processes.calls] == ["--show-toplevel"]


def test_the_folder_must_be_in_a_git_repository_and_git_must_exist(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        outside = ScriptedProcesses().expect(
            git_command("rev-parse", "--show-toplevel"), status=128
        )
        no_git = current.ut("align")
        not_a_repository = current.ut("align", processes=outside)

    assert no_git.status == 1
    assert no_git.errors == (
        "The git program is not installed or cannot be found (GIT_NOT_AVAILABLE): install it, "
        "then try again.\n"
    )
    assert not_a_repository.status == 1
    assert "is not inside a git repository (ALIGN_NO_GIT)" in not_a_repository.errors


def test_a_folder_that_is_not_linked_or_not_signed_in(tmp_path: Path) -> None:
    unlinked = run_ut(["align"], tmp_path, transport=UrlTransport())
    link_folder(tmp_path / "project")
    anonymous = run_ut(["align"], tmp_path, transport=UrlTransport())

    assert unlinked.status == 6
    assert anonymous.status == 3
    assert "ut login" in anonymous.errors


def test_a_review_made_earlier_is_not_asked_again(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        first = current.ut(
            "align", processes=current.repository(ALIGNED_PAIR), answers=["y", "later"]
        )
        again = current.ut("align", processes=current.repository(ALIGNED_PAIR), answers=[""])
        runs = current.project.change_reviews()
        decisions = current.decisions()

    assert first.status == 0, first.errors
    assert again.status == 0, again.errors
    assert "Every commit to consider already has a review of the twins." in again.output
    assert "Go ahead with this spending?" not in again.output
    assert len(runs) == 2
    assert decisions == {SECOND: "ALIGNED", FIRST: "DISMISSED"}


def test_the_review_in_italian(tmp_path: Path) -> None:
    with session(tmp_path, language="it", link_language="it") as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Aggiunge il campo")]),
            answers=["s", ""],
            language="it",
        )
        locales = [
            json.loads(request.body)["locale"]
            for request in current.studio.requests
            if request.path.endswith("/reviews") and request.method == "POST"
        ]
        note = current.project.changes()[0]["decision"]

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Allineamento di «Calcolo mancia»" in lines
    assert "Verdetto del modello" in lines
    assert "Il codice è allineato ai requisiti e al design approvati (ALIGNED)." in lines
    assert "  1. Segna questo commit come allineato" in lines
    assert locales == ["it-IT"]
    assert note["kind"] == "ALIGNED"


DESIGN_FOLLOW = "Ask a new version of the design that follows this commit"
REQUIREMENTS_FOLLOW = "Ask a change of the requirements that follows this commit"
MENU_LINES = {
    "Add the amount field": [
        "  1. Mark this commit as aligned",
        "  2. Record tasks for the code",
        f"  3. {DESIGN_FOLLOW}",
        f"  4. {REQUIREMENTS_FOLLOW}",
        "  5. Leave it for later",
    ],
    "Rework the card of the design": [
        "  1. Ask a new version of the design with this request",
        "  2. Mark it as aligned anyway",
        "  3. Record tasks for the code",
        f"  4. {REQUIREMENTS_FOLLOW}",
        "  5. Leave it for later",
    ],
    "New requirement: split the bill": [
        "  1. Ask a change of the requirements with this request",
        "  2. Mark it as aligned anyway",
        "  3. Record tasks for the code",
        f"  4. {DESIGN_FOLLOW}",
        "  5. Leave it for later",
    ],
    "The tip choice drifts": [
        "  1. Record these tasks for the code",
        "  2. Mark it as aligned anyway",
        f"  3. {DESIGN_FOLLOW}",
        f"  4. {REQUIREMENTS_FOLLOW}",
        "  5. Leave it for later",
    ],
}


LATER_SAID = (
    "Nothing recorded: the commit waits for your decision. Launch `ut align` again whenever you "
    "want."
)
NO_REQUEST = "No request written: nothing recorded."
NO_TASK = "No task written: nothing recorded."


@pytest.mark.parametrize(
    ("message", "answers", "kind", "said"),
    [
        ("Add the amount field", ["y", "later"], None, LATER_SAID),
        ("Add the amount field", ["y", "3", ""], None, NO_REQUEST),
        ("Add the amount field", ["y", "4", ""], None, NO_REQUEST),
        ("The tip choice drifts", ["y", "2"], "ALIGNED", None),
        ("The tip choice drifts", ["y", "5"], None, LATER_SAID),
        ("The tip choice drifts", ["y", "design", ""], None, NO_REQUEST),
        ("The tip choice drifts", ["y", "requirements", ""], None, NO_REQUEST),
        ("Rework the card of the design", ["y", "2"], "ALIGNED", None),
        ("Rework the card of the design", ["y", "3", ""], None, NO_TASK),
        ("Rework the card of the design", ["y", "4", ""], None, NO_REQUEST),
        ("Rework the card of the design", ["y", "5"], None, LATER_SAID),
        (
            "New requirement: split the bill",
            ["y", "3", "Split the bill in the code", ""],
            "CODE_TASKS",
            None,
        ),
        ("New requirement: split the bill", ["y", "2"], "ALIGNED", None),
        ("New requirement: split the bill", ["y", "4", ""], None, NO_REQUEST),
    ],
)
def test_every_other_choice_of_the_menus(
    tmp_path: Path, message: str, answers: list[str], kind: str | None, said: str | None
) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align", processes=current.repository([commit(FIRST, message)]), answers=answers
        )
        decisions = current.decisions()
        tasks = current.project.tasks()
        posts = [
            request.path
            for request in current.studio.requests
            if request.method == "POST" and request.path.endswith(("/jobs", "/change-requests"))
        ]

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    menu = lines.index("What do you do with this commit?")
    assert lines[menu + 1 : menu + 6] == MENU_LINES[message]
    assert decisions == {FIRST: kind}
    assert [task["text"] for task in tasks] == (
        ["Split the bill in the code"] if kind == "CODE_TASKS" else []
    )
    assert posts == []
    if said is not None:
        assert said in lines


def test_an_aligned_commit_can_ask_a_design_that_follows_it(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "design", "Make the card larger", "", "y", "y"],
        )
        change = current.project.changes()[0]
        design = current.project.current("design")
        approved = current.project.approved("design")

    assert run.status == 0, run.errors
    assert (
        "Describe in words what should change so that it follows this commit (an empty text "
        "cancels and records nothing):" in run.output.splitlines()
    )
    assert "Change applied: the design is now at version 3, to be approved." in run.output
    assert change["decision"]["kind"] == "DESIGN_CHANGE"
    assert change["decision"]["note"] == "Make the card larger"
    assert design is not None and design["version_number"] == 3
    assert approved


def test_code_drift_can_ask_the_requirements_to_follow_the_code(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "The tip choice drifts")]),
            answers=["y", "requirements", "Each person chooses a tip", "", "y", "y"],
        )
        change = current.project.changes()[0]
        requirements = current.project.current("requirements")

    assert run.status == 0, run.errors
    assert "Change applied: the requirements are at version 2." in run.output
    assert said("align.design_realigned", version=3) in run.output.splitlines()
    assert change["decision"]["kind"] == "REQUIREMENTS_CHANGE"
    assert change["decision"]["note"] == "Each person chooses a tip"
    assert requirements is not None and requirements["version_number"] == 2


@pytest.mark.parametrize(
    ("code", "status", "sentence"),
    [
        (
            "REQUIREMENTS_APPROVAL_REQUIRED",
            409,
            "The requirements are not approved at the moment (REQUIREMENTS_APPROVAL_REQUIRED): "
            "approve them with `ut init`, then launch `ut align` again.\n",
        ),
        (
            "USER_MODELING_APPROVAL_REQUIRED",
            409,
            "The User Twins are not approved at the moment (USER_MODELING_APPROVAL_REQUIRED): "
            "approve them with `ut init`, then launch `ut align` again.\n",
        ),
        (
            "INVALID_PROVIDER_OUTPUT",
            502,
            "The model gave an answer that the Studio cannot use (INVALID_PROVIDER_OUTPUT): "
            "nothing was stored. Launching `ut align` again tries once more, and it is a new "
            "spending.\n",
        ),
        (
            "TOO_MANY_GENERATIONS",
            429,
            "Too many generations are already running in the Studio: wait for one to finish, "
            "then try again.\n",
        ),
    ],
)
def test_a_review_refused_by_the_studio_is_explained(
    tmp_path: Path, code: str, status: int, sentence: str
) -> None:
    with session(tmp_path) as current:
        current.studio.fail_job("CODE_CHANGE_REVIEW", code=code, status=status)
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y"],
        )
        changes = current.project.changes()

    assert run.status == 1
    assert run.errors == sentence
    assert "Review of commit 1111111: not completed after" in run.output
    assert [change["commit"] for change in changes] == [FIRST]


def test_a_folder_that_the_studio_does_not_publish_is_said_in_one_line(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=409,
            body={"detail": {"code": "KNOWLEDGE_PACKAGE_VERSION_CONFLICT"}},
        )
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", ""],
        )
        decisions = current.decisions()

    assert run.status == 0, run.errors
    assert (
        "The Studio did not publish the knowledge folder (KNOWLEDGE_PACKAGE_VERSION_CONFLICT): "
        "the decision is recorded; publish it later with `ut package publish`."
        in run.output.splitlines()
    )
    assert decisions == {FIRST: "ALIGNED"}


def review_posts(studio: FakeStudio) -> list[str]:
    return [
        request.path
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/reviews")
    ]


def test_a_commit_of_the_knowledge_folder_is_recorded_never_reviewed_and_dismissed(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        commits = [commit(FIRST, "Add the amount field"), folder_commit(SECOND, parent=FIRST)]
        run = current.ut("align", processes=current.repository(commits), answers=["y", ""])
        changes = {str(change["commit"]): change for change in current.project.changes()}
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Commits recorded now in the Studio: 2." in lines
    assert (
        "Commits that change only the knowledge folder, recorded without a review: 1 "
        "(2222222); the newest needs no decision and is marked as dismissed." in lines
    )
    assert "Estimate: 0.45-0.80 USD, about 3 min. Credit left in the Studio: 60.00 USD." in lines
    assert "Review of commit 2222222" not in run.output
    assert "Your decision on commit 1111111: Add the amount field" in lines
    assert [item["commit"] for item in runs] == [FIRST]
    assert changes[SECOND]["decision"]["kind"] == "DISMISSED"
    assert changes[SECOND]["decision"]["note"] == "knowledge folder only"
    assert changes[FIRST]["decision"]["kind"] == "ALIGNED"
    assert lines[-1] == (
        "Development: commits recorded: 2; after the aligned point: 1; aligned commit: "
        "1111111; open tasks for the code: 0."
    )


def test_an_older_commit_of_the_knowledge_folder_is_skipped_without_a_decision(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        commits = [folder_commit(FIRST), commit(SECOND, "Show the tip", parent=FIRST)]
        run = current.ut("align", processes=current.repository(commits), answers=["y", ""])
        decisions = current.decisions()
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    assert (
        "Commits that change only the knowledge folder, recorded without a review: 1 (1111111)."
        in run.output.splitlines()
    )
    assert [item["commit"] for item in runs] == [SECOND]
    assert decisions == {SECOND: "ALIGNED", FIRST: None}


def test_a_folder_commit_of_an_italian_project_in_a_subfolder_of_the_repository(
    tmp_path: Path,
) -> None:
    with session(tmp_path, link_language="it") as current:
        processes = script_repository(
            ScriptedProcesses(), tmp_path, [folder_commit(FIRST, prefix="project/")]
        )
        run = current.ut("align", processes=processes, language="it")
        changes = current.project.changes()
        posts = review_posts(current.studio)

    assert run.status == 0, run.errors
    assert (
        "Commit che cambiano soltanto la cartella di conoscenza, registrati senza farli "
        "esaminare: 1 (1111111); il più recente non ha bisogno di una decisione ed è segnato "
        "come scartato." in run.output.splitlines()
    )
    assert "Stima" not in run.output
    assert changes[0]["decision"]["note"] == "solo cartella di conoscenza"
    assert posts == []


def test_a_dry_run_dismisses_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        commits = [commit(FIRST, "Add the amount field"), folder_commit(SECOND, parent=FIRST)]
        run = current.ut("align", "--dry-run", processes=current.repository(commits))
        decisions = current.decisions()

    assert run.status == 0, run.errors
    assert (
        "Commits that change only the knowledge folder, recorded without a review: 1 (2222222)."
        in run.output.splitlines()
    )
    assert "Trial without spending (--dry-run). Commits the twins would review: 1." in run.output
    assert decisions == {SECOND: None, FIRST: None}


def test_latest_reviews_the_newest_commit_of_the_code(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        commits = [commit(FIRST, "Add the amount field"), folder_commit(SECOND, parent=FIRST)]
        run = current.ut(
            "align", "--latest", processes=current.repository(commits), answers=["y", ""]
        )
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    assert [item["commit"] for item in runs] == [FIRST]


def test_decide_opens_the_menu_again_without_reviews_or_records(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        first = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "later"],
        )
        before = len(current.studio.requests)
        processes = current.repository([])
        processes.expect(decide_command(FIRST), output=f"{FIRST}\n")
        again = current.ut("align", "--decide", FIRST[:7], processes=processes, answers=[""])
        later = [
            (request.method, request.path.rsplit("/", 1)[-1])
            for request in current.studio.requests[before:]
            if request.method == "POST"
        ]
        decisions = current.decisions()

    assert first.status == 0, first.errors
    assert again.status == 0, again.errors
    lines = again.output.splitlines()
    assert "Review of commit 1111111: Add the amount field" in lines
    assert "Your decision on commit 1111111: Add the amount field" in lines
    assert "Estimate" not in again.output
    assert "Commits recorded now" not in again.output
    assert "Decision taken before" not in again.output
    assert ("POST", "reviews") not in later
    assert ("POST", "code-changes") not in later
    assert ("POST", "decision") in later
    assert decisions == {FIRST: "ALIGNED"}


def test_decide_replaces_an_earlier_decision_and_newer_tasks_stay_open(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        commits = [
            commit(FIRST, "The tip choice drifts"),
            commit(SECOND, "The totals drift too", parent=FIRST),
        ]
        first = current.ut(
            "align", processes=current.repository(commits), answers=["y", "", "", ""]
        )
        processes = current.repository([])
        processes.expect(decide_command(FIRST), output=f"{FIRST}\n")
        again = current.ut("align", "--decide", FIRST[:7], processes=processes, answers=["2"])
        decisions = current.decisions()
        tasks = current.project.tasks()

    assert first.status == 0, first.errors
    assert again.status == 0, again.errors
    assert (
        "Decision taken before on this commit: dismissed. The new one replaces it."
        in again.output.splitlines()
    )
    assert "  2. Mark it as aligned anyway" in again.output.splitlines()
    assert decisions == {SECOND: "CODE_TASKS", FIRST: "ALIGNED"}
    assert [(task["from_commit"], task["status"]) for task in tasks] == [
        (SECOND, "OPEN"),
        (SECOND, "OPEN"),
    ]


def test_decide_refusals(tmp_path: Path) -> None:
    with session(tmp_path, hosted=False) as current:
        recorded = current.ut("align", processes=current.repository(ALIGNED_PAIR))
        unknown = current.repository([])
        unknown.expect(decide_command("abcdef0"), status=1)
        missing = current.ut("align", "--decide", "abcdef0", processes=unknown)
        not_reviewed_git = current.repository([])
        not_reviewed_git.expect(decide_command(FIRST), output=f"{FIRST}\n")
        not_reviewed = current.ut("align", "--decide", FIRST[:7], processes=not_reviewed_git)
        alone = current.ut("align", "--decide", FIRST[:7], "--dry-run")

    assert recorded.status == 1
    assert missing.status == 2
    assert missing.errors == (
        "The commit abcdef0 given with --decide is not in this repository: check the hash or "
        "the name.\n"
    )
    assert not_reviewed.status == 1
    assert not_reviewed.errors == (
        "The commit 1111111 has no review of the twins in the Studio yet (ALIGN_NOT_REVIEWED): "
        "launch `ut align` to record it and have it reviewed, then decide.\n"
    )
    assert alone.status == 2
    assert alone.errors == (
        "--decide goes alone: it cannot be used with --since, --latest or --dry-run.\n"
    )
    assert alone.output == ""


WIDE = {"COLUMNS": "400"}


def said(key: str, language: str = "en", **values: object) -> str:
    return messages.text(key, language, **values)


def decision_bodies(studio: FakeStudio) -> list[dict[str, object]]:
    return [
        json.loads(request.body)
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/decision")
    ]


def listed_lines(lines: list[str], start: str, end: str) -> list[str]:
    first, last = lines.index(start), lines.index(end)
    return [line for line in lines[first + 1 : last] if not line.startswith("     ")]


def test_the_tasks_branch_offers_the_findings_of_the_twins(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "2", "", "1 3"],
            variables=WIDE,
        )
        tasks = current.project.tasks()
        critiques = current.project.change_reviews()[0]["critiques"]
        bodies = decision_bodies(current.studio)

    lines = run.output.splitlines()
    question = said("align.findings_question") + " "
    assert run.status == 0, run.errors
    assert [line[:5] for line in listed_lines(lines, said("align.findings_intro"), question)] == [
        "  1. ",
        "  2. ",
        "  3. ",
    ]
    after = lines.index(question)
    assert lines[after + 1 : after + 4] == [
        said("align.decided_tasks", count=2),
        f"- TSK-001: {tasks[0]['text']}",
        f"- TSK-002: {tasks[1]['text']}",
    ]
    assert bodies == [
        {
            "kind": "CODE_TASKS",
            "note": None,
            "tasks": [],
            "findings": [
                {"twin_id": critiques[0]["twin_id"], "finding": 0},
                {"twin_id": critiques[1]["twin_id"], "finding": 0},
            ],
        }
    ]
    assert [
        (task["origin"]["kind"], task["origin"]["commit"], task["origin"]["finding"])
        for task in tasks
    ] == [
        ("CODE_CHANGE", FIRST, critiques[0]["findings"][0]["text"]),
        ("CODE_CHANGE", FIRST, critiques[1]["findings"][0]["text"]),
    ]
    assert lines[-1] == (
        "Development: commits recorded: 1; none aligned yet (waiting: 1); open tasks for the "
        "code: 2."
    )


def test_the_tasks_of_the_verdict_and_the_findings_are_sent_together(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "The tip choice drifts")]),
            answers=["y", "", "", "Cover the tip choice with a test", "2"],
        )
        tasks = current.project.tasks()
        critiques = current.project.change_reviews()[0]["critiques"]
        bodies = decision_bodies(current.studio)

    proposed = "Bring the code back in line with screen SCR-001 of the approved design."
    assert run.status == 0, run.errors
    assert said("align.decided_tasks", count=3) in run.output.splitlines()
    assert bodies == [
        {
            "kind": "CODE_TASKS",
            "note": None,
            "tasks": [proposed, "Cover the tip choice with a test"],
            "findings": [{"twin_id": critiques[0]["twin_id"], "finding": 1}],
        }
    ]
    assert [task["text"] for task in tasks] == [
        proposed,
        "Cover the tip choice with a test",
        critiques[0]["findings"][1]["action"],
    ]
    assert [task["origin"]["twin_name"] for task in tasks] == [
        None,
        None,
        critiques[0]["twin_name"],
    ]


def test_the_tasks_of_the_verdict_come_first_and_existing_tasks_are_not_offered_again(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        first = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "2", "", "1"],
        )
        current.project.change_runs[0]["alignment"]["code_tasks"] = [
            "Cover the amount with a test."
        ]
        processes = current.repository([])
        processes.expect(decide_command(FIRST), output=f"{FIRST}\n")
        again = current.ut(
            "align",
            "--decide",
            FIRST[:7],
            processes=processes,
            answers=["2", "", ""],
            variables=WIDE,
        )
        tasks = current.project.tasks()
        bodies = decision_bodies(current.studio)

    lines = again.output.splitlines()
    listed = listed_lines(
        lines,
        said("align.findings_intro_verdict"),
        said("align.findings_question_verdict") + " ",
    )
    assert (first.status, again.status) == (0, 0)
    assert listed[0] == "  1. " + said("tasks.choice_verdict", text="Cover the amount with a test.")
    assert listed[1].startswith("  -  ")
    assert listed[1].endswith("(already the open task TSK-001)")
    assert [line[:5] for line in listed[2:]] == ["  2. ", "  3. "]
    assert bodies[-1] == {
        "kind": "CODE_TASKS",
        "note": None,
        "tasks": ["Cover the amount with a test."],
    }
    assert "- TSK-002: Cover the amount with a test." in lines
    assert [task["status"] for task in tasks] == ["OPEN", "OPEN"]


def test_a_finding_that_left_the_review_records_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next(
            "POST",
            "/projects/{project_id}/code-changes/{commit}/decision",
            status=422,
            body={"detail": {"code": "TASK_SOURCE_INVALID", "index": 0}},
        )
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "2", "", "1"],
        )
        tasks = current.project.tasks()
        decisions = current.decisions()

    assert run.status == 1
    assert run.errors == said("align.errors.TASK_SOURCE_INVALID") + "\n"
    assert tasks == []
    assert decisions == {FIRST: None}


def stale_changes(current: Session, count: int = 2) -> list[dict[str, object]]:
    messages_of = ("Add the split of the bill", "Round the tip")
    changes = [current.project.seed_change(message) for message in messages_of[:count]]
    current.project.seed_version("design")
    return changes


def review_bodies(studio: FakeStudio) -> list[tuple[str, dict[str, object]]]:
    return [
        (request.path.split("/")[-2], json.loads(request.body))
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/reviews")
    ]


@pytest.mark.parametrize("language", ["en", "it"])
def test_recheck_without_stale_reviews_says_so_and_needs_no_git(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as current:
        current.project.seed_change()
        run = current.ut("align", "--recheck", language=language)
        reviews = review_bodies(current.studio)

    assert run.status == 0, run.errors
    assert said("align.recheck_none", language) in run.output.splitlines()
    assert reviews == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_recheck_dry_run_lists_the_versions_and_spends_nothing(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as current:
        changes = stale_changes(current)
        run = current.ut("align", "--recheck", "--dry-run", language=language, variables=WIDE)
        reviews = review_bodies(current.studio)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert (
        said(
            "align.recheck_list",
            language,
            count=2,
            requirements=1,
            design=3,
            alternative="DES-002",
        )
        in lines
    )
    positions = [
        lines.index(
            "- "
            + said(
                "align.recheck_line",
                language,
                commit=str(change["commit"])[:7],
                date="2026-09-29 08:00",
                line=change["message"],
                requirements=1,
                design=2,
                alternative="DES-002",
            )
        )
        for change in changes
    ]
    assert positions == sorted(positions)
    assert said("align.recheck_dry_run", language) in lines
    amount = "0.90-1.60" if language == "en" else "0,90-1,60"
    assert said("align.dry_run_estimate", language, amount=amount, minutes="6 min") in lines
    assert lines[-1] == said("align.recheck_hint", language, count=2)
    assert reviews == []


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            "en",
            "These reviews run on the Claude subscription: they spend no credit. Estimated time: "
            "about 3 min. Without --dry-run they really start.",
        ),
        (
            "it",
            "Questi esami usano l'abbonamento di Claude: non spendono credito. Tempo stimato: "
            "circa 3 min. Senza --dry-run partono davvero.",
        ),
    ],
)
def test_on_the_subscription_the_dry_run_gives_the_time_without_an_amount(
    tmp_path: Path, language: str, line: str
) -> None:
    with session(tmp_path, language=language, billing="SUBSCRIPTION") as current:
        processes = current.repository([commit(FIRST, "Add the amount field")])
        run = current.ut("align", "--dry-run", processes=processes, language=language)
        reviews = review_bodies(current.studio)

    assert run.status == 0, run.errors
    assert line in run.output.splitlines()
    assert "USD" not in run.output
    assert reviews == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_on_the_subscription_the_recheck_dry_run_gives_the_time_without_an_amount(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language, billing="SUBSCRIPTION") as current:
        stale_changes(current)
        run = current.ut("align", "--recheck", "--dry-run", language=language, variables=WIDE)

    assert run.status == 0, run.errors
    assert said("align.dry_run_subscription", language, minutes="6 min") in run.output.splitlines()
    assert "USD" not in run.output


def test_on_the_subscription_the_reviews_start_without_a_question(tmp_path: Path) -> None:
    with session(tmp_path, billing="SUBSCRIPTION") as current:
        run = current.ut("align", processes=current.repository(ALIGNED_PAIR), answers=[""])
        runs = current.project.change_reviews()

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert (
        "This generation runs on the Claude subscription: it spends no credit. Estimated time: "
        "about 6 min." in lines
    )
    assert "Go ahead with this spending?" not in run.output
    assert len(runs) == 2


@pytest.mark.parametrize("billing", ["MIXED", "API"])
def test_with_paid_routes_the_dry_run_names_its_amount(tmp_path: Path, billing: str) -> None:
    with session(tmp_path, billing=billing) as current:
        processes = current.repository([commit(FIRST, "Add the amount field")])
        run = current.ut("align", "--dry-run", processes=processes)

    assert run.status == 0, run.errors
    assert (
        "Estimate of these reviews: 0.45-0.80 USD, about 3 min. Without --dry-run they really "
        "start." in run.output.splitlines()
    )


def test_recheck_reviews_again_the_oldest_first_and_opens_each_menu(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        older, newer = stale_changes(current)
        run = current.ut("align", "--recheck", answers=["y", "", "later"])
        reviews = review_bodies(current.studio)
        decisions = current.decisions()
        stale = [change["review"]["stale"] for change in current.project.changes()]

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert said("align.recheck_reviewing", count=2, twins=2) in lines
    assert "Go ahead with this spending? [Y/n] " in lines
    assert reviews == [
        (older["commit"], {"locale": "en-US", "again": True}),
        (newer["commit"], {"locale": "en-US", "again": True}),
    ]
    assert f"Review of commit {str(older['commit'])[:7]}: Add the split of the bill" in lines
    assert f"Review of commit {str(newer['commit'])[:7]}: Round the tip" in lines
    assert decisions == {older["commit"]: "ALIGNED", newer["commit"]: None}
    assert stale == [False, False]
    assert lines[-1] == (
        "Development: commits recorded: 2; after the aligned point: 1; aligned commit: "
        f"{str(older['commit'])[:7]}; open tasks for the code: 0."
    )


def test_recheck_latest_reviews_only_the_newest_stale_commit(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        _, newer = stale_changes(current)
        run = current.ut("align", "--recheck", "--latest", answers=["y", "later"])
        reviews = review_bodies(current.studio)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert [commit for commit, _ in reviews] == [newer["commit"]]
    assert said("align.recheck_reviewing", count=1, twins=2) in lines
    assert lines[-1] == said("align.recheck_hint", count=1)


def test_recheck_refused_at_the_spending_question_reviews_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        stale_changes(current)
        run = current.ut("align", "--recheck", answers=["n"])
        reviews = review_bodies(current.studio)

    assert run.status == 5
    assert "No generation started: the spending was not confirmed." in run.errors
    assert reviews == []


def test_recheck_without_a_model_stops_before_the_spending_question(tmp_path: Path) -> None:
    with session(tmp_path, hosted=False) as current:
        stale_changes(current, 1)
        run = current.ut("align", "--recheck")
        dry = current.ut("align", "--recheck", "--dry-run")
        reviews = review_bodies(current.studio)

    assert run.status == 1
    assert run.errors == said("align.errors.CHANGE_REVIEW_MODEL_NOT_CONFIGURED") + "\n"
    assert "Go ahead" not in run.output
    assert dry.status == 0, dry.errors
    assert reviews == []


@pytest.mark.parametrize("extra", [["--since", "HEAD"], ["--decide", "HEAD"], ["--since", "x"]])
def test_recheck_goes_alone(tmp_path: Path, extra: list[str]) -> None:
    run = run_ut(["align", "--recheck", *extra], tmp_path, transport=UrlTransport())

    assert run.status == 2
    assert run.errors == said("align.errors.ALIGN_RECHECK_ALONE") + "\n"
    assert run.output == ""


def test_recheck_names_the_decision_taken_before(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        first = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", "2", "Add a label to the amount", "", ""],
        )
        current.project.seed_version("design")
        run = current.ut("align", "--recheck", answers=["y", "later"])

    assert (first.status, run.status) == (0, 0)
    assert (
        said("align.earlier_decision", decision=said("align.kind_code_tasks"))
        in run.output.splitlines()
    )


def test_a_design_realignment_names_the_reviews_that_are_now_stale(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Rework the card of the design")]),
            answers=["y", "", "", "y", "y"],
        )

    lines = run.output.splitlines()
    hint = said("align.recheck_hint", count=1)
    assert run.status == 0, run.errors
    assert lines.count(hint) == 1
    assert lines.index(hint) > lines.index("Do you approve version 3 of the design now? [Y/n] ")
    assert lines[-1].startswith("Development: commits recorded: 1;")


def test_a_requirements_realignment_names_the_reviews_that_are_now_stale(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "New requirement: split among friends")]),
            answers=["y", "", "", "y", "y"],
        )

    lines = run.output.splitlines()
    hint = said("align.recheck_hint", count=1)
    assert run.status == 0, run.errors
    assert lines.index(hint) > lines.index(said("align.design_realigned", version=3))
    assert lines.count(hint) == 1


def test_a_normal_align_says_the_stale_reviews_at_the_end(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.project.seed_change()
        current.project.seed_version("design")
        run = current.ut(
            "align",
            "--dry-run",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
        )

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[-2].startswith("Development: commits recorded: 2;")
    assert lines[-1] == said("align.recheck_hint", count=1)


REQUIREMENTS_COMMIT = "New requirement: split among friends"
CHANGE_APPLIED = ["y", "", "", "y", "y"]


def gestures(studio: FakeStudio) -> list[str]:
    return [
        request.path
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/sections/alignment")
    ]


def package_of(version: dict[str, object] | None) -> dict[str, object]:
    assert version is not None
    package = dict(version["package"])
    package.pop("grounding")
    return package


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_requirements_branch_ends_with_the_gesture_the_approval_and_the_folder(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as current:
        before = current.project.current("design")
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, REQUIREMENTS_COMMIT)]),
            answers=CHANGE_APPLIED if language == "en" else ["s", "", "", "s", "s"],
            language=language,
        )
        after = current.project.current("design")
        approved = current.project.approved("design")
        sections = current.project.sections()
        sent = gestures(current.studio)
        decisions = current.decisions()
        published = current.project.knowledge_versions()

    lines = run.output.splitlines()
    design = next(item for item in sections["sections"] if item["key"] == "DESIGN")
    assert run.status == 0, run.errors
    realigned = lines.index(said("align.design_realigned", language, version=3))
    assert lines[realigned + 1 : realigned + 3] == [
        said("sections.not_covered", language, codes=", ".join(design["codes"])),
        said("sections.evaluation_missing", language),
    ]
    assert design["codes"]
    assert said("sections.evaluation_after", language) not in lines
    assert said("align.folder_updated", language, version=1) in lines
    assert sent == [f"/api/v1/projects/{current.project.id}/sections/alignment"]
    assert after is not None and after["version_number"] == 3
    assert approved
    assert package_of(after) == package_of(before)
    assert decisions == {FIRST: "REQUIREMENTS_CHANGE"}
    assert len(published) == 1
    assert [item["key"] for item in sections["sections"] if item["state"] == "TO_UPDATE"] == []
    assert design["state"] == "UPDATE_AVAILABLE"


def test_a_discarded_change_of_the_requirements_records_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, REQUIREMENTS_COMMIT)]),
            answers=["y", "", "", "n"],
        )
        decisions = current.decisions()
        requirements = current.project.current("requirements")
        sent = gestures(current.studio)

    assert run.status == 0, run.errors
    assert said("align.decided_later") in run.output.splitlines()
    assert "Decision recorded" not in run.output
    assert decisions == {FIRST: None}
    assert requirements is not None and requirements["version_number"] == 1
    assert sent == []


def test_requirements_left_waiting_send_no_gesture(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, REQUIREMENTS_COMMIT)]),
            answers=["y", "", "", "y", "n"],
        )
        decisions = current.decisions()
        sent = gestures(current.studio)

    assert run.status == 0, run.errors
    assert said("align.requirements_left", version=2) in run.output.splitlines()
    assert decisions == {FIRST: "REQUIREMENTS_CHANGE"}
    assert sent == []


def test_a_design_that_cannot_be_re_anchored_is_told_with_its_codes(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next(
            "POST",
            "/projects/{project_id}/sections/alignment",
            status=200,
            body={
                "status": "NOTHING_TO_ALIGN",
                "results": [
                    {
                        "key": "DESIGN",
                        "outcome": "BLOCKED",
                        "issue": "REQUIREMENT_NO_LONGER_AVAILABLE",
                        "version_number": None,
                        "codes": ["REQ-002"],
                    }
                ],
                "sections": None,
            },
        )
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, REQUIREMENTS_COMMIT)]),
            answers=CHANGE_APPLIED,
        )
        published = current.project.knowledge_versions()

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert (
        "Design & Evaluation cannot be updated by itself: the design cites REQ-002, which the "
        "Definition no longer contains: regenerate the alternatives in the Design & Evaluation "
        "step of the web Studio. Then go on with `ut design`." in lines
    )
    assert not any(line.startswith("Knowledge folder updated") for line in lines)
    assert published == []


@pytest.mark.parametrize(
    ("status", "body", "key", "values"),
    [
        (404, {"detail": "Not Found"}, "align.design_not_realigned", {}),
        (
            503,
            {"detail": {"code": "SECTIONS_SERVICE_UNAVAILABLE"}},
            "align.design_realign_failed",
            {"code": "SECTIONS_SERVICE_UNAVAILABLE"},
        ),
    ],
)
def test_a_studio_that_cannot_re_anchor_the_design_says_so(
    tmp_path: Path, status: int, body: dict[str, object], key: str, values: dict[str, str]
) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next(
            "POST", "/projects/{project_id}/sections/alignment", status=status, body=body
        )
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, REQUIREMENTS_COMMIT)]),
            answers=CHANGE_APPLIED,
        )
        decisions = current.decisions()

    assert run.status == 0, run.errors
    assert said(key, **values) in run.output.splitlines()
    assert decisions == {FIRST: "REQUIREMENTS_CHANGE"}


def test_the_reviews_of_align_use_the_language_of_the_knowledge_folder(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        folder = current.root / "orchestwin"
        folder.mkdir()
        manifest = {
            "package": {"version_number": 1, "content_hash": "c"},
            "project": {"id": current.project.id, "name": NAME, "language": "it"},
            "stages": {},
            "files": {},
        }
        (folder / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")
        run = current.ut(
            "align",
            processes=current.repository([commit(FIRST, "Add the amount field")]),
            answers=["y", ""],
        )
        locales = [
            json.loads(request.body)["locale"]
            for request in current.studio.requests
            if request.path.endswith("/reviews") and request.method == "POST"
        ]

    assert run.status == 0, run.errors
    assert locales == ["it-IT"]
