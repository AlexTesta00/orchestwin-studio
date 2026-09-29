from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.environment import default_run_process
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows.changes import (
    CUT_LINE,
    MAX_DIFF_LENGTH,
    ChangedFile,
    Commit,
    bounded_diff,
    change_body,
    commits_after,
    diff_of,
    excluded_path,
    git_command,
)

from .support.processes import (
    FakeCommit,
    FakeFile,
    ScriptedProcesses,
    kinds_output,
    log_output,
    script_commits,
)
from .support.terminal import command_context, environment
from .support.transports import NoNetwork

FIRST_DATE = "2026-09-29T09:00:00+02:00"
SECOND_DATE = "2026-09-29T10:00:00+02:00"
THIRD_DATE = "2026-09-29T11:00:00+02:00"
SECRET = "test-token-not-real"
HASH_A = "a" * 40
HASH_B = "b" * 40
HASH_C = "c" * 40


def context_with(tmp_path: Path, runner: object) -> CommandContext:
    return command_context(environment(tmp_path, transport=NoNetwork(), processes=runner))


def run_git(root: Path, *arguments: str, date: str = FIRST_DATE) -> str:
    extra = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *arguments,
        ],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **extra},
        check=True,
    )
    return result.stdout


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    home = tmp_path / "git-home"
    home.mkdir()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Anna Rossi")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "anna@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Anna Rossi")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "anna@example.com")
    return tmp_path


