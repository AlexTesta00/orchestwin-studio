from __future__ import annotations

import gc
import hashlib
import io
import json
import threading
import urllib.error
import urllib.request
import warnings
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest

from orchestwin.agents.perspectives import perspective_views
from orchestwin.agents.selection_rules import determine_team_constraints
from orchestwin.knowledge.archive import read_verified_folder
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.projects.domain import ProjectMode

from .support.fake_studio import COSTS, PREFIX, FakeProject, FakeStudio
from .support.folders import folder_frame, partial_archive, valid_archive

STEPS = ("brief", "team", "twins", "requirements", "design")
EMAIL = "owner@example.com"
OTHER = "other@example.com"
PASSWORD = "Test-password-not-real!"
PREFER = {"Prefer": "respond-async"}
ANSWERS = {
    "problem": {"kind": "TEXT", "text": "Al tavolo nessuno sa quanto lasciare."},
    "target_users": {"kind": "ITEM_LIST", "items": ["Camerieri", "Clienti"]},
    "goals": {"kind": "ITEM_LIST", "items": ["Calcolare la mancia in fretta"]},
    "functional_requirements": {"kind": "UNKNOWN"},
}
BOUNDARY = "fake-boundary-not-real"


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    headers: Mapping[str, str]
    content: bytes

    def json(self) -> object:
        return json.loads(self.content.decode("utf-8"))


class Client:
    def __init__(self, studio: FakeStudio) -> None:
        self.base = studio.address + PREFIX
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token: str | None = None
        self.refresh_token: str | None = None

    def send(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> Reply:
        data = content
        request_headers = dict(headers or {})
        if content is None and body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        if self.token is not None:
            request_headers.setdefault("Authorization", f"Bearer {self.token}")
        request = urllib.request.Request(
            self.base + path, data=data, headers=request_headers, method=method
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return Reply(response.status, _lower(response.headers), response.read())
        except urllib.error.HTTPError as error:
            with error:
                return Reply(error.code, _lower(error.headers), error.read())

    def get(self, path: str) -> Reply:
        return self.send("GET", path)

    def post(self, path: str, body: object = None, **options: object) -> Reply:
        return self.send("POST", path, body, **options)

    def login(self, email: str = EMAIL, password: str = PASSWORD) -> Reply:
        reply = self.post("/auth/login", {"email": email, "password": password})
        if reply.status == 200:
            self.token = str(reply.json()["access_token"])
            self.refresh_token = _cookie(reply)
        return reply

    def refresh(self, token: str | None) -> Reply:
        headers = {} if token is None else {"Cookie": f"orchestwin_refresh={token}"}
        saved, self.token = self.token, None
        try:
            return self.post("/auth/refresh", headers=headers)
        finally:
            self.token = saved


def _lower(headers: object) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def _cookie(reply: Reply) -> str:
    jar: SimpleCookie = SimpleCookie()
    jar.load(reply.headers["set-cookie"])
    return jar["orchestwin_refresh"].value


def signed_in(studio: FakeStudio, email: str = EMAIL) -> Client:
    studio.add_account(email, PASSWORD)
    client = Client(studio)
    assert client.login(email).status == 200
    return client


def new_project(client: Client, name: str = "Calcolo mancia") -> str:
    reply = client.post("/projects", {"display_name": name, "mode": "GREENFIELD_GENERATION"})
    assert reply.status == 201
    return f"/projects/{reply.json()['id']}"


def follow(client: Client, path: str) -> tuple[dict, int]:
    polls = 0
    while True:
        reply = client.get(path)
        assert reply.status == 200
        polls += 1
        job = reply.json()
        if job["status"] != "RUNNING":
            return job, polls
        assert polls < 20


def later(client: Client, base: str, path: str, body: object = None) -> dict:
    reply = client.post(base + path, body, headers=PREFER)
    assert reply.status == 202
    assert reply.headers["preference-applied"] == "respond-async"
    started = reply.json()
    assert (started["kind"], started["status"], started["response"]) == ("REQUEST", "RUNNING", None)
    job, _ = follow(client, f"{base}/generation-jobs/{started['job_id']}")
    return job["response"]


def approve(client: Client, submit: str, decide: str) -> dict:
    submitted = client.post(submit)
    assert submitted.status in {200, 201}
    decided = client.post(decide, {"action": "APPROVE"})
    assert decided.status == 200
    return decided.json()


def stage(client: Client, base: str) -> tuple[str, str]:
    project = client.get(base).json()
    return project["current_stage"], project["next_action"]


def multipart(fields: Mapping[str, str], files: Mapping[str, tuple[str, str, bytes]]) -> bytes:
    parts = []
    for name, value in fields.items():
        head = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
        parts.append(head.encode("utf-8") + value.encode("utf-8") + b"\r\n")
    for name, (file_name, media_type, content) in files.items():
        head = (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; "
            f'name="{name}"; filename="{file_name}"\r\nContent-Type: {media_type}\r\n\r\n'
        )
        parts.append(head.encode("utf-8") + content + b"\r\n")
    parts.append(f"--{BOUNDARY}--\r\n".encode("ascii"))
    return b"".join(parts)


def walk_brief(client: Client, base: str) -> dict:
    started = client.post(base + "/brief-dialogue", {"statement": "Una pagina per la mancia."})
    assert started.status == 201
    state = started.json()
    assert state["status"] == "BRIEF_DIALOGUE_STARTED"
    asked = []
    while True:
        turns = state["snapshot"]["turns"]
        pending = [turn for turn in turns if turn["answer"] is None]
        if not pending:
            break
        asked.append(pending[0]["field"])
        body = {**ANSWERS[pending[0]["field"]], "expected_turn_count": len(turns)}
        reply = client.post(base + "/brief-dialogue/answers", body)
        assert reply.status == 201
        state = reply.json()
    assert asked == ["problem", "target_users", "goals", "functional_requirements"]
    assert state["status"] == "BRIEF_DIALOGUE_READY"
    assert state["progress"]["open_essential_fields"] == []
    synthesis = client.post(
        base + "/brief-dialogue/synthesis",
        {"expected_turn_count": len(state["snapshot"]["turns"])},
    )
    assert synthesis.status == 201
    return synthesis.json()


def walk_twins(client: Client, base: str) -> list:
    proposed = later(client, base, "/user-modeling/personas/proposals")
    assert proposed["status_code"] == 200
    assert len(proposed["body"]["versions"]) == 2
    for persona in client.get(base + "/user-modeling/personas").json():
        decided = client.post(
            f"{base}/user-modeling/personas/{persona['persona_id']}/decision",
            {"decision": "CONFIRM"},
        )
        assert decided.json()["version"]["profile"]["confirmation_status"] == "CONFIRMED"
    generated = later(client, base, "/user-modeling/snapshots/generate")
    assert (generated["status_code"], generated["body"]["status"]) == (200, "CREATED")
    decision = approve(
        client, base + "/user-modeling/gate/submit", base + "/user-modeling/gate/decision"
    )
    assert decision["outcome"] == "APPLIED"
    readiness = client.get(base + "/user-modeling/readiness").json()
    assert readiness["workflow_state"] == "READY_FOR_REQUIREMENTS_DEFINITION"
    return generated["body"]["twin_versions"]


def mockups(client: Client, base: str, current: dict) -> dict[str, dict]:
    started = {}
    for alternative in current["package"]["alternatives"]:
        reply = client.post(
            base + "/design/mockups/jobs",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "alternative_id": alternative["id"],
            },
        )
        assert reply.status == 202
        assert "preference-applied" not in reply.headers
        started[alternative["id"]] = reply.json()["job_id"]
    results = {}
    for alternative_id, job_id in started.items():
        job, polls = follow(client, f"{base}/design/mockups/jobs/{job_id}")
        assert (job["kind"], job["status"], job["alternative_id"], polls) == (
            "MOCKUP",
            "SUCCEEDED",
            alternative_id,
            3,
        )
        results[alternative_id] = job["result"]
    return results


def apply(client: Client, base: str, package: dict) -> dict:
    proposed = client.post(base + "/design/revisions", {"package": package})
    assert proposed.status == 201
    diff = proposed.json()["diff"]
    decided = client.post(f"{base}/design/revisions/{diff['id']}/decision", {"decision": "APPROVE"})
    assert decided.status == 200
    return decided.json()["version"]


def review(client: Client, base: str, current: dict) -> dict:
    response = later(
        client,
        base,
        "/design/evaluations",
        {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "locale": "it-IT",
        },
    )
    assert response["status_code"] == 201
    return response["body"]


def test_the_whole_path_runs_with_urllib() -> None:
    with FakeStudio(language="it", twins=2, job_polls=2) as studio:
        studio.add_account(EMAIL, PASSWORD)
        client = Client(studio)
        assert client.get("/health").json() == {"status": "ok"}
        assert client.login().status == 200
        assert client.get("/auth/me").json()["email"] == EMAIL
        assert client.get("/model-runtime/budget").json()["total_microusd"] == 60_000_000
        base = new_project(client)
        assert stage(client, base) == ("BRIEF", "DESCRIBE_IDEA")

        synthesis = walk_brief(client, base)
        brief = synthesis["brief_version"]["brief"]
        assert brief["name"] == "Calcolo mancia"
        assert brief["problem"] == ANSWERS["problem"]["text"]
        assert brief["missing_fields"] == []
        proposals = synthesis["assumptions"]
        assert [item["field"] for item in proposals] == [
            "functional_requirements",
            "non_functional_requirements",
            "definition_of_done",
        ]
        accepted = client.post(f"{base}/brief-assumptions/{proposals[0]['id']}/accept", {})
        assert accepted.json()["status"] == "ACCEPTED"
        rejected = client.post(
            f"{base}/brief-assumptions/{proposals[1]['id']}/reject", {"reason": "Non serve"}
        )
        assert rejected.json()["assumption"]["status"] == "REJECTED"
        everything = client.post(base + "/brief-assumptions/accept-all")
        assert [item["field"] for item in everything.json()["accepted"]] == ["definition_of_done"]
        assert client.post(base + "/brief-assumptions/accept-all").status == 409
        gate = approve(
            client, base + "/gates/project-brief/submit", base + "/gates/project-brief/decisions"
        )
        assert gate["gate"]["status"] == "APPROVED"
        assert client.get(base).json()["current_brief_version"] == 4
        assert stage(client, base) == ("TEAM", "APPROVE_TEAM")

        assert client.post(base + "/team-proposals").status == 201
        assert (
            "UX_UI_DESIGNER"
            in client.get(base + "/team-proposals/current").json()["selected_agent_ids"]
        )
        approve(client, base + "/gates/agent-team/submit", base + "/gates/agent-team/decisions")
        assert stage(client, base) == ("USER_TWINS", "CONFIRM_TWINS")

        twins = walk_twins(client, base)
        assert stage(client, base) == ("REQUIREMENTS", "APPROVE_REQUIREMENTS")

        created = later(client, base, "/requirements/proposals")
        assert (created["status_code"], created["body"]["status"]) == (201, "CREATED")
        approve(client, base + "/requirements/gate/submit", base + "/requirements/gate/decision")
        assert stage(client, base) == ("DESIGN", "APPROVE_DESIGN")

        generated = later(client, base, "/design/proposals")
        assert generated["status_code"] == 201
        current = client.get(base + "/design/current").json()
        assert [item["code"] for item in current["package"]["alternatives"]] == [
            "DES-001",
            "DES-002",
        ]
        assert client.get(base + "/design/mockups/capabilities").json()["generated_mockups"]
        results = mockups(client, base, current)
        assert [
            [warning["code"] for warning in results[item["id"]]["warnings"]]
            for item in current["package"]["alternatives"]
        ] == [[], ["LIST_TOO_SHORT"]]
        for alternative_id in results:
            document = client.get(
                f"{base}/design/mockups/document?alternative_id={alternative_id}&source=latest"
            ).json()["html"]
            assert '<html lang="it">' in document
            assert '<section class="ot-screen" id="SCR-001"' in document
        chosen = current["package"]["recommended_alternative_id"]
        applied = apply(client, base, results[chosen]["package"])
        assert (applied["version_number"], applied["ready_for_gate"]) == (2, True)

        first = review(client, base, applied)
        assert len(first["responses"]) == 2
        pins = client.get(f"{base}/design/evaluations/{first['id']}/pins").json()
        places = {
            element["code"]: (screen["code"], element["kind"])
            for screen in applied["package"]["prototype"]["screens"]
            for element in screen["elements"]
        }
        assert [places[pin["element_code"]] for pin in pins["pins"]] == [
            ("SCR-001", "LINK"),
            ("SCR-002", "STATUS"),
        ]
        assert [item["screen_code"] for item in pins["unanchored"]] == ["SCR-001"]
        pinned = client.get(f"{base}/design/evaluations/{first['id']}/document").json()
        assert pinned["html"].count('class="ot-pin"') == 2
        assert '<html lang="it-IT">' in pinned["html"]

        started = client.post(
            base + "/design/iterations/jobs",
            {
                "design_version_id": applied["id"],
                "design_content_hash": applied["content_hash"],
                "request": "Metti il pulsante in alto",
                "assertions": ["Il pulsante principale resta visibile"],
            },
        )
        assert started.status == 202
        iteration, _ = follow(client, f"{base}/design/iterations/jobs/{started.json()['job_id']}")
        assert iteration["status"] == "SUCCEEDED"
        assert iteration["result"]["changes"]
        iterated = apply(client, base, iteration["result"]["package"])
        assert iterated["package"]["owner_assertions"] == ["Il pulsante principale resta visibile"]
        document = client.get(
            f"{base}/design/mockups/document?alternative_id={chosen}&source=applied"
        ).json()
        assert "Calcola la mancia in un tocco" in document["html"]
        items = client.get(base + "/design/iterations").json()["items"]
        assert [(item["status"], item["applied_design_version_number"]) for item in items] == [
            ("APPLIED", iterated["version_number"])
        ]
        review(client, base, iterated)
        comparison = client.get(base + "/design/evaluations/comparison").json()
        assert comparison["counts"]["resolved"] == 1
        assert comparison["counts"]["persisting"] == 2

        twin_id = twins[0]["twin_id"]
        turn = client.post(
            f"{base}/user-twins/{twin_id}/conversation/turns",
            {"question": "Che cosa ti serve?", "expected_turn_count": 0},
        )
        assert turn.status == 201
        assert (
            len(client.get(f"{base}/user-twins/{twin_id}/conversation").json()["snapshot"]["turns"])
            == 1
        )

        approve(client, base + "/design/gate/submit", base + "/design/gate/decision")
        assert stage(client, base) == ("PACKAGE", "DOWNLOAD_FOLDER")

        published = client.post(base + "/knowledge-packages", {})
        assert (published.status, published.json()["reused"]) == (201, False)
        again = client.post(base + "/knowledge-packages", {})
        assert (again.status, again.json()["version"]["version_number"]) == (200, 1)
        history = client.get(base + "/knowledge-packages").json()
        assert [item["version_number"] for item in history["versions"]] == [1]
        archive = client.get(base + "/knowledge-packages/1/archive")
        assert archive.headers["content-type"] == "application/zip"
        assert archive.headers["x-content-sha256"] == hashlib.sha256(archive.content).hexdigest()
        assert read_verified_folder(archive.content).project_name == "Calcolo mancia"

        imported = client.post(
            "/project-imports",
            content=multipart(
                {"display_name": "Copia del progetto"},
                {"archive": ("folder.zip", "application/zip", archive.content)},
            ),
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        assert imported.status == 201
        body = imported.json()
        assert body["project"]["display_name"] == "Copia del progetto"
        assert body["approval_required"] == ["brief", "team", "twins", "requirements", "design"]
        copy_base = f"/projects/{body['project']['id']}"
        origin = client.get(copy_base + "/import").json()
        assert origin["archive_hash"] == hashlib.sha256(archive.content).hexdigest()
        assert stage(client, copy_base) == ("BRIEF", "APPROVE_BRIEF")

        usage = client.get(base + "/model-usage").json()
        budget = client.get("/model-runtime/budget").json()
        assert usage["totals"]["cost_microusd"] == studio.spent_microusd
        assert budget["spent_total_microusd"] == studio.spent_microusd
        assert budget["remaining_total_microusd"] == 60_000_000 - studio.spent_microusd
        assert studio.project(body["project"]["id"]).name == "Copia del progetto"
        assert studio.errors == []


def test_the_refresh_rotates_the_cookie_and_a_reuse_closes_the_family() -> None:
    with FakeStudio() as studio:
        first = signed_in(studio)
        second = Client(studio)
        assert second.login().status == 200
        original = first.refresh_token
        rotated = first.refresh(original)
        assert rotated.status == 200
        renewed = _cookie(rotated)
        assert renewed != original
        assert "Path=/api/v1/auth" in rotated.headers["set-cookie"]
        reused = first.refresh(original)
        assert (reused.status, reused.json()) == (401, {"detail": "refresh_token_reuse_detected"})
        assert 'orchestwin_refresh=""' in reused.headers["set-cookie"]
        assert first.refresh(renewed).json() == {"detail": "refresh_token_reuse_detected"}
        assert second.refresh(second.refresh_token).status == 200
        assert first.refresh(None).json() == {"detail": "invalid_refresh_token"}
        assert first.get("/auth/me").status == 200


def test_the_sign_in_refuses_and_the_logout_closes_the_session() -> None:
    with FakeStudio() as studio:
        studio.add_account(EMAIL, PASSWORD)
        client = Client(studio)
        refused = client.login(password="Wrong-password-not-real!")
        assert (refused.status, refused.headers["www-authenticate"]) == (401, "Bearer")
        invalid = client.post("/auth/login", {"email": EMAIL})
        assert invalid.status == 422
        assert invalid.json()["detail"] == "invalid_authentication"
        assert client.login(email=EMAIL.upper()).status == 200
        logout = client.post(
            "/auth/logout", headers={"Cookie": f"orchestwin_refresh={client.refresh_token}"}
        )
        assert (logout.status, logout.headers["content-type"], logout.content) == (
            204,
            "application/json",
            b"",
        )
        assert "content-length" not in logout.headers
        assert client.refresh(client.refresh_token).json() == {
            "detail": "refresh_token_reuse_detected"
        }


def test_expired_access_tokens_answer_401_until_the_renewal() -> None:
    moment = datetime(2026, 9, 29, 9, 12, 3, tzinfo=UTC)
    with FakeStudio(now=lambda: moment) as studio:
        client = signed_in(studio)
        login = client.post("/auth/login", {"email": EMAIL, "password": PASSWORD}).json()
        assert login["expires_at"] == "2026-09-30T09:12:03Z"
        studio.expire_access_tokens()
        denied = client.get("/projects")
        assert (denied.status, denied.json()) == (401, {"detail": "invalid_authentication"})
        renewed = client.refresh(client.refresh_token)
        client.token = renewed.json()["access_token"]
        assert client.get("/projects").json() == []


def test_projects_are_scoped_to_their_owner() -> None:
    with FakeStudio() as studio:
        owner = signed_in(studio)
        base = new_project(owner)
        other = signed_in(studio, OTHER)
        assert other.get(base).json() == {"detail": "project_not_found"}
        assert other.get(base + "/design/current").json() == {
            "detail": {"code": "DESIGN_PACKAGE_NOT_FOUND"}
        }
        assert other.get(base + "/model-usage").status == 404
        assert other.get(base + "/brief-assumptions").json() == []
        assert other.get("/projects").json() == []
        anonymous = Client(studio)
        assert anonymous.get(base).status == 401
        assert anonymous.get("/projects").headers["www-authenticate"] == "Bearer"
        assert owner.get("/projects/not-a-uuid").json()["errors"] == [
            {"loc": ["path", "project_id"], "type": "uuid_parsing"}
        ]
        assert owner.get("/unknown").status == 404
        assert owner.send("DELETE", "/projects").status == 405


def test_the_order_of_the_steps_is_enforced() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        base = new_project(client)
        assert client.post(base + "/team-proposals").json() == {
            "detail": "team_proposal_context_not_found"
        }
        client.post(base + "/brief-versions", {"name": "Calcolo mancia", "description": "Mancia"})
        blocked = client.post(base + "/team-proposals")
        assert (blocked.status, blocked.json()["status"]) == (409, "BRIEF_NOT_APPROVED")
        incomplete = client.post(base + "/gates/project-brief/submit")
        assert incomplete.json()["status"] == "BRIEF_INCOMPLETE"
        assert "problem" in incomplete.json()["missing_fields"]
        unpublished = client.post(base + "/knowledge-packages")
        assert (unpublished.status, unpublished.json()) == (
            409,
            {"detail": {"code": "BRIEF_APPROVAL_REQUIRED"}},
        )
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="team")
        seeded_base = f"/projects/{seeded.id}"
        assert client.post(seeded_base + "/requirements/proposals").json() == {
            "detail": {"code": "USER_MODELING_APPROVAL_REQUIRED"}
        }
        assert client.post(seeded_base + "/design/proposals").json() == {
            "detail": {"code": "REQUIREMENTS_APPROVAL_REQUIRED"}
        }
        partial = client.post(seeded_base + "/knowledge-packages")
        assert partial.status == 201
        assert partial.json()["version"]["progress"] == {
            "approved": ["brief", "team"],
            "pending": "twins",
            "complete": False,
        }
        missing = client.post(seeded_base + "/user-modeling/snapshots/generate")
        assert missing.json() == {"detail": {"code": "PERSONAS_REQUIRED"}}
        regeneration = client.post(seeded_base + "/design/regenerations").json()
        assert (regeneration["status"], regeneration["issue"]) == (
            "REJECTED",
            "REQUIREMENTS_APPROVAL_REQUIRED",
        )


def test_seed_project_completes_the_path_through_the_named_step() -> None:
    expected = {
        "brief": ("TEAM", "APPROVE_TEAM"),
        "team": ("USER_TWINS", "CONFIRM_TWINS"),
        "twins": ("REQUIREMENTS", "APPROVE_REQUIREMENTS"),
        "requirements": ("DESIGN", "APPROVE_DESIGN"),
        "design": ("PACKAGE", "DOWNLOAD_FOLDER"),
    }
    with FakeStudio(twins=3) as studio:
        studio.add_account(EMAIL, PASSWORD)
        for through, progress in expected.items():
            project = studio.seed_project(owner=EMAIL, name=f"Progetto {through}", through=through)
            assert (project.stage, project.next_action) == progress
            assert project.approved(through)
            assert project.current(through) is not None
        design = project.current("design")
        assert design["ready_for_gate"]
        assert len(project.current("twins")["snapshot"]["twin_versions"]) == 3
        assert project.gate("design")["status"] == "APPROVED"
        with pytest.raises(ValueError):
            studio.seed_project(owner=OTHER, name="Nessuno", through="brief")
        with pytest.raises(ValueError):
            studio.seed_project(owner=EMAIL, name="Errato", through="package")


def test_a_request_answers_202_and_the_job_ends_after_the_polls() -> None:
    with FakeStudio(job_polls=2) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="team")
        base = f"/projects/{seeded.id}"
        first = client.post(base + "/user-modeling/personas/proposals", headers=PREFER)
        second = client.post(base + "/user-modeling/personas/proposals", headers=PREFER)
        assert (first.status, second.status) == (202, 202)
        assert first.json()["job_id"] == second.json()["job_id"]
        assert first.json()["operation"] == "PERSONA_PROPOSAL"
        running = client.get(base + "/generation-jobs?status=RUNNING").json()["items"]
        assert [job["job_id"] for job in running] == [first.json()["job_id"]]
        path = f"{base}/generation-jobs/{first.json()['job_id']}"
        statuses = [client.get(path).json()["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        finished = client.get(path).json()
        assert finished["response"]["status_code"] == 200
        assert finished["stage"] is None
        repeated = later(client, base, "/user-modeling/personas/proposals")
        assert repeated == {
            "status_code": 409,
            "body": {"detail": {"code": "PERSONAS_ALREADY_EXIST"}},
        }
        assert client.get(base + "/generation-jobs?status=WRONG").status == 422
        assert seeded.jobs()[0]["status"] == "SUCCEEDED"


def test_without_the_header_a_generation_answers_at_once() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="twins")
        base = f"/projects/{seeded.id}"
        reply = client.post(base + "/requirements/proposals")
        assert (reply.status, reply.json()["status"]) == (201, "CREATED")
        assert client.get(base + "/generation-jobs").json() == {"items": []}
        job = client.post(
            base + "/requirements/change-requests", {"request": "Aggiungi il bis"}, headers=PREFER
        )
        finished, polls = follow(client, f"{base}/generation-jobs/{job.json()['job_id']}")
        assert polls == 1
        assert finished["response"]["body"]["diff"]["status"] == "PROPOSED"


def test_fail_next_answers_the_given_status_and_body() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="twins")
        base = f"/projects/{seeded.id}"
        timeout = {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}}
        studio.fail_next(
            "POST",
            "/projects/{project_id}/requirements/proposals",
            status=503,
            body=timeout,
            times=2,
        )
        studio.fail_next(
            "GET",
            "/projects",
            status=429,
            body={"detail": "slow down"},
            headers={"Retry-After": "5"},
        )
        studio.fail_next("GET", "/health", status=500, body=b"Internal Server Error")
        assert client.post(base + "/requirements/proposals").json() == timeout
        assert client.post(base + "/requirements/proposals", headers=PREFER).status == 503
        assert client.post(base + "/requirements/proposals").status == 201
        limited = client.get("/projects")
        assert (limited.status, limited.headers["retry-after"]) == (429, "5")
        broken = client.get("/health")
        assert (broken.status, broken.content) == (500, b"Internal Server Error")
        assert client.get("/health").status == 200


