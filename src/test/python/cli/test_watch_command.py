from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli.flows.changes import git_command, log_arguments
from orchestwin.cli.http import Reply, UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.processes import FakeCommit, FakeFile, ScriptedProcesses, script_commits
from .support.terminal import (
    PROJECT_ID,
    START,
    TEST_PASSWORD,
    Run,
    link_folder,
    run_ut,
    store_session,
)
from .support.transports import API, ScriptedTransport, Sent

EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
FIRST = "1" * 40
SECOND = "2" * 40
THIRD = "3" * 40
BASE = f"{API}/projects/{PROJECT_ID}"
HEAD = git_command("rev-parse", "--verify", "--quiet", "HEAD")
RESOLVE_FIRST = git_command("rev-parse", "--verify", "--quiet", f"{FIRST}^{{commit}}")


def commit(hash_value: str, message: str, parent: str) -> FakeCommit:
    return FakeCommit(
        hash_value, message, files=(FakeFile("src/app.js"),), parent=parent, diff="+a\n"
    )


def repository(
    root: Path,
    heads: Sequence[str],
    passes: Sequence[tuple[str, Sequence[FakeCommit]]],
    *,
    interrupt: bool = True,
) -> ScriptedProcesses:
    processes = ScriptedProcesses()
    processes.expect(
        git_command("rev-parse", "--show-toplevel"), output=f"{root.as_posix()}\n", repeat=True
    )
    processes.expect(git_command("rev-parse", "--abbrev-ref", "HEAD"), output="main\n", repeat=True)
    for value in heads:
        processes.expect(HEAD, output=f"{value}\n")
    if interrupt:
        processes.expect(HEAD, interrupt=True)
    for since, commits in passes:
        script_commits(processes, commits, since=since)
    return processes


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    @property
    def root(self) -> Path:
        return self.tmp_path / "project"

    def ut(
        self,
        *arguments: str,
        processes: ScriptedProcesses | None = None,
        answers: Sequence[str] = (),
        language: str = "en",
    ) -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
            processes=processes,
        )


@contextmanager
def session(
    tmp_path: Path, *, hosted: bool = True, language: str = "en", billing: str | None = None
) -> Iterator[Session]:
    with FakeStudio(language=language, hosted=hosted, twins=2, billing=billing) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through="design")
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(tmp_path / "project", project_id=project.id, name=NAME, studio=studio.address)
        yield Session(studio=studio, project=project, tmp_path=tmp_path)
        assert studio.errors == []


