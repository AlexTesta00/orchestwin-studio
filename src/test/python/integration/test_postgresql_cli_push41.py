from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Run,
    Scene,
    StudioApi,
    StudioProcess,
    journey_scene,
    read_json,
    say,
    stay_on_the_studio,
)

pytestmark = pytest.mark.integration

INIT_FOLDER = 4
PUSHED_FOLDER = 5
REQUIREMENTS = "requirements/requirements.json"
STATEMENT = "The application shows the share of each friend, tip included, before paying."
LATEST_KEYS = ("schema_version", "pushed_at", "from_version", "to_version", "stages", "files")
SEND = ""
APPROVE = "y"
WRITES = (
    "POST {base}/requirements/revisions",
    "POST {base}/requirements/revisions/{diff}/decision",
    "POST {base}/requirements/gate/submit",
    "POST {base}/requirements/gate/decision",
    "POST {base}/sections/alignment",
    "POST {base}/knowledge-packages",
)


@dataclass
class Flow:
    version: dict[str, object] = field(default_factory=dict)
    code: str = ""


def test_ut_push_sends_a_definition_changed_by_hand_to_the_real_studio(tmp_path: Path) -> None:
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        flow = Flow()
        with journey.step("0 ut login and ut --yes init approve the Definition"):
            define(scene, flow)
        if not journey.problems:
            walk(scene, journey, flow)
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def walk(scene: Scene, journey: Journey, flow: Flow) -> None:
    steps: tuple[tuple[str, Callable[[Scene, Flow], None]], ...] = (
        ("1 a requirement changed by hand, seen with ut push --dry-run", look),
        ("2 ut push with written answers sends and approves the Definition", push),
        ("3 the new version, the approved gate and the folder of the next version", check),
        ("4 a second ut push finds nothing to send", again),
    )
    for name, action in steps:
        with journey.step(name):
            action(scene, flow)
        if journey.problems:
            break
    with journey.step("5 every request of ut went to the Studio of the test"):
        stay_on_the_studio(scene)


def define(scene: Scene, flow: Flow) -> None:
    login = scene.ut(
        "login",
        "--studio",
        scene.origin,
        "--email",
        TEST_EMAIL,
        "--password-stdin",
        directory=scene.outside,
        answers=[TEST_PASSWORD],
    )
    assert login.status == 0, login.transcript()
    init = scene.ut("--yes", "init", "--answers", str(scene.answers))
    assert init.status == 0, init.transcript()
    scene.project_id = read_json(scene.local / "project.json")["project_id"]
    assert scene.folder_numbers() == list(range(INIT_FOLDER, 0, -1)), init.transcript()
    assert knowledge.verify(scene.knowledge).package_version == INIT_FOLDER
    flow.version = scene.document("/requirements/current")
    gate = scene.document("/requirements/gate")
    assert gate["status"] == "APPROVED", gate


def look(scene: Scene, flow: Flow) -> None:
    path = scene.knowledge.joinpath(*REQUIREMENTS.split("/"))
    document = json.loads(path.read_bytes().decode("utf-8"))
    requirement = document["specification"]["requirements"][0]
    flow.code = str(requirement["code"])
    requirement["statement"] = STATEMENT
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))
    run = scene.ut("push", "--dry-run")
    assert (run.status, run.errors) == (0, ""), run.transcript()
    assert_gaps(
        run,
        say("push.summary", version=INIT_FOLDER, pushable=1, derived=0, unknown=0),
        say(
            "push.file_pushable",
            path=REQUIREMENTS,
            change=say("push.change_changed"),
            stage=say("common.stage_requirements"),
        ),
        say("push.diff_line", sign="~", what=f"requirements {flow.code}"),
        say("push.dry_run_done"),
    )
    assert writes_of(run) == [], run.transcript()


def push(scene: Scene, flow: Flow) -> None:
    run = scene.ut("push", answers=[SEND, APPROVE])
    assert (run.status, run.errors) == (0, ""), run.transcript()
    name = say("common.stage_requirements")
    number = int(flow.version["version_number"]) + 1
    verified = knowledge.verify(scene.knowledge)
    assert_gaps(
        run,
        say("push.summary", version=INIT_FOLDER, pushable=1, derived=0, unknown=0),
        say("push.send_stage", stage=name),
        say("init.change_heading", count=1),
        say("push.approve_stage", stage=name),
        say(
            "init.step_approved",
            step=say("common.stage_requirements"),
            version=number,
            path=".orchestwin/steps/requirements.json",
        ),
        say("push.done", stages=name, version=PUSHED_FOLDER, files=len(verified.files)),
    )
    diffs = scene.document("/requirements/revisions")
    approved = [item for item in diffs if item["status"] == "APPROVED"]
    assert len(approved) == 1, diffs
    expected = [line.format(base=scene.base, diff=approved[0]["id"]) for line in WRITES]
    writes = writes_of(run)
    assert [line.split(" -> ")[0] for line in writes] == expected, run.transcript()
    assert all(int(line.split(" -> ")[1].split()[0]) < 300 for line in writes), run.transcript()


def check(scene: Scene, flow: Flow) -> None:
    number = int(flow.version["version_number"]) + 1
    current = scene.document("/requirements/current")
    assert current["version_number"] == number, current["version_number"]
    statement = current["specification"]["requirements"][0]["statement"]
    assert statement == STATEMENT, statement
    gate = scene.document("/requirements/gate")
    assert (gate["status"], gate["artifact"]["version"]) == ("APPROVED", number), gate
    assert scene.folder_numbers() == list(range(PUSHED_FOLDER, 0, -1))
    verified = knowledge.verify(scene.knowledge)
    assert verified.package_version == PUSHED_FOLDER
    local = json.loads(verified.files[REQUIREMENTS])
    assert local["specification"]["requirements"][0]["statement"] == STATEMENT
    assert local["version_number"] == number
    latest = read_json(scene.local / "push" / "latest.json")
    assert tuple(latest) == LATEST_KEYS, list(latest)
    assert {key: value for key, value in latest.items() if key != "pushed_at"} == {
        "schema_version": 1,
        "from_version": INIT_FOLDER,
        "to_version": PUSHED_FOLDER,
        "stages": ["requirements"],
        "files": [REQUIREMENTS],
    }
    assert datetime.fromisoformat(str(latest["pushed_at"])).tzinfo is not None
    step = read_json(scene.local / "steps" / "requirements.json")
    assert step["version"]["version_number"] == number, step


def again(scene: Scene, flow: Flow) -> None:
    run = scene.ut("push")
    assert (run.status, run.errors) == (0, ""), run.transcript()
    assert_gaps(
        run,
        say("push.summary", version=PUSHED_FOLDER, pushable=0, derived=0, unknown=0),
        say("push.nothing"),
    )
    assert writes_of(run) == [], run.transcript()
    assert scene.folder_numbers() == list(range(PUSHED_FOLDER, 0, -1))


def writes_of(run: Run) -> list[str]:
    return [exchange.line() for exchange in run.writes()]


def assert_gaps(run: Run, *sentences: str) -> None:
    gaps = run.order_gaps(*sentences)
    assert gaps == [], "\n".join([*gaps, run.transcript()])