def test_fail_job_and_lose_job_shape_the_end_of_a_job() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="requirements")
        base = f"/projects/{seeded.id}"
        studio.fail_job("DESIGN_PROPOSAL", code="TIMEOUT")
        failed = later(client, base, "/design/proposals")
        assert failed == {
            "status_code": 503,
            "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
        }
        assert later(client, base, "/design/proposals")["status_code"] == 201
        current = client.get(base + "/design/current").json()
        alternative = current["package"]["alternatives"][0]["id"]
        body = {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "alternative_id": alternative,
        }
        studio.fail_job("MOCKUP", code="MOCKUP_QUALITY_REJECTED", rejected=True)
        started = client.post(base + "/design/mockups/jobs", body).json()
        rejected, _ = follow(client, f"{base}/design/mockups/jobs/{started['job_id']}")
        assert (rejected["status"], rejected["failure"]["code"]) == (
            "REJECTED",
            "MOCKUP_QUALITY_REJECTED",
        )
        studio.lose_job("MOCKUP")
        lost = client.post(base + "/design/mockups/jobs", body).json()
        missing = client.get(f"{base}/design/mockups/jobs/{lost['job_id']}")
        assert (missing.status, missing.json()) == (
            404,
            {"detail": {"code": "GENERATION_JOB_NOT_FOUND"}},
        )
        assert client.get(f"{base}/generation-jobs/{lost['job_id']}").status == 404
        assert lost["job_id"] not in {
            job["job_id"] for job in client.get(base + "/generation-jobs").json()["items"]
        }
        with pytest.raises(ValueError):
            studio.lose_job("UNKNOWN")