def test_watch_records_each_new_commit_until_ctrl_c(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        second = commit(SECOND, "Show the tip", FIRST)
        third = commit(THIRD, "Round the tip", SECOND)
        processes = repository(
            current.root, [FIRST, SECOND, THIRD], [(FIRST, [second]), (SECOND, [third])]
        )

        run = current.ut("watch", processes=processes)
        changes = current.project.changes()
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    assert run.output.splitlines() == [
        'Watching the commits of "Calcolo mancia"',
        "========================================",
        f"Folder: {current.root}",
        "Branch: main",
        "No commit is aligned yet and no commit of this repository is recorded in the Studio: "
        "I record the commits made from now on.",
        "The twins do not review the commits: add --twins to have them reviewed.",
        "Checking every 15 seconds. Stop me with Ctrl+C.",
        "",
        "New commits: 1.",
        "- 2222222  2026-09-29 10:15  Show the tip  (files: 1)",
        "",
        "New commits: 1.",
        "- 3333333  2026-09-29 10:15  Round the tip  (files: 1)",
        "",
        "Watching ended. The recorded commits wait for your decision with `ut verify`.",
    ]
    assert run.slept == 30.0
    assert [change["commit"] for change in changes] == [THIRD, SECOND]
    assert runs == []
    processes.assert_done()


def test_the_twins_review_until_the_cap_and_the_commits_are_still_recorded(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        second = commit(SECOND, "Show the tip", FIRST)
        third = commit(THIRD, "Round the tip", SECOND)
        processes = repository(
            current.root, [FIRST, SECOND, THIRD], [(FIRST, [second]), (SECOND, [third])]
        )

        run = current.ut(
            "watch", "--twins", "--max-usd", "1", "--interval", "2", processes=processes
        )
        changes = current.project.changes()
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "The twins review each new commit, up to 1.00 USD of estimated spending in this "
        "session (--max-usd)." in lines
    )
    assert "Credit left in the Studio: 60.00 USD." in lines
    assert "Checking every 2 seconds. Stop me with Ctrl+C." in lines
    assert "Review of commit 2222222: Show the tip" in lines
    assert "You take the decision on this commit with `ut verify`." in lines
    assert (
        "The next review would go over 1.00 USD of estimated spending: the twins stop "
        "reviewing, the commits are still recorded. Have the others reviewed with `ut verify`."
        in lines
    )
    assert "Review of commit 3333333" not in run.output
    assert [item["commit"] for item in runs] == [SECOND]
    assert [change["commit"] for change in changes] == [THIRD, SECOND]
    assert all(change["decision"] is None for change in changes)
    assert run.slept >= 4.0


def test_on_the_subscription_the_cap_still_stops_the_reviews(tmp_path: Path) -> None:
    with session(tmp_path, billing="SUBSCRIPTION") as current:
        second = commit(SECOND, "Show the tip", FIRST)
        third = commit(THIRD, "Round the tip", SECOND)
        processes = repository(
            current.root, [FIRST, SECOND, THIRD], [(FIRST, [second]), (SECOND, [third])]
        )

        run = current.ut(
            "watch", "--twins", "--max-usd", "1", "--interval", "2", processes=processes
        )
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "The twins review each new commit on the Claude subscription: they spend no credit. To "
        "spare the subscription, in this session they stop before going over 1.00 USD of "
        "reviews at paid prices (--max-usd)." in lines
    )
    assert not any(line.startswith("Credit left") for line in lines)
    assert (
        "The next review would go over 1.00 USD of reviews at paid prices (--max-usd): the twins "
        "stop reviewing, the commits are still recorded. Have the others reviewed with "
        "`ut verify`." in lines
    )
    assert "estimated spending" not in run.output
    assert [item["commit"] for item in runs] == [SECOND]


@pytest.mark.parametrize("billing", ["MIXED", "API"])
def test_with_paid_routes_the_cap_is_a_spending_and_the_credit_is_shown(
    tmp_path: Path, billing: str
) -> None:
    with session(tmp_path, billing=billing) as current:
        quiet = repository(current.root, [FIRST, FIRST], [], interrupt=False)
        run = current.ut("watch", "--once", "--twins", processes=quiet)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-3:] == [
        "The twins review each new commit, up to 5.00 USD of estimated spending in this "
        "session (--max-usd).",
        "Credit left in the Studio: 60.00 USD.",
        "No new commit to record.",
    ]


def test_once_makes_one_check(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        quiet = repository(current.root, [FIRST, FIRST], [], interrupt=False)
        run = current.ut("watch", "--once", processes=quiet)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-2:] == [
        "The twins do not review the commits: add --twins to have them reviewed.",
        "No new commit to record.",
    ]
    assert run.slept == 0
    quiet.assert_done()


