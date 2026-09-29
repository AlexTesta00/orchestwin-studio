from __future__ import annotations

import copy
import json
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.terminal import Run, command_context, link_folder, run_ut, terminal

EMAIL = "owner@example.com"
PASSWORD = "Test-password-not-real!"
PROJECT = "Calcolo mancia"
MODEL = "fake-model-not-real"
DESIGNER = "UX_UI_DESIGNER"
CAPABILITIES = "/projects/{project_id}/design/mockups/capabilities"
DECLARATIVE = "/projects/{project_id}/design/mockups"
WITHOUT_DRAWING = {
    "generated_mockups": False,
    "iterations": False,
    "model": None,
    "static_check": False,
}


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    @property
    def folder(self) -> Path:
        return self.tmp_path / "project"

    @property
    def previews(self) -> Path:
        return self.folder / ".orchestwin" / "previews"

    @property
    def base(self) -> str:
        return f"/projects/{self.project.id}"

    def ut(
        self,
        *arguments: str,
        answers: Sequence[str] = (),
        language: str = "en",
        variables: Mapping[str, str] | None = None,
    ) -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
            variables=variables,
        )

    def client(self) -> StudioClient:
        environment = terminal(self.tmp_path, transport=UrlTransport()).environment
        return command_context(environment).client()

    def requests(self, method: str, suffix: str) -> list[RecordedRequest]:
        return [
            item
            for item in self.studio.requests
            if item.method == method and item.path.endswith(suffix)
        ]

    def count(self, method: str, suffix: str) -> int:
        return len(self.requests(method, suffix))

    def writes(self) -> list[str]:
        return [
            item.path.removeprefix(f"/api/v1{self.base}")
            for item in self.studio.requests
            if item.method != "GET" and not item.path.startswith("/api/v1/auth/")
        ]

    def alternative(self, code: str) -> str:
        design = self.project.current("design")
        assert design is not None
        return next(
            str(item["id"]) for item in design["package"]["alternatives"] if item["code"] == code
        )

    def uri(self, name: str) -> str:
        return (self.previews / name).as_uri()


@contextmanager
def design_session(
    tmp_path: Path,
    *,
    through: str = "requirements",
    language: str = "en",
    hosted: bool = True,
    budget_usd: float | None = 60.0,
    job_polls: int = 2,
    twins: int = 2,
    team_without: Sequence[str] = (),
) -> Iterator[Session]:
    with FakeStudio(
        language=language,
        hosted=hosted,
        budget_usd=budget_usd,
        job_polls=job_polls,
        twins=twins,
    ) as studio:
        studio.add_account(EMAIL, PASSWORD)
        project = studio.seed_project(
            owner=EMAIL, name=PROJECT, through=through, team_without=team_without
        )
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(
            tmp_path / "project", project_id=project.id, name=PROJECT, studio=studio.address
        )
        yield Session(studio=studio, project=project, tmp_path=tmp_path)
        assert studio.errors == []


def propose(session: Session) -> Mapping[str, object]:
    answer = session.client().post(design_api.proposals_path(session.project.id))
    assert isinstance(answer, dict)
    return answer["version"]


def finish_job(client: StudioClient, path: str) -> Mapping[str, object]:
    for _ in range(20):
        job = client.get(path)
        assert isinstance(job, dict)
        if job["status"] != "RUNNING":
            return job
    raise AssertionError(f"the job at {path} never ended")


def draw(session: Session, *codes: str) -> dict[str, Mapping[str, object]]:
    client = session.client()
    project_id = session.project.id
    version = design_api.current(client, project_id)
    assert version is not None
    jobs = {}
    for code in codes:
        reply = design_api.start_mockup(client, project_id, version, session.alternative(code))
        assert reply.status == 202
        jobs[code] = str(reply.json()["job_id"])
    return {
        code: finish_job(client, design_api.mockup_job_path(project_id, job_id))
        for code, job_id in jobs.items()
    }


def choose(session: Session, code: str) -> Mapping[str, object]:
    client = session.client()
    project_id = session.project.id
    result = session.project.mockups[session.alternative(code)]
    answer = design_api.propose_revision(client, project_id, result["package"])
    decision = design_api.decide_revision(client, project_id, str(answer["diff"]["id"]))
    return decision["version"]


def prototype_package(session: Session, code: str) -> dict[str, object]:
    version = session.project.current("design")
    assert version is not None
    other = session.studio.seed_project(owner=EMAIL, name="Other", through="design")
    prototype = copy.deepcopy(other.current("design")["package"]["prototype"])
    chosen = session.alternative(code)
    prototype["design_alternative_id"] = chosen
    package = copy.deepcopy(version["package"])
    package["owner_selected_alternative_id"] = chosen
    package["prototype"] = prototype
    return package


