from __future__ import annotations

import json
import shutil
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from orchestwin.cli import folder as knowledge
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut

EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
WIDE = {"COLUMNS": "400"}
REQUIREMENTS = "requirements/requirements.json"
DESIGN = "design/design.json"
BRIEF = "brief/brief.json"
TEAM = "team/team.json"
TWINS = "twins/twins.json"
STATEMENT = "The page shows the tip of each person next to the total."
GOALS = ["Pay the bill quickly", "Split the bill fairly"]
ASSERTION = "Keep the buttons large enough for a thumb."
GOAL = "Share the bill by message"
REMOVED_AGENT = "FRONTEND_ENGINEER"
NOTE = "notes/ideas.txt"
SEND = ""
APPROVE = "y"
REFUSE = "n"


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    @property
    def root(self) -> Path:
        return self.tmp_path / "project"

    @property
    def folder(self) -> Path:
        return self.root / "orchestwin"

    def ut(self, *arguments: str, answers: Sequence[str] = (), language: str = "en") -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
            variables=WIDE,
        )

    def read(self, path: str) -> dict:
        return json.loads(self.folder.joinpath(*path.split("/")).read_bytes().decode("utf-8"))

    def write(self, path: str, document: object) -> None:
        text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        target = self.folder.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def files(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.folder).as_posix(): path.read_bytes()
            for path in sorted(self.folder.rglob("*"))
            if path.is_file()
        }

    def writes(self, start: int) -> list[str]:
        return [
            f"{request.method} {request.path}"
            for request in self.studio.requests[start:]
            if request.method != "GET"
        ]


@contextmanager
def session(tmp_path: Path, *, through: str = "design") -> Iterator[Session]:
    with FakeStudio(language="en", twins=2) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through=through)
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(tmp_path / "project", project_id=project.id, name=NAME, studio=studio.address)
        current = Session(studio=studio, project=project, tmp_path=tmp_path)
        published = current.ut("package", "publish")
        assert published.status == 0, published.errors
        yield current
        assert studio.errors == []


def change_requirement(current: Session) -> str:
    document = current.read(REQUIREMENTS)
    requirement = document["specification"]["requirements"][0]
    requirement["statement"] = STATEMENT
    current.write(REQUIREMENTS, document)
    return str(requirement["code"])


def file_line(path: str, kind: str, change: str = "changed", stage: str = "") -> str:
    if kind == "pushable":
        return f'  {path} ({change}): document of the "{stage}" step, its changes can be sent.'
    if kind == "derived":
        return f"  {path} ({change}): derived file, it is not sent."
    return (
        f"  {path} ({change}): a file the Studio does not know, it stays on the disk and is not "
        "sent."
    )


def summary(version: int, pushable: int, derived: int, unknown: int) -> str:
    return (
        f"Compared with version {version} of the folder: step documents changed {pushable}, "
        f"derived files changed {derived}, unknown files {unknown}."
    )


def latest(current: Session) -> dict:
    path = current.root / ".orchestwin" / "push" / "latest.json"
    return json.loads(path.read_bytes().decode("utf-8"))


def test_a_folder_like_the_published_one_has_nothing_to_send(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        start = len(current.studio.requests)
        run = current.ut("push")
        writes = current.writes(start)

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        summary(1, 0, 0, 0),
        "No step document has changes to send: there is nothing to do.",
    ]
    assert writes == []


def test_a_dry_run_lists_the_definition_changed_by_hand_and_sends_nothing(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        code = change_requirement(current)
        before = current.files()
        start = len(current.studio.requests)
        run = current.ut("push", "--dry-run")
        writes = current.writes(start)
        after = current.files()

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        summary(1, 1, 0, 0),
        file_line(REQUIREMENTS, "pushable", stage="Definition"),
        f"    ~ requirements {code}",
        "Trial without sending (--dry-run): the Studio and the folder stay as they are.",
    ]
    assert writes == []
    assert after == before