def test_the_budget_ceiling_refuses_generations() -> None:
    with FakeStudio(budget_usd=1.0, spent_usd=1.0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        budget = client.get("/model-runtime/budget").json()
        assert (budget["remaining_total_microusd"], budget["per_generation_microusd"]) == (
            0,
            1_000_000,
        )
        current = client.get(base + "/design/current").json()
        refused = client.post(
            base + "/design/mockups/jobs",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "alternative_id": current["package"]["owner_selected_alternative_id"],
            },
        )
        assert (refused.status, refused.json()) == (
            402,
            {"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}},
        )
        assert client.get(base + "/generation-jobs").json() == {"items": []}
        exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
        assert client.post(base + "/design/regenerations").json() == exceeded
        assert later(client, base, "/design/regenerations") == {
            "status_code": 402,
            "body": exceeded,
        }
        assert client.get(base + "/model-usage").json()["totals"]["cost_microusd"] == 0


def test_a_mockup_that_would_pass_the_ceiling_fails_inside_its_job() -> None:
    with FakeStudio(budget_usd=2.0, spent_usd=1.0, job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        current = client.get(base + "/design/current").json()
        started = client.post(
            base + "/design/mockups/jobs",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "alternative_id": current["package"]["owner_selected_alternative_id"],
            },
        )
        assert started.status == 202
        job, _ = follow(client, f"{base}/design/mockups/jobs/{started.json()['job_id']}")
        assert (job["status"], job["failure"]) == (
            "FAILED",
            {"code": "GENERATION_BUDGET_EXCEEDED", "reasons": []},
        )
        assert studio.spent_microusd == 1_000_000


@pytest.mark.parametrize(
    ("billing", "paid"), [("SUBSCRIPTION", False), ("API", True), ("MIXED", True)]
)
def test_the_budget_can_say_how_the_generations_are_billed(billing: str, paid: bool) -> None:
    with FakeStudio(billing=billing) as studio:
        client = signed_in(studio)
        budget = client.get("/model-runtime/budget").json()
        capabilities = client.get(new_project(client) + "/design/mockups/capabilities").json()

    assert budget["billing"] == billing
    assert budget["total_microusd"] == 60_000_000
    assert capabilities["paid"] is paid


def test_an_older_budget_has_no_billing_and_an_unknown_one_is_refused() -> None:
    with FakeStudio() as studio:
        budget = signed_in(studio).get("/model-runtime/budget").json()

    assert "billing" not in budget
    with pytest.raises(ValueError):
        FakeStudio(billing="FREE")


def test_a_studio_without_a_model_answers_like_the_real_one() -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed_in(studio)
        base = new_project(client)
        assert client.get("/model-runtime/budget").json() == {
            "detail": {"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"}
        }
        assert client.post(base + "/brief-dialogue", {"statement": "Mancia"}).json() == {
            "detail": {"code": "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"}
        }
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="requirements")
        seeded_base = f"/projects/{seeded.id}"
        proposal = client.post(seeded_base + "/design/proposals")
        assert proposal.status == 201
        package = proposal.json()["version"]["package"]
        assert [(item["code"], item["approach"]) for item in package["alternatives"]] == [
            ("DES-001", "GUIDED_WORKFLOW"),
            ("DES-002", "DASHBOARD_FIRST"),
            ("DES-003", "TASK_FOCUSED"),
        ]
        assert package["recommended_alternative_id"] == package["alternatives"][0]["id"]
        twins = len(package["grounding"]["user_twin_references"])
        assert len(package["critiques"]) == 3 * twins
        assert {(item["verdict"], item["quote"]) for item in package["critiques"]} == {(None, None)}
        capabilities = client.get(seeded_base + "/design/mockups/capabilities").json()
        assert capabilities == {
            "generated_mockups": False,
            "iterations": False,
            "model": None,
            "paid": True,
            "static_check": False,
        }
        current = client.get(seeded_base + "/design/current").json()
        chosen = package["recommended_alternative_id"]
        body = {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "alternative_id": chosen,
        }
        declarative = client.post(seeded_base + "/design/mockups", body)
        assert (declarative.status, declarative.json()) == (
            503,
            {"detail": {"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"}},
        )
        generated = client.post(seeded_base + "/design/mockups/jobs", body)
        assert generated.json() == {"detail": {"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"}}
        latest = client.get(f"{seeded_base}/design/mockups?alternative_id={chosen}")
        assert (latest.status, latest.content) == (200, b"null")
        evaluation = {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
        }
        refused = client.post(seeded_base + "/design/evaluations", evaluation)
        assert (refused.status, refused.json()) == (
            503,
            {"detail": {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"}},
        )
        started = client.post(seeded_base + "/design/evaluations", evaluation, headers=PREFER)
        assert started.status == 202
        job, _ = follow(client, f"{seeded_base}/generation-jobs/{started.json()['job_id']}")
        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 503, "body": {"detail": {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"}}},
        )
        reviewer = client.post(
            seeded_base + "/design/evaluations", {**evaluation, "mode": "TWIN_REVIEW"}
        )
        assert reviewer.json() == {"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}}
        assert client.get(seeded_base + "/design/evaluations").json() == []
        twin = current["package"]["grounding"]["user_twin_references"][0]["twin_id"]
        chat = client.post(
            f"{seeded_base}/user-twins/{twin}/conversation/turns",
            {"question": "Ciao", "expected_turn_count": 0},
        )
        assert chat.json() == {"detail": {"code": "TWIN_CHAT_MODEL_NOT_CONFIGURED"}}
        assert client.get(seeded_base + "/model-usage").json()["items"] == []
        assert studio.spent_microusd == 0
        designed = studio.seed_project(owner=EMAIL, name="Scelto", through="design")
        chosen_design = designed.current("design")
        assert chosen_design["ready_for_gate"]
        assert chosen_design["package"]["generated_mockup"] is None
        assert (
            chosen_design["package"]["owner_selected_alternative_id"]
            == (chosen_design["package"]["alternatives"][0]["id"])
        )
        assert studio.errors == []


def test_the_mockup_routes_of_a_hosted_studio_answer_like_the_real_ones() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        current = client.get(base + "/design/current").json()
        chosen = current["package"]["owner_selected_alternative_id"]
        body = {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "alternative_id": chosen,
        }
        assert client.post(base + "/design/mockups", body).json() == {
            "detail": {"code": "GENERATED_MOCKUP_PATH_ACTIVE"}
        }
        stale = client.post(base + "/design/mockups", {**body, "design_content_hash": "0" * 64})
        assert (stale.status, stale.json()) == (409, {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}})
        unknown = client.post(base + "/design/mockups", {**body, "alternative_id": current["id"]})
        assert (unknown.status, unknown.json()) == (
            422,
            {"detail": {"code": "DESIGN_ALTERNATIVE_NOT_FOUND"}},
        )
        latest = client.get(f"{base}/design/mockups?alternative_id={chosen}").json()
        assert latest["status"] == "MOCKUP_GENERATED"
        assert latest["package"] == current["package"]
        other = next(
            item["id"] for item in current["package"]["alternatives"] if item["id"] != chosen
        )
        assert client.get(f"{base}/design/mockups?alternative_id={other}").content == b"null"
        missing = client.get(base + "/design/mockups")
        assert missing.json()["errors"] == [{"loc": ["query", "alternative_id"], "type": "missing"}]
        stranger = signed_in(studio, OTHER)
        assert stranger.get(f"{base}/design/mockups?alternative_id={chosen}").json() == {
            "detail": {"code": "DESIGN_PACKAGE_NOT_FOUND"}
        }
        static = client.post(
            base + "/design/evaluations",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "mode": "STATIC_CHECK",
            },
        )
        assert static.json() == {"detail": {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"}}
        capabilities = client.get(base + "/design/mockups/capabilities").json()
        assert (capabilities["generated_mockups"], capabilities["static_check"]) == (True, False)


@pytest.mark.parametrize("hosted", [True, False])
def test_the_team_follows_the_real_rules(hosted: bool) -> None:
    with FakeStudio(hosted=hosted, job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="brief")
        base = f"/projects/{seeded.id}"
        created = client.post(base + "/team-proposals")
        assert created.status == 201
        team = created.json()["version"]
        brief = seeded.brief
        assert brief is not None
        rules = determine_team_constraints(project_mode=ProjectMode(seeded.mode), brief=brief.brief)
        assert team["role_constraints"] == rules.to_snapshot()["role_constraints"]
        assert team["constraints_content_hash"] == rules.content_hash
        assert team["constraint_issues"] == []
        mandatory = [agent.value for agent in rules.mandatory_agent_ids]
        deterministic = {
            member["agent_id"]: member
            for member in team["members"]
            if member["source"] == "DETERMINISTIC_MANDATORY"
        }
        assert list(deterministic) == mandatory
        for constraint in team["role_constraints"]:
            if constraint["kind"] == "MANDATORY":
                member = deterministic[constraint["agent_id"]]
                assert [item["code"] for item in member["justifications"]] == [
                    item["code"] for item in constraint["reasons"]
                ]
        suggested = [
            (member["agent_id"], member["justifications"][0]["code"])
            for member in team["members"]
            if member["source"] == "PROPOSER_SUGGESTED"
        ]
        optional = {agent.value for agent in rules.optional_agent_ids}
        expected = [("FRONTEND_ENGINEER", "MODEL_RECOMMENDATION")]
        assert suggested == (expected if hosted and "FRONTEND_ENGINEER" in optional else [])
        assert team["provider_kind"] == ("MODEL_ADAPTER" if hosted else "FAKE_DETERMINISTIC")
        assert "UX_UI_DESIGNER" in team["selected_agent_ids"]
        assert team["perspectives"] == [
            view.to_snapshot() for view in perspective_views(rules, team["selected_agent_ids"])
        ]
        assert client.get(base + "/team-proposals/current").json() == team


CONTESTED_BRIEF = {
    "name": "Archivio",
    "description": "Una app con database ma senza backend.",
    "problem": "Le ricette sono sparse.",
    "goals": ["Ritrovare una ricetta"],
    "target_users": ["Cuochi"],
    "functional_requirements": ["Cercare una ricetta"],
    "technical_constraints": ["No integrations."],
    "unknown_fields": [
        "domain",
        "temporal_constraints",
        "budget",
        "non_functional_requirements",
        "risks",
        "stakeholders",
        "available_artifacts",
        "definition_of_done",
    ],
}


def aspect(team: Mapping[str, object], key: str) -> dict:
    engineering = next(
        item for item in team["perspectives"] if item["key"] == "SOFTWARE_ENGINEERING"
    )
    return next(item for item in engineering["aspects"] if item["key"] == key)


@pytest.mark.parametrize("hosted", [True, False])
def test_a_contradiction_no_longer_blocks_the_team(hosted: bool) -> None:
    with FakeStudio(hosted=hosted, job_polls=0) as studio:
        client = signed_in(studio)
        base = new_project(client)
        assert client.post(base + "/brief-versions", CONTESTED_BRIEF).status == 201
        approve(
            client, base + "/gates/project-brief/submit", base + "/gates/project-brief/decisions"
        )
        project = studio.project(base.rsplit("/", 1)[1])
        brief = project.brief
        assert brief is not None
        rules = determine_team_constraints(
            project_mode=ProjectMode(project.mode), brief=brief.brief
        )
        assert [issue.agent_id.value for issue in rules.issues] == ["BACKEND_ENGINEER"]

        created = client.post(base + "/team-proposals")
        body = created.json()
        team = body["version"]
        assert (created.status, body["status"]) == (201, "CREATED")
        assert body["issues"] == team["constraint_issues"]
        assert [item["agent_id"] for item in body["issues"]] == ["BACKEND_ENGINEER"]
        assert body["issues"][0]["code"] == "CONTRADICTORY_ROLE_SIGNALS"
        assert "BACKEND_ENGINEER" not in team["selected_agent_ids"]
        assert team["perspectives"] == [
            view.to_snapshot() for view in perspective_views(rules, team["selected_agent_ids"])
        ]
        services = aspect(team, "SERVICES")
        assert (services["standing"], services["applied"], services["editable"]) == (
            "CONTESTED",
            False,
            True,
        )
        assert services["requested"] == {"fields": ["description"], "terms": ["database"]}
        assert services["excluded"] == {"fields": ["description"], "terms": ["senza backend"]}
        integrations = aspect(team, "INTEGRATIONS")
        assert (integrations["standing"], integrations["editable"]) == ("EXCLUDED", False)
        constraint = next(
            item for item in team["role_constraints"] if item["agent_id"] == "BACKEND_ENGINEER"
        )
        assert (constraint["kind"], constraint["owner_editable"]) == ("CONFLICT", True)
        assert len(client.get(base + "/model-usage").json()["items"]) == (1 if hosted else 0)

        again = client.post(base + "/team-proposals")
        assert (again.status, again.json()["status"], again.json()["issues"]) == (
            200,
            "UNCHANGED",
            body["issues"],
        )

        contested = [*team["selected_agent_ids"], "BACKEND_ENGINEER"]
        added = client.send(
            "PATCH", base + "/team-proposals/current", {"selected_agent_ids": contested}
        )
        edited = added.json()["version"]
        assert (added.status, added.json()["status"]) == (201, "UPDATED")
        member = next(item for item in edited["members"] if item["agent_id"] == "BACKEND_ENGINEER")
        assert member["source"] == "OWNER_ADDED"
        assert [item["statement"] for item in member["justifications"]] == ["Chosen by the owner."]
        assert aspect(edited, "SERVICES")["applied"] is True
        assert edited["constraint_issues"] == body["issues"]

        refused = client.send(
            "PATCH",
            base + "/team-proposals/current",
            {"selected_agent_ids": [*contested, "INTEGRATION_ENGINEER"]},
        )
        assert (refused.status, refused.json()["status"], refused.json()["issues"]) == (
            422,
            "REJECTED",
            [{"code": "AGENT_NOT_SELECTABLE", "agent_id": "INTEGRATION_ENGINEER"}],
        )

        removed = client.send(
            "PATCH",
            base + "/team-proposals/current",
            {"selected_agent_ids": team["selected_agent_ids"]},
        )
        assert (removed.status, aspect(removed.json()["version"], "SERVICES")["applied"]) == (
            201,
            False,
        )
        assert studio.errors == []


def test_an_added_agent_keeps_the_rationale_of_the_owner() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="brief")
        base = f"/projects/{seeded.id}"
        team = client.post(base + "/team-proposals").json()["version"]
        selected = [*team["selected_agent_ids"], "SECURITY_REVIEWER", "MOBILE_ENGINEER"]
        reply = client.send(
            "PATCH",
            base + "/team-proposals/current",
            {
                "selected_agent_ids": selected,
                "owner_rationales": [
                    {"agent_id": "SECURITY_REVIEWER", "statement": "  Dati   dei clienti. "}
                ],
            },
        )
        edited = reply.json()["version"]
        statements = {
            member["agent_id"]: member["justifications"][0]["statement"]
            for member in edited["members"]
            if member["source"] == "OWNER_ADDED"
        }
        assert reply.status == 201
        assert statements == {
            "MOBILE_ENGINEER": "Chosen by the owner.",
            "SECURITY_REVIEWER": "Dati dei clienti.",
        }
        security = next(item for item in edited["perspectives"] if item["key"] == "SECURITY")
        assert (security["standing"], security["applied"], security["agent_id"]) == (
            "OPTIONAL",
            True,
            "SECURITY_REVIEWER",
        )
        history = client.get(base + "/team-proposals").json()
        assert all(
            [item["key"] for item in version["perspectives"]]
            == ["UX", "ACCESSIBILITY", "SOFTWARE_ENGINEERING", "PRODUCT", "SECURITY"]
            for version in history
        )
        unused = client.send(
            "PATCH",
            base + "/team-proposals/current",
            {
                "selected_agent_ids": selected,
                "owner_rationales": [{"agent_id": "FRONTEND_ENGINEER", "statement": "Web."}],
            },
        )
        assert (unused.status, unused.json()["issues"]) == (
            422,
            [{"code": "UNUSED_RATIONALE", "agent_id": "FRONTEND_ENGINEER"}],
        )
        assert studio.errors == []


@pytest.mark.parametrize("hosted", [True, False])
def test_a_team_without_the_designer_gets_no_design(hosted: bool) -> None:
    with FakeStudio(hosted=hosted, job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(
            owner=EMAIL,
            name="Squadra vecchia",
            through="requirements",
            team_without=["UX_UI_DESIGNER"],
        )
        team = seeded.current("team")
        assert "UX_UI_DESIGNER" not in team["selected_agent_ids"]
        designer = next(
            item for item in team["role_constraints"] if item["agent_id"] == "UX_UI_DESIGNER"
        )
        assert (designer["kind"], designer["reasons"]) == ("OPTIONAL", [])
        base = f"/projects/{seeded.id}"
        refused = client.post(base + "/design/proposals")
        if hosted:
            expected = (
                502,
                {"detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}},
            )
        else:
            expected = (
                409,
                {"detail": {"code": "PROPOSAL_REJECTED", "proposal_issue": "UX_DESIGNER_REQUIRED"}},
            )
        assert (refused.status, refused.json()) == expected
        assert later(client, base, "/design/proposals") == {
            "status_code": expected[0],
            "body": expected[1],
        }
        assert client.get(base + "/design").json() == []
        assert studio.spent_microusd == 0
        with pytest.raises(ValueError):
            studio.seed_project(
                owner=EMAIL, name="Mai", through="design", team_without=["UX_UI_DESIGNER"]
            )
        with pytest.raises(ValueError):
            studio.seed_project(
                owner=EMAIL, name="Mai", through="brief", team_without=["QA_TEST_ENGINEER"]
            )
        with pytest.raises(ValueError):
            studio.seed_project(owner=EMAIL, name="Mai", through="team", team_without=["NOBODY"])


def test_add_account_refuses_what_the_real_registration_refuses() -> None:
    with FakeStudio() as studio:
        for address in ("owner@example.test", "person@localhost", "not-an-address", "a@"):
            with pytest.raises(ValueError, match=r"refuses|characters"):
                studio.add_account(address, PASSWORD)
        with pytest.raises(ValueError, match="special-use or reserved"):
            studio.add_account("owner@example.test", PASSWORD)
        studio.add_account(" Owner@Example.com ", PASSWORD)
        with pytest.raises(ValueError, match="already exists"):
            studio.add_account("owner@example.com", PASSWORD)
        assert Client(studio).login(email="OWNER@example.com").status == 200
        assert Client(studio).login(email="owner@example.test").status == 401


def test_the_registration_opens_a_session_like_the_login() -> None:
    with FakeStudio() as studio:
        client = Client(studio)
        created = client.post(
            "/auth/register", {"email": " New@Example.com ", "password": PASSWORD}
        )
        assert created.status == 201
        body = created.json()
        assert list(body) == ["access_token", "token_type", "expires_at", "user"]
        assert (body["token_type"], body["user"]["email"]) == ("bearer", "new@example.com")
        assert "Path=/api/v1/auth" in created.headers["set-cookie"]
        assert "HttpOnly" in created.headers["set-cookie"]
        client.token = str(body["access_token"])
        assert client.get("/auth/me").json() == body["user"]
        assert client.refresh(_cookie(created)).status == 200
        assert Client(studio).login(email="NEW@example.com").status == 200
        again = Client(studio).post(
            "/auth/register", {"email": "new@example.com", "password": PASSWORD}
        )
        assert (again.status, again.json()) == (409, {"detail": "email_already_registered"})
        with pytest.raises(ValueError, match="already exists"):
            studio.add_account("new@example.com", PASSWORD)
        studio.add_account(EMAIL, PASSWORD)
        taken = Client(studio).post(
            "/auth/register", {"email": EMAIL.upper(), "password": PASSWORD}
        )
        assert (taken.status, taken.json()) == (409, {"detail": "email_already_registered"})
        assert studio.errors == []


@pytest.mark.parametrize(
    ("email", "password", "detail"),
    [
        ("probe@example.test", PASSWORD, "invalid_registration"),
        ("person@localhost", PASSWORD, "invalid_registration"),
        ("probe@example.test", "abcdefgh!", "invalid_registration"),
        ("new@example.com", "abcdefg1!", "password_missing_uppercase"),
        ("new@example.com", "Abcdefg12", "password_missing_special"),
    ],
)
def test_the_registration_refuses_what_the_real_one_refuses(
    email: str, password: str, detail: str
) -> None:
    with FakeStudio() as studio:
        client = Client(studio)
        refused = client.post("/auth/register", {"email": email, "password": password})
        assert (refused.status, refused.json()) == (422, {"detail": detail})
        assert "set-cookie" not in refused.headers
        assert client.login(email=email, password=password).status == 401


@pytest.mark.parametrize(
    ("body", "detail", "error"),
    [
        (
            {"email": EMAIL, "password": "Abcde1!"},
            "password_too_short",
            (["body", "password"], "string_too_short"),
        ),
        (
            {"email": EMAIL, "password": "Ab!" * 342},
            "password_too_long",
            (["body", "password"], "string_too_long"),
        ),
        ({"email": EMAIL}, "invalid_registration", (["body", "password"], "missing")),
        (
            {"email": "a@", "password": PASSWORD},
            "invalid_registration",
            (["body", "email"], "string_too_short"),
        ),
        (
            {"email": EMAIL, "password": PASSWORD, "role": "owner"},
            "invalid_registration",
            (["body", "role"], "extra_forbidden"),
        ),
        (None, "invalid_registration", (["body"], "missing")),
    ],
)
def test_invalid_registration_bodies_carry_the_codes_of_the_real_api(
    body: object, detail: str, error: tuple[list[object], str]
) -> None:
    with FakeStudio() as studio:
        reply = Client(studio).post("/auth/register", body)
        location, kind = error
        assert (reply.status, reply.json()) == (
            422,
            {"detail": detail, "errors": [{"loc": location, "type": kind}]},
        )
        assert studio.errors == []


def test_the_model_runtime_readiness_answers_like_the_real_route() -> None:
    with FakeStudio(hosted=False) as studio:
        client = signed_in(studio)
        missing = client.get("/model-runtime/readiness")
        assert (missing.status, missing.json()) == (
            503,
            {
                "mode": "DEVELOPMENT_FIXTURES",
                "ready": False,
                "code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED",
            },
        )
        anonymous = Client(studio).get("/model-runtime/readiness")
        assert (anonymous.status, anonymous.headers["www-authenticate"]) == (401, "Bearer")
    with FakeStudio(budget_usd=2.0, spent_usd=0.5) as studio:
        client = signed_in(studio)
        ready = client.get("/model-runtime/readiness")
        assert ready.status == 200
        report = ready.json()
        assert list(report) == [
            "mode",
            "manifest_schema_version",
            "ready",
            "components",
            "proposal_tasks",
            "routes",
            "budget",
            "evaluator_configured",
            "generation_performed",
            "semantic_quality_qualified",
            "formal_campaign_ready",
        ]
        assert (report["mode"], report["manifest_schema_version"], report["ready"]) == (
            "REAL_REQUIRED",
            2,
            True,
        )
        assert list(report["components"]) == ["provider:anthropic", "database"]
        assert report["proposal_tasks"] == sorted(TASKS)
        assert list(report["routes"]["tasks"]) == sorted(TASKS)
        assert report["budget"] == client.get("/model-runtime/budget").json()
        assert report["budget"]["remaining_total_microusd"] == 1_500_000
    with FakeStudio(budget_usd=None) as studio:
        assert signed_in(studio).get("/model-runtime/readiness").json()["budget"] is None
        assert studio.errors == []


def test_the_dialogue_can_ask_after_the_essential_fields() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        studio.ask_after_essentials("non_functional_requirements")
        base = new_project(client)
        statement = {"statement": "Una pagina per la mancia."}
        state = client.post(base + "/brief-dialogue", statement).json()
        while state["snapshot"]["turns"][-1]["field"] in ANSWERS:
            turns = state["snapshot"]["turns"]
            body = {**ANSWERS[turns[-1]["field"]], "expected_turn_count": len(turns)}
            state = client.post(base + "/brief-dialogue/answers", body).json()
        pending = state["snapshot"]["turns"][-1]
        assert (state["status"], pending["field"], pending["answer"]) == (
            "BRIEF_QUESTION_ASKED",
            "non_functional_requirements",
            None,
        )
        assert pending["question"] == (
            "Quali qualità deve avere il prodotto, per esempio velocità o sicurezza?"
        )
        assert state["progress"]["open_essential_fields"] == []
        answered = client.post(
            base + "/brief-dialogue/answers",
            {
                "kind": "ITEM_LIST",
                "items": ["Si apre in due secondi"],
                "expected_turn_count": len(state["snapshot"]["turns"]),
            },
        ).json()
        assert answered["status"] == "BRIEF_DIALOGUE_READY"
        synthesis = client.post(
            base + "/brief-dialogue/synthesis",
            {"expected_turn_count": len(answered["snapshot"]["turns"])},
        ).json()
        assert synthesis["brief_version"]["brief"]["non_functional_requirements"] == [
            "Si apre in due secondi"
        ]
        for wrong in ("problem", "name", "unknown"):
            with pytest.raises(ValueError):
                studio.ask_after_essentials(wrong)
        with pytest.raises(ValueError):
            studio.ask_after_essentials()


def test_a_second_knowledge_version_without_a_changed_step() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        assert client.post(base + "/knowledge-packages").status == 201
        assert client.post(base + "/knowledge-packages").status == 200
        seeded.mark_knowledge_changed()
        second = client.post(base + "/knowledge-packages")
        assert (second.status, second.json()["version"]["version_number"]) == (201, 2)
        seeded.fingerprint = None
        third = client.post(base + "/knowledge-packages")
        assert (third.status, third.json()["version"]["version_number"]) == (201, 3)
        assert [item["version_number"] for item in seeded.knowledge_versions()] == [1, 2, 3]


@pytest.mark.parametrize("through", STEPS)
def test_a_folder_is_published_from_the_brief_on(through: str) -> None:
    present = list(STEPS[: STEPS.index(through) + 1])
    complete = through == "design"
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through=through)
        base = f"/projects/{seeded.id}"
        published = client.post(base + "/knowledge-packages")
        assert published.status == 201
        version = published.json()["version"]
        assert version["schema_version"] == 3
        assert [item["stage"] for item in version["stages"]] == present
        assert version["progress"] == {
            "approved": present,
            "pending": None if complete else STEPS[len(present)],
            "complete": complete,
        }
        assert version["state"] == {
            "changes": 0,
            "pending_changes": 0,
            "stale_reviews": 0,
            "aligned_commit": None,
            "open_tasks": 0,
        }
        assert version["feedback"]["change_reviews"] == 0
        entries = set(version["entries"])
        assert {"state/state.json", "state/state.md", "twins/feedback/changes.json"} <= entries
        assert ("design/design.json" in entries) is complete
        assert ("team/team.json" in entries) is (through != "brief")
        twins = "twins" in present
        assert ("twins/feedback/learned.json" in entries) is twins
        assert version["feedback"].get("learned_observations") == (0 if twins else None)
        assert client.post(base + "/knowledge-packages").status == 200
        archive = client.get(base + "/knowledge-packages/1/archive")
        verified = read_verified_folder(archive.content)
        assert verified.project_name == "Seme"
        assert set(verified.manifest["stages"]) == set(present)
        assert verified.manifest["progress"] == version["progress"]
        assert studio.errors == []


def test_the_development_state_reaches_the_published_folder() -> None:
    commit = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
    change = {
        "commit": commit,
        "parent": None,
        "committed_at": "2026-09-29T10:00:00+00:00",
        "author": "Test Author",
        "message": "Correggere il drift del risultato",
        "files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 4, "removed": 1}],
        "diff": "+// REQ-002\n",
    }
    steps = (
        ("/code-changes", change),
        (f"/code-changes/{commit}/reviews", {"locale": "it-IT"}),
        (
            f"/code-changes/{commit}/decision",
            {"kind": "CODE_TASKS", "tasks": ["Coprire REQ-002 con un test."]},
        ),
        (f"/code-changes/{commit}/decision", {"kind": "ALIGNED", "note": "Allineato."}),
    )
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        assert client.post(base + "/knowledge-packages").status == 201
        numbers = []
        for path, body in steps:
            assert client.post(base + path, body).status in {200, 201}
            published = client.post(base + "/knowledge-packages")
            assert published.status == 201
            numbers.append(published.json()["version"]["version_number"])
            assert client.post(base + "/knowledge-packages").status == 200
        assert numbers == [2, 3, 4, 5]
        version = published.json()["version"]
        assert version["state"] == {
            "changes": 1,
            "pending_changes": 0,
            "stale_reviews": 0,
            "aligned_commit": commit,
            "open_tasks": 0,
        }
        assert version["feedback"]["change_reviews"] == 1
        archive = client.get(base + "/knowledge-packages/5/archive")
        assert read_verified_folder(archive.content).manifest["state"]["aligned_commit"] == commit
        with zipfile.ZipFile(io.BytesIO(archive.content)) as folder:
            state = json.loads(folder.read("state/state.json").decode("utf-8"))
            reviews = json.loads(folder.read("twins/feedback/changes.json").decode("utf-8"))
        sources = studio._state_sources(seeded, "design")
        assert state["changes"] == [
            {**change, "review": {**change["review"], "stale": False}} for change in sources.changes
        ]
        assert [change["commit"] for change in state["changes"]] == [
            change["commit"] for change in seeded.changes()
        ]
        assert state["aligned"] == seeded.aligned()
        assert state["tasks"] == seeded.tasks()
        assert [task["status"] for task in state["tasks"]] == ["DONE"]
        assert reviews["runs"] == seeded.change_reviews()
        assert reviews["runs"][0]["alignment"]["status"] == "CODE_DRIFT"
        assert studio.errors == []


def test_a_partial_folder_cannot_be_imported() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="brief")
        base = f"/projects/{seeded.id}"
        assert client.post(base + "/knowledge-packages").status == 201
        published = client.get(base + "/knowledge-packages/1/archive").content
        for content, pending in (
            (published, "team"),
            (partial_archive(through="twins"), "requirements"),
        ):
            refused = client.post(
                "/project-imports",
                content=multipart({}, {"archive": ("folder.zip", "application/zip", content)}),
                headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
            )
            assert (refused.status, refused.json()) == (
                422,
                {"detail": {"code": "FOLDER_INCOMPLETE", "location": pending}},
            )
        assert len(client.get("/projects").json()) == 1
        assert studio.errors == []


def test_a_hosted_studio_without_a_budget_charges_without_a_ceiling() -> None:
    with FakeStudio(budget_usd=None, language="en", job_polls=0) as studio:
        client = signed_in(studio)
        base = new_project(client, "Tip calculator")
        assert client.get("/model-runtime/budget").json() == {
            "detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}
        }
        started = client.post(base + "/brief-dialogue", {"statement": "A tip calculator."}).json()
        assert (
            started["snapshot"]["turns"][0]["question"] == "Which problem does the project solve?"
        )
        assert studio.spent_microusd == COSTS["BRIEF_QUESTION"]
        seeded = studio.seed_project(owner=EMAIL, name="Seed", through="twins")
        personas = client.get(f"/projects/{seeded.id}/user-modeling/personas").json()
        assert {item["profile"]["name"] for item in personas} == {
            "Evening shift waiter",
            "Pizzeria owner",
        }
        identifiers = [item["persona_id"] for item in personas]
        assert identifiers == sorted(identifiers)


def test_invalid_bodies_answer_422_like_the_real_api() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        missing = client.post("/projects", {"display_name": "Calcolo mancia"})
        assert missing.json() == {
            "detail": "invalid_request",
            "errors": [{"loc": ["body", "mode"], "type": "missing"}],
        }
        extra = client.post(
            "/projects", {"display_name": "A", "mode": "GREENFIELD_GENERATION", "x": 1}
        )
        assert extra.json()["errors"] == [{"loc": ["body", "x"], "type": "extra_forbidden"}]
        empty = client.post("/projects")
        assert empty.json()["errors"] == [{"loc": ["body"], "type": "missing"}]
        broken = client.send(
            "POST", "/projects", content=b"{", headers={"Content-Type": "application/json"}
        )
        assert broken.json()["errors"] == [{"loc": ["body", 0], "type": "json_invalid"}]
        text = client.send(
            "POST", "/projects", content=b"{}", headers={"Content-Type": "text/plain"}
        )
        assert text.status == 422


def test_requests_are_recorded_with_lower_case_headers() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        client.get("/projects?limit=3")
        recorded = studio.requests[-1]
        assert (recorded.method, recorded.path, recorded.query) == (
            "GET",
            "/api/v1/projects",
            "limit=3",
        )
        assert recorded.headers["authorization"] == f"Bearer {client.token}"
        assert (
            studio.requests[0].body == json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
        )


def test_the_archive_of_the_support_folder_can_be_imported() -> None:
    with FakeStudio() as studio:
        client = signed_in(studio)
        content = valid_archive(project_name="Lista della spesa")
        imported = client.post(
            "/project-imports",
            content=multipart({}, {"archive": ("folder.zip", "application/zip", content)}),
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        assert imported.json()["project"]["display_name"] == "Lista della spesa"
        broken = client.post(
            "/project-imports",
            content=multipart({}, {"archive": ("folder.zip", "application/zip", b"not a zip")}),
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        assert (broken.status, broken.json()["detail"]["code"]) == (422, "FOLDER_ARCHIVE_INVALID")
        absent = client.post(
            "/project-imports",
            content=multipart({"display_name": "Senza cartella"}, {}),
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        assert absent.json()["errors"] == [{"loc": ["body", "archive"], "type": "missing"}]


def test_the_server_closes_its_socket_and_joins_its_threads(
    capfd: pytest.CaptureFixture[str],
) -> None:
    before = {thread.ident for thread in threading.enumerate()}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with FakeStudio() as studio:
            assert studio.running
            client = Client(studio)
            for _ in range(5):
                assert client.get("/health").status == 200
            assert client.get("/missing").status == 404
        gc.collect()
    assert not studio.running
    assert {thread.ident for thread in threading.enumerate()} <= before
    assert [item for item in caught if issubclass(item.category, ResourceWarning)] == []
    assert capfd.readouterr() == ("", "")
    assert studio.errors == []
    with pytest.raises(RuntimeError):
        _ = studio.address


def test_two_instances_share_nothing() -> None:
    with FakeStudio() as first, FakeStudio() as second:
        first.add_account(EMAIL, PASSWORD)
        assert first.address != second.address
        assert Client(second).login().status == 401
        project = first.seed_project(owner=EMAIL, name="Solo qui", through="brief")
        with pytest.raises(KeyError):
            second.project(project.id)


def test_the_clock_is_injected_and_never_goes_back() -> None:
    moments = iter(
        [datetime(2026, 9, 29, 12, 0, tzinfo=UTC), datetime(2026, 9, 29, 11, 0, tzinfo=UTC)]
    )
    start = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with FakeStudio(now=lambda: next(moments, start + timedelta(hours=1))) as studio:
        assert studio.now() == start
        assert studio.now() == start
        assert studio.now() == start + timedelta(hours=1)
    earlier = datetime(2026, 1, 5, 7, 30, tzinfo=UTC)
    with FakeStudio(now=lambda: earlier) as studio:
        assert studio.now() == earlier
    with FakeStudio() as studio:
        assert studio.now() + timedelta(seconds=1) == studio.now()


TEST_PAGE = "http://127.0.0.1:41234/"
TEST_SNAPSHOT = {"url": TEST_PAGE, "title": "Seme", "text": "Seme", "elements": []}


def plan_tests(client: Client, base: str) -> dict:
    reply = client.post(
        base + "/test-plans",
        {"application": {"kind": "STATIC", "address": "dist"}, "snapshot": TEST_SNAPSHOT},
    )
    assert reply.status == 201
    return reply.json()["plan"]


def record_tests(client: Client, base: str, plan: dict) -> dict:
    results = [
        {
            "path": path,
            "browser": "chrome",
            "status": "PASSED" if position else "FAILED",
            "seconds": 2.5,
            "steps": [
                {
                    "index": index,
                    "status": "FAILED" if not position and index == len(path["steps"]) else "DONE",
                    "detail": None,
                    "url": TEST_PAGE,
                    "title": "Seme",
                    "screenshot": f"{path['code']}/chrome/{index:02d}.png",
                }
                for index in range(1, len(path["steps"]) + 1)
            ],
            "page_text": "Seme",
        }
        for position, path in enumerate(plan["paths"])
    ]
    reply = client.post(
        base + "/test-runs",
        {
            "plan_id": plan["id"],
            "started_at": "2026-09-29T10:00:00+00:00",
            "finished_at": "2026-09-29T10:01:00+00:00",
            "application": {"kind": "STATIC", "address": "dist"},
            "browsers": [{"name": "chrome", "version": "151.0.7922.76"}],
            "results": results,
            "not_covered": plan["not_covered"],
        },
    )
    assert reply.status == 201
    return reply.json()["run"]


def test_the_acceptance_tests_reach_the_published_folder() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        first = client.post(base + "/knowledge-packages").json()["version"]
        plan = plan_tests(client, base)
        assert client.post(base + "/knowledge-packages").status == 200
        run = record_tests(client, base, plan)
        recorded = client.post(base + "/knowledge-packages")
        assert client.post(base + "/knowledge-packages").status == 200
        reviewed = client.post(f"{base}/test-runs/{run['id']}/reviews", {"locale": "it-IT"})
        published = client.post(base + "/knowledge-packages")
        assert client.post(base + "/knowledge-packages").status == 200
        archive = client.get(base + "/knowledge-packages/3/archive")
        verified = read_verified_folder(archive.content)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as folder:
            document = json.loads(folder.read("twins/feedback/tests.json").decode("utf-8"))

        assert first["feedback"]["test_runs"] == 0
        assert (recorded.status, recorded.json()["version"]["feedback"]["test_runs"]) == (201, 1)
        assert reviewed.status == 201
        version = published.json()["version"]
        assert (published.status, version["version_number"]) == (201, 3)
        assert version["feedback"]["test_runs"] == 1
        assert "twins/feedback/tests.json" in version["entries"]
        assert verified.manifest["feedback"]["tests"] == "twins/feedback/tests.json"
        assert verified.manifest["feedback"]["test_runs"] == 1
        assert (document["kind"], document["schema_version"]) == ("orchestwin.test-reviews", 3)
        assert document["runs"] == seeded.test_runs()
        assert document["runs"][0]["critiques"] == reviewed.json()["review"]["critiques"]
        assert document["runs"][0]["summary"]["failed"] == 1
        assert studio.errors == []


def test_the_published_folder_keeps_the_twenty_newest_runs() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        plan = plan_tests(client, base)
        for _ in range(21):
            record_tests(client, base, plan)

        version = client.post(base + "/knowledge-packages").json()["version"]
        archive = client.get(base + "/knowledge-packages/1/archive")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as folder:
            document = json.loads(folder.read("twins/feedback/tests.json").decode("utf-8"))

        assert len(seeded.test_runs()) == 21
        assert document["runs"] == seeded.test_runs()[:20]
        assert version["feedback"]["test_runs"] == 20
        assert studio.errors == []


def test_the_helpers_of_the_tests_give_copies() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        run = record_tests(client, base, plan_tests(client, base))
        assert client.post(f"{base}/test-runs/{run['id']}/reviews", {}).status == 201

        seeded.seed_tasks()
        seeded.seed_learning(0)
        seeded.seed_change()
        seeded.seed_update(0)

        seeded.test_plans()[0]["paths"].clear()
        seeded.test_runs()[0]["critiques"].clear()
        seeded.test_reviews()[0]["critiques"].clear()
        seeded.plan_requests()[0]["snapshot"]["hidden_text"] = "Cambiato"
        seeded.tasks()[0]["origin"]["kind"] = "OWNER"
        seeded.twin_learning()[0]["observations"].clear()
        seeded.twin_updates()[0]["observations"].clear()
        seeded.earlier_findings()[0]["twins"].clear()

        assert len(seeded.test_plans()[0]["paths"]) == 4
        assert len(seeded.test_runs()[0]["critiques"]) == 2
        assert len(seeded.test_reviews()[0]["critiques"]) == 2
        assert seeded.test_runs()[0]["critiques"] == seeded.test_reviews()[0]["critiques"]
        assert seeded.plan_requests()[0]["snapshot"]["hidden_text"] == ""
        assert seeded.tasks()[0]["origin"]["kind"] == "CODE_CHANGE"
        assert len(seeded.twin_learning()[0]["observations"]) == 2
        assert len(seeded.twin_updates()[0]["observations"]) == 2
        assert len(seeded.earlier_findings()[0]["twins"]) == 2
        assert studio.errors == []


def test_the_plan_requests_keep_the_body_of_every_plan_with_its_defaults() -> None:
    application = {"kind": "STATIC", "address": "dist"}
    hidden = {**TEST_SNAPSHOT, "hidden_text": "  Totale\n per   persona  "}
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        first = plan_tests(client, base)
        refused = client.post(
            base + "/test-plans",
            {"application": application, "snapshot": {**TEST_SNAPSHOT, "hidden_text": None}},
        )
        second = client.post(
            base + "/test-plans",
            {
                "locale": "en-US",
                "application": application,
                "snapshot": hidden,
                "criteria": ["ac-001"],
            },
        )

        assert (refused.status, refused.json()["errors"]) == (
            422,
            [{"loc": ["body", "snapshot", "hidden_text"], "type": "string_type"}],
        )
        assert second.status == 201
        assert seeded.plan_requests() == [
            {
                "locale": "en-US",
                "application": application,
                "snapshot": hidden,
                "criteria": ["AC-001"],
                "earlier": None,
            },
            {
                "locale": "it-IT",
                "application": application,
                "snapshot": {**TEST_SNAPSHOT, "hidden_text": ""},
                "criteria": None,
                "earlier": None,
            },
        ]
        assert [plan["id"] for plan in seeded.test_plans()] == [
            second.json()["plan"]["id"],
            first["id"],
        ]
        assert studio.errors == []


def folder_document(client: Client, base: str, number: int, name: str) -> dict:
    archive = client.get(f"{base}/knowledge-packages/{number}/archive")
    read_verified_folder(archive.content)
    with zipfile.ZipFile(io.BytesIO(archive.content)) as folder:
        return json.loads(folder.read(name).decode("utf-8"))


def test_the_tasks_the_stale_reviews_and_the_learning_reach_the_published_folder() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"

        def publish() -> tuple[int, dict]:
            reply = client.post(base + "/knowledge-packages")
            return reply.status, reply.json()["version"]

        statuses = [publish()[0]]
        change = seeded.seed_change()
        statuses.append(publish()[0])
        seeded.seed_version("design")
        statuses.append(publish()[0])
        created = client.post(
            base + "/code-tasks", {"tasks": [{"text": "Uno.", "source": {"kind": "OWNER"}}]}
        )
        statuses.append(publish()[0])
        client.post(base + "/code-tasks/TSK-001/status", {"status": "DONE"})
        statuses.append(publish()[0])
        entry = seeded.seed_learning(0)
        statuses.append(publish()[0])
        seeded.seed_change()
        statuses.append(publish()[0])
        update = seeded.seed_update(0)
        rejected = client.post(
            f"{base}/twin-updates/{update['id']}/decision", {"decision": "REJECT"}
        )
        status, version = publish()
        statuses.append(status)

        number = version["version_number"]
        state = folder_document(client, base, number, "state/state.json")
        learned = folder_document(client, base, number, "twins/feedback/learned.json")
        manifest = folder_document(client, base, number, "orchestwin.json")
        assert (created.status, rejected.status) == (201, 200)
        assert statuses == [201] * 7 + [200]
        assert number == 7
        assert version["state"]["stale_reviews"] == manifest["state"]["stale_reviews"] == 1
        assert version["feedback"]["learned_observations"] == 2
        assert [item["review"]["stale"] for item in state["changes"]] == [False, True]
        assert state["changes"][1]["commit"] == change["commit"]
        assert state["changes"][1]["review"]["reference"] == change["review"]["reference"]
        assert state["tasks"] == seeded.tasks()
        assert [task["status"] for task in state["tasks"]] == ["DONE"]
        assert [twin["label"] for twin in learned["twins"]] == ["1.1", "1.0"]
        assert learned["twins"][0]["observations"] == entry["observations"]
        assert learned["twins"][0]["twin_id"] == manifest["twins"][0]["twin_id"]
        assert learned["twins"][0]["twin_id"] != entry["twin_id"]
        assert studio.errors == []


def test_the_state_sources_follow_the_frame_of_the_published_folder() -> None:
    with FakeStudio(twins=1, job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        older = seeded.seed_change()
        seeded.seed_version("design")
        newer = seeded.seed_change()
        entry = seeded.seed_learning(0, ["Chi paga legge da lontano."])

        complete = studio._state_sources(seeded, "design")
        partial = studio._state_sources(seeded, "requirements")

        frame = folder_frame("design")
        reviews = {item["commit"]: item["review"] for item in complete.changes}
        assert reviews[newer["commit"]]["reference"] == frame["reference"]
        assert reviews[older["commit"]]["reference"] == older["review"]["reference"]
        assert all("stale" not in review for review in reviews.values())
        assert [item["review"]["reference"] for item in partial.changes] == [
            newer["review"]["reference"],
            older["review"]["reference"],
        ]
        (learning,) = complete.learning
        twin = frame["twins"][0]
        assert learning == {
            **entry,
            "twin_id": twin["twin_id"],
            "twin_name": twin["twin_name"],
            "profile_version_number": twin["profile_version_number"],
            "label": f"{twin['profile_version_number']}.1",
        }
        assert partial.learning == complete.learning
        assert studio._state_sources(seeded, "team").learning == ()
        assert complete.tasks == tuple(seeded.tasks())
        assert studio.errors == []


def test_the_seeding_helpers_give_a_project_in_the_named_state() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        seeded = studio.seed_project(owner=EMAIL, name="Seed", through="design")
        early = studio.seed_project(owner=EMAIL, name="Early", through="team")

        first = seeded.seed_change()
        second = seeded.seed_change("Show the shares", commit="ABCDEF1234567")
        quiet = seeded.seed_change(reviewed=False)
        run = seeded.seed_test_run()
        passed = seeded.seed_test_run(failed=False, reviewed=False)
        design = seeded.seed_version("design")
        tasks = seeded.seed_tasks()
        done = seeded.set_task_status("TSK-002", "DONE", "Done.")
        added = seeded.add_tasks([{"text": "Write the manual.", "source": {"kind": "OWNER"}}])
        learned = seeded.seed_learning(0)
        written = seeded.seed_learning(1, ["The owner reads the bill at the till."], source="OWNER")
        seeded.seed_change()
        pending = seeded.seed_update(
            0, [{"statement": "They pay in cash.", "contradicts_profile": "It pays by card."}]
        )

        assert (first["commit"], len(first["commit"])) != (second["commit"], 40)
        assert (first["message"], first["parent"], second["parent"]) == (
            "Add the split of the bill",
            None,
            first["commit"],
        )
        assert second["commit"] == "abcdef1234567"
        assert first["review"]["stale"] is False
        assert quiet["review"] is None
        assert run["criteria"][0]["status"] == "FAILED"
        assert len(run["critiques"]) == 2
        assert {item["status"] for item in passed["criteria"]} == {"PASSED"}
        assert passed["critiques"] == []
        assert design["version_number"] == 3
        assert seeded.approved("design")
        assert [
            (change["commit"], change["review"]["stale"])
            for change in seeded.changes()
            if change["review"]
        ][1:] == [(second["commit"], True), (first["commit"], True)]
        assert [task["origin"]["kind"] for task in tasks] == [
            "CODE_CHANGE",
            "CODE_CHANGE",
            "TEST_RUN",
            "OWNER",
        ]
        assert tasks[0]["origin"]["twin_id"] is None
        assert tasks[0]["text"] == "Cover the tip calculation with an automated test."
        assert tasks[3]["text"] == "Write the help text of the page."
        assert tasks[2]["about"]["criteria"] == ["AC-001"]
        assert (done["status"], done["note"]) == ("DONE", "Done.")
        assert [task["code"] for task in added] == ["TSK-005"]
        assert (learned["label"], len(learned["observations"])) == ("1.1", 2)
        assert {item["source"] for item in learned["observations"]} == {"TWIN_CRITIQUE"}
        assert seeded.twin_updates()[1]["status"] == "APPROVED"
        assert (written["label"], written["observations"][0]["basis"]) == ("1.1", None)
        assert pending["status"] == "PROPOSED"
        assert pending["observations"][0]["contradicts_profile"] == "It pays by card."
        assert pending["material"] == {"changes": 1, "tests": 0}
        assert studio.spent_microusd == 0
        failures = (
            lambda: seeded.seed_change(commit=first["commit"]),
            lambda: seeded.seed_change(commit="xyz"),
            lambda: early.seed_change(),
            lambda: early.seed_test_run(),
            lambda: early.seed_learning(0),
            lambda: seeded.seed_version("brief"),
            lambda: seeded.set_task_status("TSK-099", "DONE"),
            lambda: seeded.add_tasks([{"source": {"kind": "OWNER"}}]),
            lambda: seeded.seed_update(0),
            lambda: seeded.seed_learning(0),
            lambda: seeded.seed_learning(5),
            lambda: seeded.seed_learning(1, ["Same.", "same."], source="OWNER"),
            lambda: seeded.seed_learning(1, source="NOBODY"),
            lambda: seeded.seed_update(1, [{"statement": ""}]),
        )
        for failure in failures:
            with pytest.raises(ValueError):
                failure()
        assert studio.errors == []


ALIGNMENT_REASON = "Aligned to the current upstream versions with unchanged content."
SECTION_KEYS = ["BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE"]


def states(sections: Mapping[str, object]) -> dict[str, tuple[object, ...]]:
    return {
        item["key"]: (
            item["state"],
            item["version_number"],
            item["reasons"],
            item["blocked"],
            item["codes"],
        )
        for item in sections["sections"]
    }


def design_content(package: Mapping[str, object]) -> dict:
    content = json.loads(json.dumps(package))
    content.pop("grounding")
    for alternative in content["alternatives"]:
        alternative.pop("user_twin_references")
    for critique in content["critiques"]:
        critique.pop("user_twin_reference")
    return content


def twin_identities(project_snapshot: Mapping[str, object]) -> list[tuple[str, str]]:
    return [
        (twin["twin_id"], twin["profile"]["name"])
        for twin in project_snapshot["snapshot"]["twin_versions"]
    ]


def last_reason(client: Client, path: str) -> str | None:
    return client.get(path).json()[-1]["reason"]


def published(client: Client, base: str) -> tuple[int, object]:
    reply = client.post(base + "/knowledge-packages")
    return reply.status, reply.json()


def attempts(gate: Mapping[str, object]) -> tuple[object, ...]:
    return gate["status"], gate["iteration"], gate["max_iterations"]


def new_design(client: Client, project: FakeProject) -> Reply:
    base = f"/projects/{project.id}"
    package = project.current("design")["package"]
    assertions = package["owner_assertions"]
    package["owner_assertions"] = [*assertions, f"Controllo numero {len(assertions) + 1}"]
    apply(client, base, package)
    return client.post(base + "/design/gate/submit")


def design_attempt(client: Client, project: FakeProject, action: str) -> tuple[object, ...]:
    assert new_design(client, project).status == 200
    reason = None if action == "APPROVE" else "Non ancora"
    decided = client.post(
        f"/projects/{project.id}/design/gate/decision", {"action": action, "reason": reason}
    )
    assert decided.status == 200
    return attempts(decided.json()["gate"])


def test_the_sections_of_a_seeded_project_follow_the_real_rules() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        empty = new_project(client)
        early = studio.seed_project(owner=EMAIL, name="Presto", through="requirements")
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"

        nothing = client.get(empty + "/sections").json()
        assert nothing == {
            "first_pass_complete": False,
            "sections": [
                {
                    "key": key,
                    "state": "NOT_STARTED",
                    "version_number": None,
                    "reasons": [],
                    "blocked": None,
                    "codes": [],
                }
                for key in SECTION_KEYS
            ],
            "alignment": {"available": False, "sections": [], "uncovered_codes": []},
        }
        first = client.get(f"/projects/{early.id}/sections").json()
        assert first["first_pass_complete"] is False
        assert [item["state"] for item in first["sections"]] == ["FINE"] * 4 + ["NOT_STARTED"] * 2

        sections = client.get(base + "/sections").json()
        assert sections == studio.sections(seeded.id) == seeded.sections()
        assert sections["first_pass_complete"] is True
        assert states(sections) == {
            "BRIEF": ("FINE", 1, [], None, []),
            "TEAM": ("FINE", 1, [], None, []),
            "USER_TWINS": ("FINE", 1, [], None, []),
            "REQUIREMENTS": ("FINE", 1, [], None, []),
            "DESIGN": ("UPDATE_AVAILABLE", 2, ["EVALUATION_MISSING"], None, []),
            "PACKAGE": ("NOT_STARTED", None, [], None, []),
        }
        design = seeded.current("design")
        reviewed = client.post(
            base + "/design/evaluations",
            {"design_version_id": design["id"], "design_content_hash": design["content_hash"]},
        )
        assert reviewed.status == 201
        assert published(client, base)[0] == 201
        assert states(client.get(base + "/sections").json())["DESIGN"] == ("FINE", 2, [], None, [])
        assert states(seeded.sections())["PACKAGE"] == ("FINE", 1, [], None, [])

        seeded.seed_change()
        learned = states(seeded.sections())["USER_TWINS"]
        assert learned == ("UPDATE_AVAILABLE", 1, ["TWINS_LEARNED"], None, [])
        assert states(seeded.sections())["PACKAGE"] == ("FINE", 1, [], None, [])

        stranger = signed_in(studio, OTHER)
        refused = {"detail": {"code": "PROJECT_NOT_FOUND"}}
        assert (
            stranger.get(base + "/sections").status,
            stranger.get(base + "/sections").json(),
        ) == (
            404,
            refused,
        )
        gesture = stranger.post(base + "/sections/alignment")
        assert (gesture.status, gesture.json()) == (404, refused)
        assert seeded.alignments() == []
        assert studio.errors == []


def test_without_a_model_a_pending_update_still_tells_that_the_twins_learned() -> None:
    with FakeStudio(job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        seeded.seed_change()
        studio.hosted = False
        assert states(seeded.sections())["USER_TWINS"][0] == "FINE"
        seeded.seed_update(0)
        assert states(seeded.sections())["USER_TWINS"][2] == ["TWINS_LEARNED"]
        assert studio.errors == []


def test_the_gesture_re_anchors_twins_requirements_and_design_after_a_perspective_change() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        assert published(client, base)[0] == 201
        twins_before = twin_identities(seeded.current("twins"))
        design_before = seeded.current("design")

        behind = studio.seed_perspective_change(seeded.id, "SECURITY_REVIEWER")
        assert behind == client.get(base + "/sections").json()
        assert states(behind) == {
            "BRIEF": ("FINE", 1, [], None, []),
            "TEAM": ("FINE", 2, [], None, []),
            "USER_TWINS": ("TO_UPDATE", 1, ["PERSPECTIVES_CHANGED"], None, []),
            "REQUIREMENTS": (
                "TO_UPDATE",
                1,
                ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"],
                None,
                [],
            ),
            "DESIGN": ("TO_UPDATE", 2, ["REQUIREMENTS_CHANGED"], None, []),
            "PACKAGE": ("TO_UPDATE", 1, ["FOLDER_BEHIND"], None, []),
        }
        assert behind["alignment"] == {
            "available": True,
            "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"],
            "uncovered_codes": [],
        }
        security = next(
            item for item in seeded.current("team")["perspectives"] if item["key"] == "SECURITY"
        )
        assert security["applied"] is True
        assert published(client, base) == (409, {"detail": {"code": "USER_TWINS_OUTDATED"}})
        assert seeded.stage == "USER_TWINS"

        reply = client.post(base + "/sections/alignment")
        answer = reply.json()
        assert reply.status == 200
        assert answer["status"] == "ALIGNED"
        assert answer["results"] == [
            {
                "key": "USER_TWINS",
                "outcome": "ALIGNED",
                "issue": None,
                "version_number": 2,
                "codes": [],
            },
            {
                "key": "REQUIREMENTS",
                "outcome": "ALIGNED",
                "issue": None,
                "version_number": 2,
                "codes": [],
            },
            {
                "key": "DESIGN",
                "outcome": "ALIGNED",
                "issue": None,
                "version_number": 3,
                "codes": [],
            },
        ]
        assert answer["sections"] == client.get(base + "/sections").json()
        assert states(answer["sections"]) == {
            "BRIEF": ("FINE", 1, [], None, []),
            "TEAM": ("FINE", 2, [], None, []),
            "USER_TWINS": ("FINE", 2, [], None, []),
            "REQUIREMENTS": ("FINE", 2, [], None, []),
            "DESIGN": ("UPDATE_AVAILABLE", 3, ["EVALUATION_MISSING"], None, []),
            "PACKAGE": ("TO_UPDATE", 1, ["FOLDER_BEHIND"], None, []),
        }
        assert all(seeded.approved(stage) for stage in STEPS)
        assert (seeded.stage, seeded.next_action) == ("PACKAGE", "DOWNLOAD_FOLDER")
        twins_after = seeded.current("twins")
        assert twin_identities(twins_after) == twins_before
        assert [
            twin["based_on_version_number"] for twin in twins_after["snapshot"]["twin_versions"]
        ] == [
            1,
            1,
        ]
        team = seeded.current("team")
        assert twins_after["snapshot"]["agent_team_reference"]["artifact_id"] == team["id"]
        requirements = seeded.current("requirements")
        assert (
            requirements["specification"]["user_modeling_reference"]["artifact_id"]
            == (twins_after["id"])
        )
        design = seeded.current("design")
        assert design_content(design["package"]) == design_content(design_before["package"])
        assert (
            design["package"]["grounding"]["requirements_reference"]["artifact_id"]
            == (requirements["id"])
        )
        for path in (
            "/user-modeling/gate/events",
            "/requirements/gate/events",
            "/design/gate/events",
        ):
            assert last_reason(client, base + path) == ALIGNMENT_REASON
        assert seeded.alignments() == [answer]
        assert studio.alignments(seeded.id) == [answer]

        status, folder = published(client, base)
        assert (status, folder["version"]["version_number"]) == (201, 2)
        assert states(seeded.sections())["PACKAGE"] == ("FINE", 2, [], None, [])
        again = client.post(base + "/sections/alignment").json()
        assert (again["status"], again["results"]) == ("NOTHING_TO_ALIGN", [])
        assert len(seeded.alignments()) == 2
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_the_gesture_re_anchors_the_design_after_a_requirements_change() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        before = seeded.current("design")

        behind = studio.seed_requirements_change(seeded.id)
        assert states(behind)["REQUIREMENTS"] == ("FINE", 2, [], None, [])
        assert states(behind)["DESIGN"] == ("TO_UPDATE", 2, ["REQUIREMENTS_CHANGED"], None, [])
        assert behind["alignment"] == {
            "available": True,
            "sections": ["DESIGN"],
            "uncovered_codes": ["REQ-005"],
        }
        codes = [
            item["code"] for item in seeded.current("requirements")["specification"]["requirements"]
        ]
        assert codes == ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]
        mockup = {
            "design_version_id": before["id"],
            "design_content_hash": before["content_hash"],
            "alternative_id": before["package"]["owner_selected_alternative_id"],
        }
        stale = client.post(base + "/design/mockups/jobs", mockup)
        assert (stale.status, stale.json()) == (409, {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}})
        assert published(client, base) == (409, {"detail": {"code": "DESIGN_OUTDATED"}})

        answer = client.post(base + "/sections/alignment").json()
        assert (answer["status"], answer["results"]) == (
            "ALIGNED",
            [
                {
                    "key": "DESIGN",
                    "outcome": "ALIGNED",
                    "issue": None,
                    "version_number": 3,
                    "codes": [],
                }
            ],
        )
        assert states(answer["sections"])["DESIGN"] == (
            "UPDATE_AVAILABLE",
            3,
            ["REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING"],
            None,
            ["REQ-005"],
        )
        after = seeded.current("design")
        assert design_content(after["package"]) == design_content(before["package"])
        fresh = {
            **mockup,
            "design_version_id": after["id"],
            "design_content_hash": after["content_hash"],
        }
        assert client.post(base + "/design/mockups/jobs", fresh).status == 202
        assert published(client, base)[0] == 201
        assert studio.errors == []


def test_a_new_brief_reanchors_valid_perspectives_before_the_other_sections() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        twins_before = twin_identities(seeded.current("twins"))
        team_before = seeded.current("team")
        behind = studio.seed_brief_change(seeded.id)
        assert states(behind)["TEAM"] == ("TO_UPDATE", 1, ["BRIEF_CHANGED"], None, [])
        assert behind["alignment"]["available"]
        status = client.get(base + "/team/context-alignment").json()
        assert status == {
            "aligned": False,
            "issue": None,
            "team_version_number": 1,
            "brief_version_number": 2,
        }
        assert published(client, base) == (409, {"detail": {"code": "TEAM_OUTDATED"}})
        aligned = client.post(base + "/team/context-alignment")
        assert aligned.status == 200
        team = seeded.current("team")
        assert aligned.json() == {
            "version_id": team["id"],
            "version_number": 2,
            "based_on_version_number": 1,
            "content_hash": team["content_hash"],
            "gate_approval_required": True,
        }
        assert team["revision_kind"] == "OWNER_EDITED"
        assert team["members"] == team_before["members"]
        assert not seeded.approved("team")
        approve(client, base + "/gates/agent-team/submit", base + "/gates/agent-team/decisions")
        answer = client.post(base + "/sections/alignment").json()
        assert answer["status"] == "ALIGNED"
        assert [item["key"] for item in answer["results"]] == [
            "USER_TWINS",
            "REQUIREMENTS",
            "DESIGN",
        ]
        assert twin_identities(seeded.current("twins")) == twins_before
        assert seeded.current("twins")["snapshot"]["project_brief_reference"]["version_number"] == 2
        assert published(client, base)[0] == 201
        assert not any(
            request.method == "POST" and request.path.endswith("/team-proposals")
            for request in studio.requests
        )
        assert studio.errors == []


def test_a_removed_requirement_and_a_pending_revision_block_the_design() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        removed = studio.seed_project(owner=EMAIL, name="Tolto", through="design")
        pending = studio.seed_project(owner=EMAIL, name="Sospeso", through="design")

        sections = studio.seed_requirement_removed(removed.id)
        assert states(sections)["DESIGN"] == (
            "TO_UPDATE",
            2,
            ["REQUIREMENTS_CHANGED"],
            "REQUIREMENT_NO_LONGER_AVAILABLE",
            ["REQ-004", "AC-004"],
        )
        assert sections["alignment"] == {
            "available": False,
            "sections": ["DESIGN"],
            "uncovered_codes": [],
        }
        blocked = client.post(f"/projects/{removed.id}/sections/alignment").json()
        assert (blocked["status"], blocked["results"]) == (
            "NOTHING_TO_ALIGN",
            [
                {
                    "key": "DESIGN",
                    "outcome": "BLOCKED",
                    "issue": "REQUIREMENT_NO_LONGER_AVAILABLE",
                    "version_number": None,
                    "codes": ["REQ-004", "AC-004"],
                }
            ],
        )
        assert removed.current("design")["version_number"] == 2

        studio.seed_requirements_change(pending.id)
        sections = studio.seed_design_revision(pending.id)
        assert states(sections)["DESIGN"][3] == "REVISION_PENDING"
        base = f"/projects/{pending.id}"
        waiting = client.post(base + "/sections/alignment").json()
        assert waiting["results"][0]["issue"] == "REVISION_PENDING"
        diff = client.get(base + "/design/revisions").json()[-1]
        assert diff["status"] == "PROPOSED"
        decided = client.post(
            f"{base}/design/revisions/{diff['id']}/decision",
            {"decision": "REJECT", "reason": "Non serve"},
        )
        assert decided.status == 200
        assert client.post(base + "/sections/alignment").json()["status"] == "ALIGNED"
        assert studio.errors == []


def test_the_gesture_goes_past_the_third_approval_of_a_gate() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        seeded.seed_version("design")
        seeded.seed_version("design")
        assert attempts(seeded.gate("design")) == ("APPROVED", 3, 5)
        studio.seed_requirements_change(seeded.id)
        answer = client.post(f"/projects/{seeded.id}/sections/alignment").json()
        assert (answer["status"], answer["results"]) == (
            "ALIGNED",
            [
                {
                    "key": "DESIGN",
                    "outcome": "ALIGNED",
                    "issue": None,
                    "version_number": 5,
                    "codes": [],
                }
            ],
        )
        assert seeded.current("design")["version_number"] == 5
        assert attempts(seeded.gate("design")) == ("APPROVED", 4, 6)
        assert studio.errors == []


def test_only_versions_not_approved_use_up_the_attempts_of_a_gate() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        decisions = ("REJECT", "REJECT", "APPROVE")
        tried = [design_attempt(client, seeded, action) for action in decisions]
        assert tried == [("REJECTED", 2, 4), ("REJECTED", 3, 4), ("APPROVED", 4, 4)]
        studio.seed_requirements_change(seeded.id)
        answer = client.post(f"/projects/{seeded.id}/sections/alignment").json()
        assert (answer["status"], answer["results"]) == (
            "ALIGNED",
            [
                {
                    "key": "DESIGN",
                    "outcome": "ALIGNED",
                    "issue": None,
                    "version_number": 6,
                    "codes": [],
                }
            ],
        )
        assert attempts(seeded.gate("design")) == ("APPROVED", 5, 7)
        tried = [design_attempt(client, seeded, "REJECT") for _ in range(3)]
        assert tried == [("REJECTED", 6, 8), ("REJECTED", 7, 8), ("REJECTED", 8, 8)]
        refused = new_design(client, seeded)
        assert (refused.status, refused.json()) == (
            409,
            {"detail": {"code": "ITERATION_LIMIT_REACHED"}},
        )
        assert states(seeded.sections())["DESIGN"][:2] == ("IN_PROGRESS", 10)
        assert studio.errors == []


def test_the_twins_follow_the_brief_and_the_perspectives_through_their_route() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        early = studio.seed_project(owner=EMAIL, name="Presto", through="team")
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        early_path = f"/projects/{early.id}/user-modeling/context-alignment"
        path = f"/projects/{seeded.id}/user-modeling/context-alignment"

        assert client.get(early_path).json() == {
            "aligned": False,
            "issue": "USER_TWINS_NOT_FOUND",
            "snapshot_version_number": None,
            "brief_version_number": 1,
            "team_version_number": 1,
        }
        missing = client.post(early_path)
        assert (missing.status, missing.json()) == (
            404,
            {"detail": {"code": "USER_TWINS_NOT_FOUND"}},
        )
        assert client.get(path).json() == {
            "aligned": True,
            "issue": "ALREADY_ALIGNED",
            "snapshot_version_number": 1,
            "brief_version_number": 1,
            "team_version_number": 1,
        }
        assert client.post(path).json() == {"detail": {"code": "ALREADY_ALIGNED"}}

        twins_before = seeded.current("twins")
        studio.seed_perspective_change(seeded.id, "MOBILE_ENGINEER")
        assert client.get(path).json() == {
            "aligned": False,
            "issue": None,
            "snapshot_version_number": 1,
            "brief_version_number": 1,
            "team_version_number": 2,
        }
        created = client.post(path)
        body = created.json()
        snapshot = seeded.current("twins")
        assert created.status == 201
        assert body == {
            "snapshot_version_id": snapshot["id"],
            "snapshot_version_number": 2,
            "based_on_version_number": 1,
            "content_hash": snapshot["content_hash"],
            "twin_count": 2,
            "gate_approval_required": True,
        }
        assert not seeded.approved("twins")
        assert twin_identities(snapshot) == twin_identities(twins_before)
        old = {twin["twin_id"]: twin for twin in twins_before["snapshot"]["twin_versions"]}
        for twin in snapshot["snapshot"]["twin_versions"]:
            earlier = old[twin["twin_id"]]
            assert (twin["version_number"], twin["based_on_version_number"]) == (2, 1)
            assert twin["profile"]["observations"] == earlier["profile"]["observations"]
            assert twin["profile"]["persona_reference"] == earlier["profile"]["persona_reference"]
            assert twin["profile"]["agent_team_reference"]["version_number"] == 2
        assert (
            snapshot["snapshot"]["persona_versions"] == twins_before["snapshot"]["persona_versions"]
        )
        assert client.get(path).json()["issue"] == "ALREADY_ALIGNED"
        assert states(seeded.sections())["USER_TWINS"] == ("IN_PROGRESS", 2, [], None, [])

        studio.seed_brief_change(early.id)
        still_missing = client.post(early_path)
        assert still_missing.json() == {"detail": {"code": "USER_TWINS_NOT_FOUND"}}
        unapproved = studio.seed_project(owner=EMAIL, name="Nuovo brief", through="design")
        fields = {
            key: value
            for key, value in unapproved.current("brief")["brief"].items()
            if key not in ("provided_fields", "missing_fields")
        }
        changed = client.post(
            f"/projects/{unapproved.id}/brief-versions",
            {**fields, "description": "Una pagina per il conto."},
        )
        assert changed.status == 201
        route = f"/projects/{unapproved.id}/user-modeling/context-alignment"
        assert client.get(route).json()["issue"] == "BRIEF_APPROVAL_REQUIRED"
        assert client.post(route).json() == {"detail": {"code": "BRIEF_APPROVAL_REQUIRED"}}
        approve(
            client,
            f"/projects/{unapproved.id}/gates/project-brief/submit",
            f"/projects/{unapproved.id}/gates/project-brief/decisions",
        )
        assert client.post(route).json() == {"detail": {"code": "TEAM_APPROVAL_REQUIRED"}}
        stranger = signed_in(studio, OTHER)
        assert stranger.get(path).json()["issue"] == "USER_TWINS_NOT_FOUND"
        assert stranger.post(path).status == 404
        assert studio.errors == []


def test_the_requirements_follow_the_twins_through_their_route() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed_in(studio)
        early = studio.seed_project(owner=EMAIL, name="Presto", through="twins")
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        path = base + "/requirements/twin-alignment"

        assert client.get(f"/projects/{early.id}/requirements/twin-alignment").json() == {
            "aligned": False,
            "issue": "REQUIREMENTS_NOT_FOUND",
            "requirements_version_number": None,
            "snapshot_version_number": 1,
            "twins_approved": True,
        }
        missing = client.post(f"/projects/{early.id}/requirements/twin-alignment")
        assert (missing.status, missing.json()) == (
            404,
            {"detail": {"code": "REQUIREMENTS_NOT_FOUND"}},
        )
        assert client.get(path).json() == {
            "aligned": True,
            "issue": "REQUIREMENTS_ALREADY_ALIGNED",
            "requirements_version_number": 1,
            "snapshot_version_number": 1,
            "twins_approved": True,
        }
        assert client.post(path).json() == {"detail": {"code": "REQUIREMENTS_ALREADY_ALIGNED"}}

        studio.seed_perspective_change(seeded.id, "SECURITY_REVIEWER")
        assert client.get(path).json() == {
            "aligned": True,
            "issue": "USER_TWINS_APPROVAL_REQUIRED",
            "requirements_version_number": 1,
            "snapshot_version_number": 1,
            "twins_approved": False,
        }
        assert client.post(path).json() == {"detail": {"code": "USER_TWINS_APPROVAL_REQUIRED"}}
        assert client.post(base + "/user-modeling/context-alignment").status == 201
        assert client.get(path).json()["issue"] == "USER_TWINS_APPROVAL_REQUIRED"
        approve(client, base + "/user-modeling/gate/submit", base + "/user-modeling/gate/decision")
        assert published(client, base) == (409, {"detail": {"code": "REQUIREMENTS_OUTDATED"}})
        assert client.get(path).json() == {
            "aligned": False,
            "issue": None,
            "requirements_version_number": 1,
            "snapshot_version_number": 2,
            "twins_approved": True,
        }
        change = client.post(base + "/requirements/change-requests", {"request": "Aggiungi il bis"})
        assert change.status == 201
        assert client.post(path).json() == {"detail": {"code": "REQUIREMENTS_REVISION_PENDING"}}
        diff = change.json()["diff"]
        rejected = client.post(
            f"{base}/requirements/revisions/{diff['id']}/decision",
            {"decision": "REJECT", "reason": "Non ora"},
        )
        assert rejected.status == 200
        created = client.post(path)
        requirements = seeded.current("requirements")
        snapshot = seeded.current("twins")
        assert created.status == 201
        assert created.json() == {
            "version_id": requirements["id"],
            "version_number": 2,
            "based_on_version_number": 1,
            "content_hash": requirements["content_hash"],
            "user_modeling_version_number": 2,
            "twin_count": 2,
            "gate_approval_required": True,
        }
        specification = requirements["specification"]
        assert specification["agent_team_reference"]["version_number"] == 2
        assert specification["user_modeling_reference"]["artifact_id"] == snapshot["id"]
        versions = {
            twin["twin_id"]: twin["version_number"]
            for twin in specification["user_twin_references"]
        }
        assert set(versions.values()) == {2}
        assert all(
            reference["version_number"] == 2
            for story in specification["user_stories"]
            for reference in (story["user_twin_reference"],)
        )
        assert not seeded.approved("requirements")
        assert client.get(path).json()["issue"] == "REQUIREMENTS_ALREADY_ALIGNED"

        lost = studio.seed_project(owner=EMAIL, name="Nuovi twin", through="design")
        lost_base = f"/projects/{lost.id}"
        studio.seed_perspective_change(lost.id, "SECURITY_REVIEWER")
        regenerated = client.post(lost_base + "/user-modeling/snapshots/generate")
        assert regenerated.status == 200
        approve(
            client,
            lost_base + "/user-modeling/gate/submit",
            lost_base + "/user-modeling/gate/decision",
        )
        reanchored = client.post(lost_base + "/requirements/twin-alignment")
        assert reanchored.status == 201
        assert reanchored.json()["gate_approval_required"]
        assert not lost.approved("requirements")
        assert studio.errors == []


def test_the_design_follows_the_requirements_through_its_route() -> None:
    with FakeStudio(twins=3, job_polls=0) as studio:
        client = signed_in(studio)
        early = studio.seed_project(owner=EMAIL, name="Presto", through="requirements")
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        base = f"/projects/{seeded.id}"
        path = base + "/design/requirements-alignment"

        early_path = f"/projects/{early.id}/design/requirements-alignment"
        assert client.get(early_path).json() == {
            "aligned": False,
            "issue": "DESIGN_NOT_FOUND",
            "design_version_number": None,
            "grounded_requirements_version_number": None,
            "requirements_version_number": 1,
            "missing_codes": [],
            "uncovered_codes": [],
        }
        assert client.post(early_path).json() == {"detail": {"code": "DESIGN_NOT_FOUND"}}
        assert client.get(path).json() == {
            "aligned": True,
            "issue": "ALREADY_ALIGNED",
            "design_version_number": 2,
            "grounded_requirements_version_number": 1,
            "requirements_version_number": 1,
            "missing_codes": [],
            "uncovered_codes": [],
        }
        assert client.post(path).json() == {"detail": {"code": "ALREADY_ALIGNED"}}

        change = client.post(base + "/requirements/change-requests", {"request": "Aggiungi il bis"})
        diff = change.json()["diff"]
        applied = client.post(
            f"{base}/requirements/revisions/{diff['id']}/decision", {"decision": "APPROVE"}
        )
        assert applied.status == 200
        assert client.get(path).json() == {
            "aligned": False,
            "issue": "REQUIREMENTS_APPROVAL_REQUIRED",
            "design_version_number": 2,
            "grounded_requirements_version_number": 1,
            "requirements_version_number": 2,
            "missing_codes": [],
            "uncovered_codes": ["REQ-005"],
        }
        assert client.post(path).json() == {"detail": {"code": "REQUIREMENTS_APPROVAL_REQUIRED"}}
        assert states(seeded.sections())["DESIGN"][3] == "UPSTREAM_NOT_READY"
        approve(client, base + "/requirements/gate/submit", base + "/requirements/gate/decision")
        assert client.get(path).json()["issue"] is None
        created = client.post(path)
        design = seeded.current("design")
        assert created.status == 201
        assert created.json() == {
            "version_id": design["id"],
            "version_number": 3,
            "based_on_version_number": 2,
            "content_hash": design["content_hash"],
            "requirements_version_number": 2,
            "gate_approval_required": True,
            "uncovered_codes": ["REQ-005"],
        }
        assert not seeded.approved("design")
        assert client.get(path).json()["issue"] == "ALREADY_ALIGNED"

        removed = studio.seed_project(owner=EMAIL, name="Tolto", through="design")
        studio.seed_requirement_removed(removed.id)
        removed_path = f"/projects/{removed.id}/design/requirements-alignment"
        status = client.get(removed_path).json()
        assert (status["issue"], status["missing_codes"]) == (
            "REQUIREMENT_NO_LONGER_AVAILABLE",
            ["REQ-004", "AC-004"],
        )
        refused = client.post(removed_path)
        assert (refused.status, refused.json()) == (
            409,
            {
                "detail": {
                    "code": "REQUIREMENT_NO_LONGER_AVAILABLE",
                    "missing_codes": ["REQ-004", "AC-004"],
                }
            },
        )

        revised = studio.seed_project(owner=EMAIL, name="Rivisto", through="design")
        studio.seed_requirements_change(revised.id)
        studio.seed_design_revision(revised.id)
        assert client.post(f"/projects/{revised.id}/design/requirements-alignment").json() == {
            "detail": {"code": "DESIGN_REVISION_PENDING"}
        }

        fewer = studio.seed_project(owner=EMAIL, name="Meno twin", through="design")
        with studio._lock:
            current = fewer.requirements[-1]
            specification = json.loads(json.dumps(current["specification"]))
            dropped = specification["user_twin_references"].pop()["twin_id"]
            for requirement in specification["requirements"]:
                requirement["user_twin_references"] = [
                    item
                    for item in requirement["user_twin_references"]
                    if item["twin_id"] != dropped
                ]
            studio._append_requirements(fewer, specification, fewer.account)
            studio._approve(fewer, "requirements")
        assert client.post(f"/projects/{fewer.id}/design/requirements-alignment").json() == {
            "detail": {"code": "TWIN_SET_CHANGED"}
        }
        assert states(fewer.sections())["DESIGN"][3] == "TWIN_SET_CHANGED"
        assert studio.errors == []


def test_the_helpers_of_the_sections_refuse_what_cannot_be_seeded() -> None:
    with FakeStudio(job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        early = studio.seed_project(owner=EMAIL, name="Presto", through="brief")
        twins = studio.seed_project(owner=EMAIL, name="Twin", through="twins")
        seeded = studio.seed_project(owner=EMAIL, name="Seme", through="design")
        failures = (
            lambda: studio.seed_perspective_change(early.id, "SECURITY_REVIEWER"),
            lambda: studio.seed_perspective_change(seeded.id, "UX_UI_DESIGNER"),
            lambda: studio.seed_perspective_change(seeded.id, "NOBODY"),
            lambda: studio.seed_requirements_change(twins.id),
            lambda: studio.seed_requirement_removed(twins.id),
            lambda: studio.seed_design_revision(twins.id),
        )
        for failure in failures:
            with pytest.raises(ValueError):
                failure()
        removed = studio.seed_perspective_change(seeded.id, "FRONTEND_ENGINEER")
        assert states(removed)["TEAM"] == ("FINE", 2, [], None, [])
        assert "FRONTEND_ENGINEER" not in seeded.current("team")["selected_agent_ids"]
        assert studio.seed_perspective_change(seeded.id, "FRONTEND_ENGINEER") == seeded.sections()
        assert "FRONTEND_ENGINEER" in seeded.current("team")["selected_agent_ids"]
        studio.seed_brief_change(seeded.id)
        with pytest.raises(ValueError):
            studio.seed_brief_change(seeded.id)
        with pytest.raises(ValueError):
            studio.seed_perspective_change(seeded.id, "SECURITY_REVIEWER")
        studio.seed_design_revision(seeded.id)
        with pytest.raises(ValueError):
            studio.seed_design_revision(seeded.id)
        with pytest.raises(KeyError):
            studio.sections("00000000-0000-4000-8000-000000000000")
        copied = seeded.sections()
        copied["sections"].clear()
        assert len(seeded.sections()["sections"]) == 6
        assert studio.spent_microusd == 0
        assert studio.errors == []