@pytest.fixture
def repository(isolated_git: Path) -> Path:
    root = isolated_git / "repo"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    source = root / "src"
    source.mkdir()
    (source / "app.js").write_bytes(b"one\ntwo\nthree\nfour\nfive\n")
    (root / "logo.png").write_bytes(bytes(range(256)) * 4)
    (root / "README.md").write_bytes(b"# Tip\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "First screen\n\nWith a blank line.", date=FIRST_DATE)
    (source / "app.js").rename(source / "main.js")
    (source / "main.js").write_bytes(b"one\ntwo\nthree\nfour\n5\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "Rename the entry point", date=SECOND_DATE)
    (root / ".env").write_bytes(f"TOKEN={SECRET}\n".encode())
    (root / "big.txt").write_bytes(b"x" * 250_000 + b"\n")
    (root / "README.md").write_bytes(b"# Tip\n\nSplit the bill.\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "Secrets and a big file", date=THIRD_DATE)
    return root


def hashes(root: Path) -> list[str]:
    return run_git(root, "log", "--reverse", "--format=%H").split()


def test_a_real_repository_gives_the_commits_oldest_first(tmp_path: Path, repository: Path) -> None:
    context = context_with(tmp_path, default_run_process)
    first, second, third = hashes(repository)

    commits = commits_after(context, repository, None)

    assert [commit.hash for commit in commits] == [first, second, third]
    assert commits[0].parent is None
    assert commits[1].parent == first
    assert commits[0].message == "First screen\n\nWith a blank line."
    assert commits[2].committed_at == THIRD_DATE
    assert commits[0].author == "Anna Rossi"
    assert commits[0].files == (
        ChangedFile("README.md", "ADDED", 1, 0),
        ChangedFile("logo.png", "ADDED", 0, 0),
        ChangedFile("src/app.js", "ADDED", 5, 0),
    )
    assert commits[1].files == (ChangedFile("src/main.js", "RENAMED", 1, 1),)
    assert {item.path: item.kind for item in commits[2].files} == {
        ".env": "ADDED",
        "README.md": "MODIFIED",
        "big.txt": "ADDED",
    }
    assert [commit.hash for commit in commits_after(context, repository, first)] == [
        second,
        third,
    ]
    assert commits_after(context, repository, third) == ()
    assert [item.hash for item in commits_after(context, repository, None, limit=1)] == [third]


def test_a_real_diff_leaves_out_binaries_secrets_and_big_files(
    tmp_path: Path, repository: Path
) -> None:
    context = context_with(tmp_path, default_run_process)
    first, second, third = commits_after(context, repository, None)

    initial = diff_of(context, repository, first)
    renamed = diff_of(context, repository, second)
    guarded = diff_of(context, repository, third)

    assert "+one" in initial
    assert initial.endswith("[excluded: logo.png]\n")
    assert "Binary files" not in initial
    assert "rename from src/app.js" in renamed
    assert "rename to src/main.js" in renamed
    assert "+5" in renamed
    assert "+Split the bill." in guarded
    assert SECRET not in guarded
    assert "xxxxxxxxxx" not in guarded
    assert guarded.endswith("[excluded: .env]\n[excluded: big.txt]\n")
    body = change_body(third, guarded)
    assert list(body) == ["commit", "parent", "committed_at", "author", "message", "files", "diff"]
    assert body["commit"] == third.hash
    assert body["parent"] == second.hash
    assert body["files"] == [
        {"path": ".env", "kind": "ADDED", "added": 1, "removed": 0},
        {"path": "README.md", "kind": "MODIFIED", "added": 2, "removed": 0},
        {"path": "big.txt", "kind": "ADDED", "added": 1, "removed": 0},
    ]
    assert body["diff"] == guarded


def test_a_real_diff_over_the_limit_is_cut_with_its_last_line(
    tmp_path: Path, repository: Path
) -> None:
    context = context_with(tmp_path, default_run_process)
    for number in range(4):
        text = "".join(f"line {number}-{index} of a long file\n" for index in range(700))
        (repository / f"long-{number}.txt").write_bytes(text.encode())
    (repository / "server.pem").write_bytes(b"not a real key\n")
    run_git(repository, "add", "-A")
    run_git(repository, "commit", "-q", "-m", "Four long files", date=THIRD_DATE)
    newest = commits_after(context, repository, None)[-1]

    diff = diff_of(context, repository, newest)

    assert len(diff) <= MAX_DIFF_LENGTH
    assert diff.endswith(f"{CUT_LINE}\n[excluded: server.pem]\n")
    assert "+line 0-0 of a long file" in diff


def test_the_repository_head_branch_and_revisions_of_a_real_repository(
    tmp_path: Path, repository: Path
) -> None:
    context = context_with(tmp_path, default_run_process)
    first, second, third = hashes(repository)
    outside = tmp_path / "outside"
    outside.mkdir()

    assert git.repository_root(context, repository / "src").resolve() == repository.resolve()
    assert git.repository_root(context, outside) is None
    assert git.head(context, repository) == third
    assert git.resolve(context, repository, "HEAD~2") == first
    assert git.resolve(context, repository, second[:10]) == second
    assert git.resolve(context, repository, "no-such-branch") is None
    assert git.resolve(context, repository, "--all") is None
    assert git.branch(context, repository) == "main"
    assert git.uncommitted(context, repository) is False
    (repository / ".orchestwin").mkdir()
    (repository / ".orchestwin" / "project.json").write_bytes(b"{}\n")
    assert git.uncommitted(context, repository) is True
    assert git.uncommitted(context, repository, ignored=[".orchestwin/"]) is False
    (repository / "README.md").write_bytes(b"# Changed\n")
    assert git.uncommitted(context, repository, ignored=[".orchestwin/"]) is True


def test_an_empty_repository_has_no_head_and_no_commit(tmp_path: Path, isolated_git: Path) -> None:
    root = isolated_git / "empty"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    context = context_with(tmp_path, default_run_process)

    assert git.head(context, root) is None
    assert commits_after(context, root, None) == ()


def test_an_aligned_commit_that_left_the_history_is_named(tmp_path: Path, repository: Path) -> None:
    context = context_with(tmp_path, default_run_process)

    with pytest.raises(CliError) as caught:
        commits_after(context, repository, "0123456789abcdef0123456789abcdef01234567")

    assert caught.value.code == "GIT_COMMIT_UNKNOWN"
    assert caught.value.values["commit"] == "0123456"


def test_a_missing_git_is_its_own_error(tmp_path: Path) -> None:
    context = context_with(tmp_path, None)

    with pytest.raises(CliError) as caught:
        git.repository_root(context, tmp_path)

    assert (caught.value.code, caught.value.status) == ("GIT_NOT_AVAILABLE", 1)


def test_every_call_goes_through_the_runner_with_the_fixed_options(tmp_path: Path) -> None:
    processes = ScriptedProcesses().expect(
        git_command("rev-parse", "--show-toplevel"), output=f"{tmp_path.as_posix()}\n"
    )
    context = context_with(tmp_path, processes)

    found = git.repository_root(context, tmp_path)

    assert found == Path(tmp_path.as_posix())
    assert processes.calls[0].arguments[:6] == (
        "git",
        "-c",
        "core.quotepath=off",
        "-c",
        "i18n.logOutputEncoding=utf-8",
        "--no-pager",
    )
    assert processes.calls[0].folder == tmp_path
    assert processes.timeouts == [60.0]


def test_a_folder_outside_a_repository_has_no_root(tmp_path: Path) -> None:
    processes = ScriptedProcesses().expect(
        git_command("rev-parse", "--show-toplevel"),
        status=128,
        errors="fatal: not a git repository",
    )

    assert git.repository_root(context_with(tmp_path, processes), tmp_path) is None


def test_messages_with_blank_lines_and_paths_with_accents_are_read_exactly(
    tmp_path: Path,
) -> None:
    commits = [
        FakeCommit(
            HASH_A,
            "Prima schermata\n\nCon una riga vuota.\n\n  E un'altra, rientrata.",
            files=(
                FakeFile("città/menù.txt", status="A", added=3),
                FakeFile("tab\there.txt", status="M", added=1, removed=1),
            ),
            author="Zoë  Martín",
        ),
        FakeCommit(
            HASH_B,
            "Rinomina",
            files=(
                FakeFile("new/cassa.js", status="R", added=2, removed=1, source="old/cassa.js"),
                FakeFile("foto.png", status="A", binary=True),
                FakeFile("vecchio.txt", status="D", added=0, removed=4),
            ),
            parent=HASH_A,
        ),
        FakeCommit(HASH_C, "Merge branch 'side'", parent=f"{HASH_B} {HASH_A}"),
    ]
    processes = script_commits(ScriptedProcesses(), commits)

    found = commits_after(context_with(tmp_path, processes), tmp_path, None)

    assert found == (
        Commit(
            hash=HASH_A,
            parent=None,
            committed_at="2026-09-29T10:15:00+02:00",
            author="Zoë Martín",
            message="Prima schermata\n\nCon una riga vuota.\n\n  E un'altra, rientrata.",
            files=(
                ChangedFile("città/menù.txt", "ADDED", 3, 0),
                ChangedFile("tab\there.txt", "MODIFIED", 1, 1),
            ),
        ),
        Commit(
            hash=HASH_B,
            parent=HASH_A,
            committed_at="2026-09-29T10:15:00+02:00",
            author="Anna Rossi",
            message="Rinomina",
            files=(
                ChangedFile("new/cassa.js", "RENAMED", 2, 1),
                ChangedFile("foto.png", "ADDED", 0, 0),
                ChangedFile("vecchio.txt", "DELETED", 0, 4),
            ),
        ),
        Commit(
            hash=HASH_C,
            parent=HASH_B,
            committed_at="2026-09-29T10:15:00+02:00",
            author="Anna Rossi",
            message="Merge branch 'side'",
            files=(),
        ),
    )
    assert git.first_line(found[0].message) == "Prima schermata"


def test_a_long_message_is_trimmed_and_an_empty_one_gets_a_dash(tmp_path: Path) -> None:
    long = "Title\n\n" + "word " * 600
    commits = [FakeCommit(HASH_A, long), FakeCommit(HASH_B, "   ", parent=HASH_A)]
    processes = script_commits(ScriptedProcesses(), commits)

    first, second = commits_after(context_with(tmp_path, processes), tmp_path, None)

    assert len(first.message) <= 2000
    assert first.message.startswith("Title\n\nword word")
    assert not first.message.endswith(" ")
    assert second.message == "-"


def test_names_of_the_kinds_of_change() -> None:
    commit = FakeCommit(
        HASH_A,
        "x",
        files=(
            FakeFile("a.txt", status="A"),
            FakeFile("b.txt", status="C", source="a.txt"),
            FakeFile("c.txt", status="T"),
            FakeFile("d.txt", status="X"),
        ),
    )

    assert git.parse_kinds(kinds_output(commit)) == {
        "a.txt": "ADDED",
        "b.txt": "ADDED",
        "c.txt": "MODIFIED",
        "d.txt": "MODIFIED",
    }
    assert git.parse_log(log_output([])) == []


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        "keys/server.pem",
        "tls/private.KEY",
        "cert.p12",
        "cert.pfx",
        "home/id_rsa",
        "home/id_ed25519.pub",
        "docs/MySecret.txt",
        "secrets/database.json",
        "aws_credentials.json",
        "cert.der",
        "store.jks",
        "android/app.keystore",
        "frontend/node_modules/left-pad/index.js",
        ".venv/lib/site.py",
        "venv/lib/site.py",
        "dist/app.js",
        "web/build/app.js",
        "lib/__pycache__/a.pyc",
    ],
)
def test_secret_names_and_generated_folders_never_reach_the_diff(path: str) -> None:
    assert excluded_path(path)


@pytest.mark.parametrize(
    "path", ["src/build.js", "src/app.js", "README.md", "environment.py", "docs/keys.md"]
)
def test_ordinary_files_reach_the_diff(path: str) -> None:
    assert not excluded_path(path)


def test_the_diff_of_a_commit_skips_what_must_not_be_sent(tmp_path: Path) -> None:
    diff = (
        "diff --git a/src/app.js b/src/app.js\n"
        "--- a/src/app.js\n"
        "+++ b/src/app.js\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/data.bin b/data.bin\n"
        "Binary files a/data.bin and b/data.bin differ\n"
        "diff --git a/huge.json b/huge.json\n"
        "--- a/huge.json\n"
        "+++ b/huge.json\n"
        "@@ -0,0 +1 @@\n"
        f"+{'y' * 210_000}\n"
    )
    commit = FakeCommit(
        HASH_A,
        "Mixed",
        files=(
            FakeFile("src/app.js", added=1, removed=1),
            FakeFile(".env", status="A"),
            FakeFile("data.bin"),
            FakeFile("huge.json", status="A"),
            FakeFile("image.png", status="A", binary=True),
            FakeFile("generated.csv", status="A", added=120_000),
        ),
        diff=diff,
    )
    processes = script_commits(ScriptedProcesses(), [commit])
    context = context_with(tmp_path, processes)
    [found] = commits_after(context, tmp_path, None)

    text = diff_of(context, tmp_path, found)

    assert text == (
        "diff --git a/src/app.js b/src/app.js\n"
        "--- a/src/app.js\n"
        "+++ b/src/app.js\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "[excluded: .env]\n"
        "[excluded: data.bin]\n"
        "[excluded: huge.json]\n"
        "[excluded: image.png]\n"
        "[excluded: generated.csv]\n"
    )
    [shown] = processes.arguments("git", "--literal-pathspecs")
    assert shown[-4:] == ("--", "src/app.js", "data.bin", "huge.json")


def test_a_renamed_file_sends_both_of_its_paths(tmp_path: Path) -> None:
    commit = FakeCommit(
        HASH_A,
        "Rename",
        files=(FakeFile("new.js", status="R", added=1, removed=1, source="old.js"),),
        diff="diff --git a/old.js b/new.js\nsimilarity index 90%\n",
    )
    processes = script_commits(ScriptedProcesses(), [commit])
    context = context_with(tmp_path, processes)
    [found] = commits_after(context, tmp_path, None)

    text = diff_of(context, tmp_path, found)

    assert text == "diff --git a/old.js b/new.js\nsimilarity index 90%\n"
    [shown] = processes.arguments("git", "--literal-pathspecs")
    assert shown[-3:] == ("--", "old.js", "new.js")


def test_a_commit_with_nothing_to_send_runs_no_diff(tmp_path: Path) -> None:
    commit = FakeCommit(HASH_A, "Keys", files=(FakeFile("id_rsa", status="A"),))
    processes = script_commits(ScriptedProcesses(), [commit])
    context = context_with(tmp_path, processes)
    [found] = commits_after(context, tmp_path, None)

    assert diff_of(context, tmp_path, found) == "[excluded: id_rsa]\n"
    assert processes.arguments("git", "--literal-pathspecs") == []


def test_the_cut_keeps_the_last_line_and_the_excluded_files_within_the_limit() -> None:
    text = "".join(f"+line {index}\n" for index in range(20_000))

    cut = bounded_diff(text, ["secret.pem", "logo.png"])
    small = bounded_diff("+one", ["logo.png"])

    assert len(cut) <= MAX_DIFF_LENGTH
    assert cut.endswith(f"\n{CUT_LINE}\n[excluded: secret.pem]\n[excluded: logo.png]\n")
    assert cut.startswith("+line 0\n")
    assert small == "+one\n[excluded: logo.png]\n"
    assert bounded_diff("") == ""


def test_a_very_long_list_of_excluded_files_is_summed_up() -> None:
    paths = [f"node_modules/package-{index}/index.js" for index in range(3000)]

    cut = bounded_diff("+a\n" * 30_000, paths)

    assert len(cut) <= MAX_DIFF_LENGTH
    assert cut.endswith(" more files]\n")
    assert CUT_LINE in cut


def test_the_body_of_a_change_respects_the_limits_of_the_studio() -> None:
    long_path = "folder/" * 100 + "file.js"
    files = tuple(ChangedFile(f"f{index}.js", "ADDED", 1, 0) for index in range(600))
    commit = Commit(
        hash=HASH_A,
        parent=None,
        committed_at=FIRST_DATE,
        author=None,
        message="Many files",
        files=(
            ChangedFile("bad\x07name.js", "ADDED", 1, 0),
            ChangedFile(long_path, "ADDED", 1, 0),
            *files,
        ),
    )

    body = change_body(commit, "a\x00b" + "c" * MAX_DIFF_LENGTH)

    assert len(body["files"]) == 500
    assert body["files"][0]["path"] == "bad?name.js"
    assert len(body["files"][1]["path"]) == 500
    assert body["files"][1]["path"].startswith("…")
    assert body["files"][1]["path"].endswith("folder/file.js")
    assert len(body["diff"]) <= MAX_DIFF_LENGTH
    assert "\x00" not in body["diff"]
    assert body["author"] is None
    assert body["parent"] is None


def test_small_helpers_for_the_screen() -> None:
    assert git.short(HASH_A) == "aaaaaaa"
    assert git.commit_date("2026-09-29T10:15:00+02:00") == "2026-09-29 10:15"
    assert git.commit_date("not a date") == "not a date"
    assert git.first_line("\n\n  First\tline  \nSecond") == "First line"
    assert git.first_line("") == "-"
    assert git.status_paths(" M a.txt\x00R  new.txt\x00old.txt\x00?? b/\x00") == [
        "a.txt",
        "new.txt",
        "b/",
    ]