def test_an_approved_definition_becomes_a_version_and_the_folder_follows(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        code = change_requirement(current)
        version = current.project.current("requirements")["version_number"]
        start = len(current.studio.requests)
        run = current.ut("push", answers=[SEND, APPROVE])
        writes = current.writes(start)
        specification = current.project.current("requirements")
        gate = current.project.gate("requirements")
        approved = current.project.approved("requirements")
        verified = knowledge.verify(current.folder)
        local = current.read(REQUIREMENTS)
        written = latest(current)
        packages = current.project.knowledge_versions()

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert lines[:3] == [
        summary(1, 1, 0, 0),
        file_line(REQUIREMENTS, "pushable", stage="Definition"),
        f"    ~ requirements {code}",
    ]
    assert 'Send the changes of "Definition" to the Studio? [Y/n] ' in run.output
    assert "The proposed change. Changes: 1." in lines
    assert f"  ~ changes the requirement {code}: Amount entry: {STATEMENT}" in lines
    assert (
        'Do you approve the differences of "Definition"? They become a new version, supplied '
        "by you. [y/N] " in run.output
    )
    assert (
        f'Step "Definition" approved (version {version + 1}). Saved in '
        ".orchestwin/steps/requirements.json." in lines
    )
    assert lines[-1] == (
        f"Sent: Definition. Folder at version {verified.package_version} "
        f"({len(verified.files)} files)."
    )
    assert specification["version_number"] == version + 1
    assert specification["specification"]["requirements"][0]["statement"] == STATEMENT
    assert gate is not None and gate["status"] == "APPROVED"
    assert approved
    assert verified.package_version == packages[-1]["version_number"] == 2
    assert local["specification"]["requirements"][0]["statement"] == STATEMENT
    assert writes[:4] == [
        f"POST /api/v1/projects/{current.project.id}/requirements/revisions",
        *writes[1:2],
        f"POST /api/v1/projects/{current.project.id}/requirements/gate/submit",
        f"POST /api/v1/projects/{current.project.id}/requirements/gate/decision",
    ]
    assert writes[1].endswith("/decision") and "/requirements/revisions/" in writes[1]
    assert {key: value for key, value in written.items() if key != "pushed_at"} == {
        "schema_version": 1,
        "from_version": 1,
        "to_version": 2,
        "stages": ["requirements"],
        "files": [REQUIREMENTS],
    }
    assert written["pushed_at"].startswith("2026-09-29T")


def test_a_refused_definition_leaves_the_studio_and_the_folder_as_they_were(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        change_requirement(current)
        version = current.project.current("requirements")["version_number"]
        before = current.files()
        run = current.ut("push", answers=[SEND, REFUSE])
        after = current.files()
        specification = current.project.current("requirements")
        diffs = current.project.requirement_diffs
        packages = current.project.knowledge_versions()

    assert run.status == 1
    assert run.errors == ""
    assert '"Definition" stays as it was in the Studio.' in run.output.splitlines()
    assert "Sent:" not in run.output
    assert specification["version_number"] == version
    assert [diff["status"] for diff in diffs] == ["REJECTED"]
    assert diffs[0]["decision_reason"] == "Refused by the owner of the project with ut push."
    assert len(packages) == 1
    assert after == before
    assert not (current.root / ".orchestwin" / "push").exists()


def test_yes_skips_the_send_question_but_never_the_approval(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        change_requirement(current)
        version = current.project.current("requirements")["version_number"]
        run = run_ut(
            ["--yes", "push"],
            current.tmp_path,
            transport=UrlTransport(),
            answers=[APPROVE],
            variables=WIDE,
        )
        stored = current.project.current("requirements")["version_number"]

    assert (run.status, run.errors) == (0, "")
    assert "Send the changes" not in run.output
    assert 'Do you approve the differences of "Definition"?' in run.output
    assert stored == version + 1


def test_a_stage_not_sent_stays_as_it_was_and_nothing_is_written(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        change_requirement(current)
        before = current.files()
        start = len(current.studio.requests)
        run = current.ut("push", answers=[REFUSE])
        writes = current.writes(start)
        after = current.files()

    assert (run.status, run.errors) == (1, "")
    assert run.output.splitlines()[-1] == '"Definition" stays as it was in the Studio.'
    assert "Do you approve" not in run.output
    assert writes == []
    assert after == before


def test_a_derived_file_changed_by_hand_is_not_sent(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        path = current.folder / "requirements" / "requirements.md"
        path.write_bytes(path.read_bytes() + b"A line added by hand.\n")
        start = len(current.studio.requests)
        run = current.ut("push")
        writes = current.writes(start)

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        summary(1, 0, 1, 0),
        file_line("requirements/requirements.md", "derived"),
        "Derived files are generated again by the Studio: change the JSON documents of the steps.",
        "No step document has changes to send: there is nothing to do.",
    ]
    assert writes == []


def test_a_file_unknown_to_the_studio_stays_on_the_disk(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        note = current.folder.joinpath(*NOTE.split("/"))
        note.parent.mkdir()
        note.write_bytes(b"Ideas for later.\n")
        nothing = current.ut("push")
        change_requirement(current)
        sent = current.ut("push", answers=[SEND, APPROVE])
        kept = note.read_bytes()

    assert (nothing.status, nothing.errors) == (0, "")
    assert nothing.output.splitlines() == [
        summary(1, 0, 0, 1),
        file_line(NOTE, "unknown", change="added"),
        "No step document has changes to send: there is nothing to do.",
    ]
    assert (sent.status, sent.errors) == (0, "")
    assert file_line(NOTE, "unknown", change="added") in sent.output.splitlines()
    assert sent.output.splitlines()[-1] == (
        f"Put back in the folder as you left them, without sending them: {NOTE}. While they "
        "are there, the folder does not pass the verification."
    )
    assert kept == b"Ideas for later.\n"


def test_a_studio_ahead_of_the_folder_stops_the_push(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        copy = tmp_path / "copy"
        shutil.copytree(current.folder, copy)
        current.project.mark_knowledge_changed()
        assert current.ut("package", "publish").status == 0
        shutil.rmtree(current.folder)
        shutil.copytree(copy, current.folder)
        change_requirement(current)
        start = len(current.studio.requests)
        run = current.ut("push")
        italian = current.ut("push", language="it")
        writes = current.writes(start)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == (
        "The Studio is at version 2, the folder starts from version 1: download it with "
        "`ut package pull` and make the changes again.\n"
    )
    assert italian.errors == (
        "Lo Studio è alla versione 2, la cartella parte dalla 1: scarica con `ut package pull` "
        "e rifai le modifiche.\n"
    )
    assert writes == []


def test_a_revision_waiting_in_the_studio_stops_the_push(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        change_requirement(current)
        interrupted = current.ut("push", answers=[SEND])
        again = current.ut("push", answers=[SEND])
        diffs = current.project.requirement_diffs

    assert interrupted.status == 1
    assert "The input closed while an answer was awaited" in interrupted.errors
    assert again.status == 1
    assert again.errors == (
        'A revision already waits for "Definition": decide it in the web before sending.\n'
    )
    assert [diff["status"] for diff in diffs] == ["PROPOSED"]


def test_the_stage_option_sends_only_the_design_and_keeps_the_other_changes(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        change_requirement(current)
        changed = current.read(REQUIREMENTS)
        document = current.read(DESIGN)
        document["package"]["owner_assertions"] = [ASSERTION]
        current.write(DESIGN, document)
        requirements = current.project.current("requirements")["version_number"]
        design = current.project.current("design")["version_number"]
        run = current.ut("push", "--stage", "design", answers=[SEND, APPROVE])
        after = current.project.current("design")
        gate = current.project.gate("design")
        unchanged = current.project.current("requirements")["version_number"]
        local = current.read(REQUIREMENTS)
        written = latest(current)

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert lines[:4] == [
        summary(1, 2, 0, 0),
        file_line(DESIGN, "pushable", stage="Design & Evaluation"),
        "    + owner_assertions",
        file_line(REQUIREMENTS, "pushable", stage="Definition"),
    ]
    assert "The proposed change. Changes: 1." in lines
    assert f"    + owner_assertions {ASSERTION}" in lines
    assert 'Send the changes of "Definition" to the Studio?' not in run.output
    assert lines[-2] == "Sent: Design & Evaluation. Folder at version 2 (66 files)."
    assert lines[-1] == (
        f"Put back in the folder as you left them, without sending them: {REQUIREMENTS}. "
        "While they are there, the folder does not pass the verification."
    )
    assert after["version_number"] == design + 1
    assert after["package"]["owner_assertions"] == [ASSERTION]
    assert gate is not None and gate["status"] == "APPROVED"
    assert unchanged == requirements
    assert local == changed
    assert written["stages"] == ["design"]


def test_the_brief_and_the_team_are_sent_and_approved_one_after_the_other(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        brief = current.read(BRIEF)
        brief["brief"]["fields"]["goals"].append(GOAL)
        brief["brief"]["fields"]["audience"] = "Friends at the table"
        current.write(BRIEF, brief)
        team = current.read(TEAM)
        team["proposal"]["members"] = [
            member for member in team["proposal"]["members"] if member["agent_id"] != REMOVED_AGENT
        ]
        current.write(TEAM, team)
        run = current.ut("push", answers=[SEND, APPROVE, SEND, APPROVE])
        stored_brief = current.project.current("brief")
        stored_team = current.project.current("team")
        approvals = [current.project.approved(stage) for stage in ("brief", "team", "twins")]
        verified = knowledge.verify(current.folder)
        written = latest(current)

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert lines[:7] == [
        summary(1, 2, 0, 0),
        file_line(BRIEF, "pushable", stage="Brief"),
        "    + audience",
        "    ~ goals",
        "    Fields of the Brief that the Studio does not expect, left out: audience.",
        file_line(TEAM, "pushable", stage="Perspectives"),
        f"    - members {REMOVED_AGENT}",
    ]
    assert 'Step "Brief" approved (version 2). Saved in .orchestwin/steps/brief.json.' in lines
    assert GOAL in stored_brief["brief"]["goals"]
    assert REMOVED_AGENT not in stored_team["selected_agent_ids"]
    assert stored_team["revision_kind"] == "OWNER_EDITED"
    assert approvals == [True, True, True]
    assert lines[-1] == (
        f"Sent: Brief, Perspectives. Folder at version {verified.package_version} "
        f"({len(verified.files)} files)."
    )
    assert written["stages"] == ["brief", "team"]
    assert written["files"] == [BRIEF, TEAM]


def test_a_twin_field_is_sent_and_the_twins_are_approved_again(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        document = current.read(TWINS)
        twin = document["snapshot"]["twin_versions"][0]
        name = twin["profile"]["name"]
        twin["profile"]["name"] = f"{name} renamed"
        for item in twin["profile"]["observations"]:
            if item["observation_key"] == "user_twin.goals":
                item["value"]["items"] = GOALS
        current.write(TWINS, document)
        snapshot = current.project.current("twins")["version_number"]
        run = current.ut("push", answers=[SEND, APPROVE])
        stored = current.project.current("twins")
        approved = current.project.approved("twins")
        diffs = current.project.twin_diffs

    assert (run.status, run.errors) == (0, "")
    lines = run.output.splitlines()
    assert lines[:4] == [
        summary(1, 1, 0, 0),
        file_line(TWINS, "pushable", stage="User Twin"),
        f"    ~ {name}: Goals",
        f'    Changes of "{name}" that cannot be sent, left out: Name.',
    ]
    assert f"    ~ Goals: {GOALS[0]}; {GOALS[1]}" in lines
    assert f'Do you approve the differences of "{name}"?' in run.output
    assert stored["version_number"] == snapshot + 1
    revised = next(
        item for item in stored["snapshot"]["twin_versions"] if item["twin_id"] == twin["twin_id"]
    )
    goals = next(
        item
        for item in revised["profile"]["observations"]
        if item["observation_key"] == "user_twin.goals"
    )
    assert goals["value"]["items"] == GOALS
    assert revised["profile"]["name"] == name
    assert approved
    assert [diff["status"] for diff in diffs] == ["APPROVED"]
    assert lines[-1].startswith("Sent: User Twin. Folder at version 2")


def test_the_report_speaks_italian(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        code = change_requirement(current)
        run = current.ut("push", "--dry-run", language="it")

    assert run.status == 0
    assert run.output.splitlines() == [
        "Rispetto alla versione 1 della cartella: documenti dei passi cambiati 1, file derivati "
        "cambiati 0, file sconosciuti 0.",
        f"  {REQUIREMENTS} (cambiato): documento del passo «Definizione», le sue modifiche si "
        "possono inviare.",
        f"    ~ requirements {code}",
        "Prova senza invio (--dry-run): lo Studio e la cartella restano come sono.",
    ]


def test_a_design_missing_in_the_studio_cannot_be_supplied(tmp_path: Path) -> None:
    with session(tmp_path, through="requirements") as current:
        design = {"package": {"alternatives": []}}
        current.write(DESIGN, design)
        run = current.ut("push", answers=[SEND])

    assert run.status == 1
    assert file_line(DESIGN, "pushable", change="added", stage="Design & Evaluation") in run.output
    assert run.errors == (
        "The Studio has no Design yet: generate it with `ut design`; a Design written by hand "
        "cannot be supplied.\n"
    )