def test_after_an_aligned_point_the_first_check_takes_the_commits_after_it(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        first = FakeCommit(FIRST, "Add the amount field", files=(FakeFile("src/app.js"),))
        aligned = script_commits(
            repository(current.root, [FIRST], [], interrupt=False), [first], since=None
        )
        aligned.expect(git_command("status", "--porcelain", "-z"), repeat=True)
        verify = current.ut("verify", processes=aligned, answers=["y", ""])
        later = commit(SECOND, "Show the tip", FIRST)
        processes = repository(current.root, [SECOND], [(FIRST, [later])], interrupt=False)

        run = current.ut("watch", "--once", processes=processes)
        changes = current.project.changes()

    assert verify.status == 0, verify.errors
    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert "Aligned point: commit 1111111. I record the commits that come after it." in lines
    assert "New commits: 1." in lines
    assert "Checking every" not in run.output
    assert [change["commit"] for change in changes] == [SECOND, FIRST]


def test_a_commit_of_the_knowledge_folder_is_recorded_but_never_reviewed(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        code = commit(SECOND, "Show the tip", FIRST)
        folder = FakeCommit(
            THIRD,
            "Update the knowledge folder",
            files=(
                FakeFile("orchestwin/state/state.md"),
                FakeFile(".orchestwin/steps/design.json"),
            ),
            parent=SECOND,
            diff="+a\n",
        )
        processes = repository(current.root, [FIRST, THIRD], [(FIRST, [code, folder])])

        run = current.ut("watch", "--twins", processes=processes)
        changes = {str(change["commit"]): change for change in current.project.changes()}
        runs = current.project.change_reviews()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "Commits that change only the knowledge folder, recorded without a review: 1 "
        "(3333333); the newest needs no decision and is marked as dismissed." in lines
    )
    assert "Review of commit 2222222: Show the tip" in lines
    assert "Review of commit 3333333" not in run.output
    assert [item["commit"] for item in runs] == [SECOND]
    assert changes[THIRD]["decision"]["kind"] == "DISMISSED"
    assert changes[THIRD]["decision"]["note"] == "knowledge folder only"
    assert changes[SECOND]["decision"] is None


def test_without_a_model_the_twins_do_not_review_and_the_commits_are_recorded(
    tmp_path: Path,
) -> None:
    with session(tmp_path, hosted=False) as current:
        second = commit(SECOND, "Show the tip", FIRST)
        processes = repository(current.root, [FIRST, SECOND], [(FIRST, [second])])

        run = current.ut("watch", "--twins", processes=processes)
        changes = current.project.changes()

    assert run.status == 0, run.errors
    assert (
        "The twins cannot review the code on this Studio (CHANGE_REVIEW_MODEL_NOT_CONFIGURED): "
        "I only record the commits." in run.output.splitlines()
    )
    assert [change["commit"] for change in changes] == [SECOND]


def test_a_studio_that_fails_is_reported_and_the_commit_is_retried(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        second = commit(SECOND, "Show the tip", FIRST)
        processes = repository(current.root, [FIRST, SECOND, SECOND], [(FIRST, [second])])
        current.studio.fail_next(
            "GET",
            "/projects/{project_id}/code-changes",
            status=503,
            body={"detail": {"code": "DATABASE_UNAVAILABLE"}},
        )

        run = current.ut("watch", processes=processes)
        changes = current.project.changes()

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "The Studio answered with an error (DATABASE_UNAVAILABLE): I try again at the next "
        "check." in lines
    )
    assert lines.count("New commits: 1.") == 1
    assert [change["commit"] for change in changes] == [SECOND]


def test_the_history_of_the_repository_can_change_under_the_watch(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        processes = repository(current.root, [FIRST, SECOND, SECOND], [], interrupt=True)
        processes.expect(git_command(*log_arguments(FIRST)), status=128, errors="fatal")
        processes.expect(
            git_command("rev-parse", "--verify", "--quiet", f"{FIRST}^{{commit}}"), status=1
        )

        run = current.ut("watch", processes=processes)

    assert run.status == 0, run.errors
    assert (
        "The history of the repository changed (commit 1111111 is gone): I go on from the "
        "current commit." in run.output.splitlines()
    )


def test_wrong_options_are_usage_errors(tmp_path: Path) -> None:
    short = run_ut(["watch", "--interval", "1"], tmp_path, transport=ScriptedTransport())
    zero = run_ut(["watch", "--max-usd", "0"], tmp_path, transport=ScriptedTransport())
    endless = run_ut(["watch", "--max-usd", "nan"], tmp_path, transport=ScriptedTransport())
    words = run_ut(["watch", "--max-usd", "five"], tmp_path, transport=ScriptedTransport())

    assert short.status == 2
    assert short.errors == "The interval between two checks must be at least 2 seconds.\n"
    assert zero.status == 2
    assert zero.errors == (
        "The highest spending must be a positive amount in USD, for example 5.00.\n"
    )
    assert endless.status == 2
    assert words.status == 2
    assert "invalid float value" in words.errors


def test_the_introduction_in_italian(tmp_path: Path) -> None:
    with session(tmp_path, language="it") as current:
        processes = repository(current.root, [FIRST, FIRST], [], interrupt=False)
        run = current.ut("watch", "--once", "--twins", processes=processes, language="it")

    assert run.status == 0, run.errors
    assert run.output.splitlines() == [
        "Osservo i commit di «Calcolo mancia»",
        "====================================",
        f"Cartella: {current.root}",
        "Ramo: main",
        "Nessun commit è ancora allineato e nessun commit di questo repository è registrato "
        "nello Studio: registro i commit fatti da adesso in poi.",
        "I twin esaminano ogni nuovo commit, fino a 5,00 USD di spesa stimata in questa "
        "sessione (--max-usd).",
        "Credito rimasto nello Studio: 60,00 USD.",
        "Nessun commit nuovo da registrare.",
    ]


def test_the_introduction_on_the_subscription_in_italian(tmp_path: Path) -> None:
    with session(tmp_path, language="it", billing="SUBSCRIPTION") as current:
        processes = repository(current.root, [FIRST, FIRST], [], interrupt=False)
        run = current.ut("watch", "--once", "--twins", processes=processes, language="it")

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-2:] == [
        "I twin esaminano ogni nuovo commit con l'abbonamento di Claude: non spendono credito. "
        "Per non consumare troppo l'abbonamento, in questa sessione si fermano prima di superare "
        "5,00 USD di esami ai prezzi a pagamento (--max-usd).",
        "Nessun commit nuovo da registrare.",
    ]


def test_without_an_aligned_point_the_watch_starts_after_the_last_recorded_commit(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        first = FakeCommit(FIRST, "Add the amount field", files=(FakeFile("src/app.js"),))
        before = script_commits(
            repository(current.root, [FIRST], [], interrupt=False), [first], since=None
        )
        before.expect(git_command("status", "--porcelain", "-z"), repeat=True)
        verify = current.ut("verify", processes=before, answers=["y", "later"])
        second = commit(SECOND, "Show the tip", FIRST)
        processes = repository(current.root, [SECOND], [(FIRST, [second])], interrupt=False)
        processes.expect(RESOLVE_FIRST, output=f"{FIRST}\n")

        run = current.ut("watch", "--once", processes=processes)
        changes = current.project.changes()

    assert verify.status == 0, verify.errors
    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "No commit is aligned yet: I record the commits that come after 1111111, the last one "
        "recorded in the Studio." in lines
    )
    assert "New commits: 1." in lines
    assert [change["commit"] for change in changes] == [SECOND, FIRST]


def test_a_recorded_commit_that_git_does_not_know_falls_back_to_head(tmp_path: Path) -> None:
    root = linked(tmp_path)
    document = {**ALIGNMENT, "latest_change": {"commit": THIRD}}
    transport = ScriptedTransport().expect("GET", f"{BASE}/alignment", body=document)
    processes = repository(root, [FIRST, FIRST], [], interrupt=False)
    processes.expect(
        git_command("rev-parse", "--verify", "--quiet", f"{THIRD}^{{commit}}"), status=1
    )

    run = run_ut(["watch", "--once"], tmp_path, transport=transport, processes=processes)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "No commit is aligned yet and no commit of this repository is recorded in the Studio: "
        "I record the commits made from now on." in lines
    )
    assert lines[-1] == "No new commit to record."
    transport.assert_done()