def choose_in_the_web(session: Session, code: str) -> Mapping[str, object]:
    client = session.client()
    project_id = session.project.id
    answer = design_api.propose_revision(client, project_id, prototype_package(session, code))
    decision = design_api.decide_revision(client, project_id, str(answer["diff"]["id"]))
    return decision["version"]


def without_drawing(session: Session, *, times: int = 20) -> None:
    session.studio.fail_next("GET", CAPABILITIES, status=200, body=WITHOUT_DRAWING, times=times)


def start_iteration(session: Session, request: str, rules: Sequence[str] = ()) -> str:
    client = session.client()
    version = design_api.current(client, session.project.id)
    assert version is not None
    reply = client.request(
        "POST",
        design_api.iteration_jobs_path(session.project.id),
        body=design_api.iteration_body(version, request, rules),
    )
    assert reply.status == 202
    return str(reply.json()["job_id"])


def test_the_paths_of_the_design_routes() -> None:
    assert design_api.design_path("p") == "/projects/p/design"
    assert design_api.proposals_path("p") == "/projects/p/design/proposals"
    assert design_api.evaluations_path("p") == "/projects/p/design/evaluations"
    assert design_api.mockup_job_path("p", "j") == "/projects/p/design/mockups/jobs/j"
    assert design_api.iteration_job_path("p", "j") == "/projects/p/design/iterations/jobs/j"
    assert design_api.request_job_path("p", "j") == "/projects/p/generation-jobs/j"


def test_the_bodies_carry_the_version_and_its_hash() -> None:
    version = {"id": "v", "content_hash": "h", "version_number": 3}

    assert design_api.version_body(version, alternative_id="a") == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "alternative_id": "a",
    }
    assert design_api.iteration_body(version, "Bigger button", ("Keep it dark",)) == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "request": "Bigger button",
        "assertions": ["Keep it dark"],
    }
    assert design_api.evaluation_body(version, "it-IT")["locale"] == "it-IT"


def test_capabilities_follow_the_model_of_the_studio(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        found = design_api.capabilities(session.client(), session.project.id)

    assert found == design_api.Capabilities(
        generated_mockups=True, iterations=True, static_check=False, model=MODEL
    )


def test_a_studio_without_hosted_model_draws_no_mockup(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        found = design_api.capabilities(session.client(), session.project.id)

    assert found == design_api.NO_CAPABILITIES


@pytest.mark.parametrize(
    ("hosted", "budget", "expected"),
    [
        (True, 60.0, design_api.ModelRuntime(model=True, budget=True)),
        (True, None, design_api.ModelRuntime(model=True, budget=False)),
        (False, 60.0, design_api.ModelRuntime(model=False, budget=False)),
    ],
)
def test_the_model_and_the_budget_are_read_from_the_budget_route(
    tmp_path: Path, hosted: bool, budget: float | None, expected: design_api.ModelRuntime
) -> None:
    with design_session(tmp_path, hosted=hosted, budget_usd=budget) as session:
        found = design_api.model_runtime(session.client())

    assert found == expected


def test_an_older_studio_without_the_budget_route_counts_as_one_with_a_model(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_next(
            "GET", "/model-runtime/budget", status=404, body={"detail": "Not Found"}
        )
        older = design_api.model_runtime(session.client())
        session.studio.fail_next(
            "GET",
            "/model-runtime/budget",
            status=500,
            body={"detail": {"code": "BUDGET_STORE_FAILED"}},
        )
        with pytest.raises(ApiFailure) as broken:
            design_api.model_runtime(session.client())

    assert older == design_api.ModelRuntime(model=True, budget=False)
    assert broken.value.code == "BUDGET_STORE_FAILED"


def test_capabilities_that_cannot_be_read_count_as_unavailable(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_next(
            "GET",
            "/projects/{project_id}/design/mockups/capabilities",
            status=503,
            body={"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}},
        )
        found = design_api.capabilities(session.client(), session.project.id)

    assert found == design_api.NO_CAPABILITIES


def test_current_readiness_and_history_before_and_after_the_proposal(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        before = design_api.readiness(client, project_id)
        missing = design_api.current(client, project_id)
        version = propose(session)
        current = design_api.current(client, project_id)
        history = design_api.history(client, project_id)

    assert before["status"] == "DESIGN_REQUIRED" and before["version"] is None
    assert missing is None
    assert current is not None and current["id"] == version["id"]
    assert [item["code"] for item in current["package"]["alternatives"]] == ["DES-001", "DES-002"]
    assert [item["id"] for item in history] == [version["id"]]


def test_the_deterministic_proposal_has_three_alternatives_without_verdicts(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, hosted=False) as session:
        version = propose(session)

    package = version["package"]
    assert [item["code"] for item in package["alternatives"]] == ["DES-001", "DES-002", "DES-003"]
    assert package["recommended_alternative_id"] == package["alternatives"][0]["id"]
    assert {(item["verdict"], item["quote"]) for item in package["critiques"]} == {(None, None)}


def test_documents_exist_only_for_drawn_mockups(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        propose(session)
        first = session.alternative("DES-001")
        before = design_api.mockup_document(client, project_id, first)
        jobs = draw(session, "DES-001")
        latest = design_api.mockup_document(client, project_id, first)
        applied = design_api.mockup_document(client, project_id, first, source=design_api.APPLIED)
        stored = design_api.latest_mockup(client, project_id, first)
        listed = design_api.project_jobs(client, project_id)
        asked = session.requests("GET", f"{session.base}/design/mockups")

    assert before is None
    assert jobs["DES-001"]["status"] == "SUCCEEDED"
    assert latest is not None and latest["html"].startswith("<!doctype html>")
    assert latest["alternative_id"] == first and latest["source"] == "latest"
    assert applied is None
    assert stored == jobs["DES-001"]["result"]
    assert [request.query for request in asked] == [
        urllib.parse.urlencode({"alternative_id": first})
    ]
    assert [(job["operation"], job["status"], job["alternative_id"]) for job in listed] == [
        ("MOCKUP", "SUCCEEDED", first)
    ]


def test_the_latest_mockup_of_an_alternative_is_read_or_is_none(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        propose(session)
        first = session.alternative("DES-001")
        second = session.alternative("DES-002")
        result = draw(session, "DES-002")["DES-002"]["result"]
        stored = design_api.latest_mockup(client, project_id, second)
        never_drawn = design_api.latest_mockup(client, project_id, first)
        session.studio.fail_next(
            "GET",
            "/projects/{project_id}/design/mockups",
            status=503,
            body={"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}},
        )
        unreadable = design_api.latest_mockup(client, project_id, second)

    assert stored == result
    assert never_drawn is None
    assert unreadable is None


def test_a_revision_is_proposed_decided_and_the_gate_approves_it(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        propose(session)
        result = draw(session, "DES-002")["DES-002"]["result"]
        proposal = design_api.propose_revision(client, project_id, result["package"])
        pending = design_api.revisions(client, project_id)
        decision = design_api.decide_revision(client, project_id, str(proposal["diff"]["id"]))
        submission = design_api.submit_gate(client, project_id)
        approval = design_api.decide_gate(client, project_id)
        approved = session.project.approved("design")

    assert proposal["diff"]["status"] == "PROPOSED"
    assert [item["status"] for item in pending] == ["PROPOSED"]
    assert decision["version"]["version_number"] == 2
    assert submission["status"] == "SUBMITTED"
    assert approval["gate"]["status"] == "APPROVED"
    assert approved


def test_the_declarative_mockup_sends_the_version_and_the_alternative(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        version = propose(session)
        first = session.alternative("DES-001")
        answer = {"status": "MOCKUP_GENERATED", "package": {"prototype": {}}}
        session.studio.fail_next("POST", DECLARATIVE, status=200, body=answer)
        found = design_api.declarative_mockup(client, project_id, version, first)
        with pytest.raises(ApiFailure) as refused:
            design_api.declarative_mockup(client, project_id, version, first)
        sent = session.requests("POST", f"{session.base}/design/mockups")

    assert found == answer
    assert refused.value.code == "GENERATED_MOCKUP_PATH_ACTIVE"
    assert json.loads(sent[0].body) == {
        "design_version_id": version["id"],
        "design_content_hash": version["content_hash"],
        "alternative_id": first,
    }


def test_a_studio_without_a_model_prepares_no_prototype(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        version = propose(session)
        first = session.alternative("DES-001")
        with pytest.raises(ApiFailure) as refused:
            design_api.declarative_mockup(session.client(), session.project.id, version, first)

    assert refused.value.code == design_api.NO_MOCKUP_MODEL
    assert refused.value.http_status == 503


def test_lists_that_do_not_exist_yet_are_empty(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        project_id = session.project.id
        propose(session)
        found = (
            design_api.evaluations(client, project_id),
            design_api.comparison(client, project_id),
            design_api.iterations(client, project_id),
            design_api.revisions(client, project_id),
        )

    assert found == ([], None, [], [])