ALIGNMENT = {
    "project_id": PROJECT_ID,
    "reference": {
        "requirements": {"version_id": "r", "version_number": 1, "content_hash": "hr"},
        "design": {
            "version_id": "d",
            "version_number": 2,
            "content_hash": "hd",
            "alternative_code": "DES-002",
        },
    },
    "aligned": None,
    "pending_changes": 0,
    "latest_change": None,
    "tasks": [],
    "review_available": True,
}
RECORDED = {"status": "RECORDED", "change": {"commit": SECOND}}


def linked(tmp_path: Path) -> Path:
    store_session(tmp_path, expires_at=START + timedelta(hours=2))
    return link_folder(tmp_path / "project").root


def test_an_unreachable_studio_is_reported_and_the_loop_goes_on(tmp_path: Path) -> None:
    root = linked(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{BASE}/alignment", body=ALIGNMENT)
    for _ in range(3):
        transport.expect("GET", f"{BASE}/code-changes", unreachable=True)
    transport.expect("GET", f"{BASE}/code-changes", body={"items": []})
    transport.expect("POST", f"{BASE}/code-changes", status=201, body=RECORDED)
    second = commit(SECOND, "Show the tip", FIRST)
    processes = repository(root, [FIRST, SECOND, SECOND], [(FIRST, [second])])

    run = run_ut(["watch"], tmp_path, transport=transport, processes=processes)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "The Studio http://127.0.0.1:8000 does not answer: I try again at the next check." in lines
    )
    assert lines.count("New commits: 1.") == 1
    transport.assert_done()


def test_a_sign_in_that_expires_ends_the_watch_with_3(tmp_path: Path) -> None:
    root = linked(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{BASE}/alignment", body=ALIGNMENT)
    transport.expect("GET", f"{BASE}/code-changes", status=401, body={"detail": "expired"})
    transport.expect(
        "POST", f"{API}/auth/refresh", status=401, body={"detail": "invalid_refresh_token"}
    )
    second = commit(SECOND, "Show the tip", FIRST)
    processes = repository(root, [FIRST, SECOND], [(FIRST, [second])], interrupt=False)

    run = run_ut(["watch"], tmp_path, transport=transport, processes=processes)

    assert run.status == 3
    assert "has expired" in run.errors
    transport.assert_done()


def test_ctrl_c_during_a_review_leaves_it_running_in_the_studio(tmp_path: Path) -> None:
    root = linked(tmp_path)
    job = {"job_id": "job-1", "status": "RUNNING", "stage": "GENERATING", "operation": "X"}

    def interrupted(sent: Sent) -> Reply:
        raise KeyboardInterrupt

    transport = ScriptedTransport().expect("GET", f"{BASE}/alignment", body=ALIGNMENT)
    transport.expect(
        "GET",
        f"{API}/model-runtime/budget",
        status=503,
        body={"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}},
    )
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/snapshots/current",
        body={"snapshot": {"twin_versions": [{"twin_id": "a"}, {"twin_id": "b"}]}},
    )
    transport.expect("GET", f"{BASE}/code-changes", body={"items": []})
    transport.expect("POST", f"{BASE}/code-changes", status=201, body=RECORDED)
    transport.expect(
        "POST",
        f"{BASE}/code-changes/{SECOND}/reviews",
        status=202,
        body=job,
        headers={"Preference-Applied": "respond-async"},
    )
    transport.expect("GET", f"{BASE}/generation-jobs/job-1", respond=interrupted)
    second = commit(SECOND, "Show the tip", FIRST)
    processes = repository(root, [FIRST, SECOND], [(FIRST, [second])], interrupt=False)

    run = run_ut(["watch", "--twins"], tmp_path, transport=transport, processes=processes)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        "Review of commit 2222222: the review goes on in the Studio; `ut verify` finds it." in lines
    )
    assert lines[-1] == (
        "Watching ended. The recorded commits wait for your decision with `ut verify`."
    )
    assert transport.requests("POST", f"{BASE}/code-changes/{SECOND}/reviews")[0].json() == {
        "locale": "en-US",
        "again": False,
    }
    transport.assert_done()
