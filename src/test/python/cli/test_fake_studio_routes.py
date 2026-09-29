from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from orchestwin.api.app import create_app
from orchestwin.api.auth import (
    AuthApiSettings,
    AuthenticationResponse,
    UserResponse,
    current_user_dependency,
)
from orchestwin.api.clarification import (
    BriefAssumptionBulkAcceptanceResponse,
    BriefAssumptionDecisionResponse,
    BriefAssumptionResponse,
    HumanGateEventResponse,
    HumanGateResponse,
    ProjectBriefGateDecisionResponse,
    ProjectBriefGateSubmissionResponse,
)
from orchestwin.api.design import (
    DesignGateDecisionPayload,
    DesignGateSubmissionPayload,
    DesignGenerationPayload,
    DesignPackageDiffPayload,
    DesignPackagePayload,
    DesignPackageVersionPayload,
    DesignReadinessPayload,
    DesignRevisionPayload,
)
from orchestwin.api.design_mockups import MockupCapabilities
from orchestwin.api.design_review_pins import ReviewDocumentPayload, ReviewPinsPayload
from orchestwin.api.generation_jobs import GenerationJob, GenerationJobKind, GenerationOperation
from orchestwin.api.knowledge_packages import (
    KnowledgePackageHistoryPayload,
    KnowledgePackagePublicationPayload,
)
from orchestwin.api.project_imports import ProjectImportOriginPayload, ProjectImportPayload
from orchestwin.api.projects import ProjectBriefVersionResponse, ProjectResponse
from orchestwin.api.requirements import (
    RequirementsGateDecisionPayload,
    RequirementsGateSubmissionPayload,
    RequirementsGenerationPayload,
    RequirementsReadinessPayload,
    RequirementsRevisionPayload,
    RequirementsSpecificationDiffPayload,
    RequirementsSpecificationPayload,
    RequirementsSpecificationVersionPayload,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.teams import (
    AgentCatalogResponse,
    AgentTeamGateDecisionResponse,
    AgentTeamGateSubmissionResponse,
    ProjectReadinessResponse,
    TeamEditResponse,
    TeamProposalGenerationResponse,
    TeamProposalVersionResponse,
)
from orchestwin.api.user_modeling import (
    GateCommandPayload,
    HumanGatePayload,
    PersonaDecisionCommandPayload,
    PersonaProposalCommandPayload,
    PersonaVersionPayload,
    SnapshotGenerationCommandPayload,
    UserModelingReadinessPayload,
    UserModelingSnapshotVersionPayload,
)
from orchestwin.artifacts.bound_mockups import bound_mockup_from_snapshot
from orchestwin.artifacts.design_evaluation import synthetic_finding_from_snapshot
from orchestwin.artifacts.generated_mockup_review import review_generated_mockup
from orchestwin.artifacts.visual_catalog import MODES, VisualChoices
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.application import IdentityUnitOfWork, LocalIdentityApplicationService
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.models.design import DesignProposalIssueCode
from orchestwin.projects.code_changes import (
    alignment_verdict_from_snapshot,
    changed_file_from_snapshot,
    twin_critique_from_snapshot,
)

from .support.fake_studio import COSTS, PREFIX, ROUTES, FakeStudio, route_table

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
EMAIL = "owner@example.com"
PASSWORD = "Test-password-not-real!"
BOUNDARY = "fake-boundary-not-real"
JWT_SECRET = "jwt-secret-not-real-for-the-fake-studio-test"
MOMENT = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
REFUSED_REGISTRATIONS = (
    {"email": "probe@example.test", "password": PASSWORD},
    {"email": "person@localhost", "password": PASSWORD},
    {"email": "probe@example.test", "password": "abcdefgh!"},
    {"email": EMAIL, "password": "abcdefg1!"},
    {"email": EMAIL, "password": "Abcdefg12"},
    {"email": EMAIL, "password": "Abcde1!"},
    {"email": EMAIL, "password": "Ab!" * 342},
    {"email": EMAIL},
    {"email": "a@", "password": PASSWORD},
    {"email": 5, "password": "x" * 1025},
    {"email": EMAIL, "password": PASSWORD, "role": "owner"},
)


@pytest.fixture(scope="module")
def real_routes() -> frozenset[tuple[str, str]]:
    with pytest.MonkeyPatch.context() as patch:
        for name in tuple(os.environ):
            if name.upper().startswith("ORCHESTWIN_"):
                patch.delenv(name, raising=False)
        application = create_app(
            ApplicationSettings(
                application_name="OrchesTwin Fake Studio Route Test",
                environment=RuntimeEnvironment.TEST,
                debug=False,
                log_level=LogLevel.INFO,
                api_prefix=PREFIX,
                _env_file=None,
            ),
            runtime=ApplicationRuntime(),
            auth_settings=AuthApiSettings(_env_file=None),
        )
        document = application.openapi()
    return frozenset(
        (method.upper(), path)
        for path, operations in document["paths"].items()
        for method in operations
        if method.upper() in HTTP_METHODS
    )


def test_every_route_of_the_fake_exists_in_the_real_api(
    real_routes: frozenset[tuple[str, str]],
) -> None:
    missing = [route for route in route_table() if route not in real_routes]

    assert missing == []


def test_the_route_table_has_no_duplicates() -> None:
    table = route_table()

    assert len(set(table)) == len(table)
    assert all(path.startswith(PREFIX + "/") for _, path in table)


def test_only_health_and_the_sign_in_are_open_without_a_token() -> None:
    open_routes = {(route.method, route.template) for route in ROUTES if not route.authenticated}

    assert open_routes == {
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/logout"),
    }


def test_the_fake_serves_every_area_that_the_commands_need(
    real_routes: frozenset[tuple[str, str]],
) -> None:
    project = PREFIX + "/projects/{project_id}"
    needed = {
        ("GET", PREFIX + "/health"),
        ("POST", PREFIX + "/auth/login"),
        ("POST", PREFIX + "/auth/refresh"),
        ("GET", PREFIX + "/model-runtime/budget"),
        ("POST", PREFIX + "/projects"),
        ("POST", project + "/brief-dialogue/answers"),
        ("POST", project + "/brief-assumptions/accept-all"),
        ("POST", project + "/gates/project-brief/decisions"),
        ("PATCH", project + "/team-proposals/current"),
        ("POST", project + "/user-modeling/snapshots/generate"),
        ("POST", project + "/user-twins/{twin_id}/conversation/turns"),
        ("POST", project + "/requirements/change-requests"),
        ("POST", project + "/design/regenerations"),
        ("GET", project + "/design/mockups/document"),
        ("POST", project + "/design/mockups"),
        ("GET", project + "/design/mockups"),
        ("GET", project + "/design/iterations"),
        ("GET", project + "/design/evaluations/{run_id}/pins"),
        ("GET", project + "/generation-jobs/{job_id}"),
        ("GET", project + "/knowledge-packages/{version_number}/archive"),
        ("POST", PREFIX + "/project-imports"),
        ("GET", project + "/model-usage"),
        ("GET", project + "/alignment"),
        ("POST", project + "/code-changes"),
        ("GET", project + "/code-changes"),
        ("GET", project + "/code-changes/{commit}"),
        ("POST", project + "/code-changes/{commit}/reviews"),
        ("GET", project + "/code-changes/{commit}/reviews"),
        ("POST", project + "/code-changes/{commit}/decision"),
    }

    assert needed <= set(route_table())
    assert needed <= real_routes


class _Client:
    def __init__(self, studio: FakeStudio) -> None:
        self.base = studio.address + PREFIX
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token: str | None = None
        self.headers: dict[str, str] = {}

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        content: bytes | None = None,
        content_type: str = "application/json",
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, object]:
        data = content if content is not None else None
        if content is None and body is not None:
            data = json.dumps(body).encode("utf-8")
        sent = {"Content-Type": content_type} if data is not None else {}
        if self.token is not None:
            sent["Authorization"] = f"Bearer {self.token}"
        sent.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=sent, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                self.headers = {name.lower(): value for name, value in response.headers.items()}
                return response.status, _parsed(response.read())
        except urllib.error.HTTPError as error:
            with error:
                self.headers = {name.lower(): value for name, value in error.headers.items()}
                return error.code, _parsed(error.read())


def _parsed(content: bytes) -> object:
    return json.loads(content.decode("utf-8")) if content else None


def fits(model: type[BaseModel], reply: tuple[int, object], status: int = 200) -> dict:
    code, payload = reply
    assert code == status, payload
    assert isinstance(payload, dict)
    assert set(payload) == set(model.model_fields), model.__name__
    model.model_validate(payload)
    return payload


def items_fit(model: type[BaseModel], reply: tuple[int, object]) -> list:
    code, payload = reply
    assert code == 200
    assert isinstance(payload, list)
    assert payload
    for item in payload:
        assert set(item) == set(model.model_fields), model.__name__
        model.model_validate(item)
    return payload


def test_the_answers_of_the_fake_fit_the_response_models_of_the_real_api() -> None:
    with FakeStudio(job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        client = _Client(studio)
        login = fits(
            AuthenticationResponse,
            client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD}),
        )
        client.token = str(login["access_token"])
        fits(UserResponse, client.call("GET", "/auth/me"))
        fits(AgentCatalogResponse, client.call("GET", "/agent-catalog"))
        created = client.call(
            "POST", "/projects", {"display_name": "Calcolo mancia", "mode": "GREENFIELD_GENERATION"}
        )
        base = f"/projects/{fits(ProjectResponse, created, 201)['id']}"

        _, state = client.call("POST", base + "/brief-dialogue", {"statement": "Una pagina."})
        while any(turn["answer"] is None for turn in state["snapshot"]["turns"]):
            count = len(state["snapshot"]["turns"])
            _, state = client.call(
                "POST",
                base + "/brief-dialogue/answers",
                {"kind": "UNKNOWN", "expected_turn_count": count},
            )
        _, synthesis = client.call(
            "POST",
            base + "/brief-dialogue/synthesis",
            {"expected_turn_count": len(state["snapshot"]["turns"])},
        )
        ProjectBriefVersionResponse.model_validate(synthesis["brief_version"])
        proposals = [
            BriefAssumptionResponse.model_validate(item) for item in synthesis["assumptions"]
        ]
        assert len(proposals) == 6
        fits(
            BriefAssumptionDecisionResponse,
            client.call("POST", f"{base}/brief-assumptions/{proposals[0].id}/accept", {}),
        )
        fits(
            BriefAssumptionDecisionResponse,
            client.call(
                "POST", f"{base}/brief-assumptions/{proposals[1].id}/reject", {"reason": "No"}
            ),
        )
        fits(
            BriefAssumptionBulkAcceptanceResponse,
            client.call("POST", base + "/brief-assumptions/accept-all"),
        )
        items_fit(BriefAssumptionResponse, client.call("GET", base + "/brief-assumptions"))
        submitted = fits(
            ProjectBriefGateSubmissionResponse,
            client.call("POST", base + "/gates/project-brief/submit"),
            201,
        )
        fits(
            ProjectBriefGateDecisionResponse,
            client.call("POST", base + "/gates/project-brief/decisions", {"action": "APPROVE"}),
        )
        fits(HumanGateResponse, client.call("GET", base + "/gates/project-brief/current"))
        gate_id = submitted["gate"]["id"]
        items_fit(
            HumanGateEventResponse,
            client.call("GET", f"{base}/gates/project-brief/{gate_id}/events"),
        )
        items_fit(ProjectBriefVersionResponse, client.call("GET", base + "/brief-versions"))

        fits(TeamProposalGenerationResponse, client.call("POST", base + "/team-proposals"), 201)
        team = fits(
            TeamProposalVersionResponse, client.call("GET", base + "/team-proposals/current")
        )
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        fits(
            TeamEditResponse,
            client.call("PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited}),
            201,
        )
        fits(ProjectReadinessResponse, client.call("GET", base + "/readiness"))
        fits(
            AgentTeamGateSubmissionResponse,
            client.call("POST", base + "/gates/agent-team/submit"),
            201,
        )
        fits(
            AgentTeamGateDecisionResponse,
            client.call("POST", base + "/gates/agent-team/decisions", {"action": "APPROVE"}),
        )

        fits(
            PersonaProposalCommandPayload,
            client.call("POST", base + "/user-modeling/personas/proposals"),
        )
        for persona in items_fit(
            PersonaVersionPayload, client.call("GET", base + "/user-modeling/personas")
        ):
            fits(
                PersonaDecisionCommandPayload,
                client.call(
                    "POST",
                    f"{base}/user-modeling/personas/{persona['persona_id']}/decision",
                    {"decision": "CONFIRM"},
                ),
            )
        generated = fits(
            SnapshotGenerationCommandPayload,
            client.call("POST", base + "/user-modeling/snapshots/generate"),
        )
        fits(
            UserModelingSnapshotVersionPayload,
            client.call("GET", base + "/user-modeling/snapshots/current"),
        )
        fits(GateCommandPayload, client.call("POST", base + "/user-modeling/gate/submit"))
        fits(
            GateCommandPayload,
            client.call("POST", base + "/user-modeling/gate/decision", {"action": "APPROVE"}),
        )
        fits(HumanGatePayload, client.call("GET", base + "/user-modeling/gate"))
        fits(UserModelingReadinessPayload, client.call("GET", base + "/user-modeling/readiness"))

        fits(
            RequirementsGenerationPayload,
            client.call("POST", base + "/requirements/proposals"),
            201,
        )
        change = fits(
            RequirementsRevisionPayload,
            client.call(
                "POST", base + "/requirements/change-requests", {"request": "Aggiungi il bis"}
            ),
            201,
        )
        items_fit(
            RequirementsSpecificationDiffPayload,
            client.call("GET", base + "/requirements/revisions"),
        )
        fits(
            RequirementsRevisionPayload,
            client.call(
                "POST",
                f"{base}/requirements/revisions/{change['diff']['id']}/decision",
                {"decision": "APPROVE"},
            ),
        )
        fits(
            RequirementsSpecificationVersionPayload,
            client.call("GET", base + "/requirements/current"),
        )
        fits(
            RequirementsGateSubmissionPayload,
            client.call("POST", base + "/requirements/gate/submit"),
        )
        fits(
            RequirementsGateDecisionPayload,
            client.call("POST", base + "/requirements/gate/decision", {"action": "APPROVE"}),
        )
        fits(RequirementsReadinessPayload, client.call("GET", base + "/requirements/readiness"))

        fits(DesignGenerationPayload, client.call("POST", base + "/design/proposals"), 201)
        current = fits(DesignPackageVersionPayload, client.call("GET", base + "/design/current"))
        fits(MockupCapabilities, client.call("GET", base + "/design/mockups/capabilities"))
        chosen = current["package"]["recommended_alternative_id"]
        _, job = client.call(
            "POST",
            base + "/design/mockups/jobs",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "alternative_id": chosen,
            },
        )
        real_job = GenerationJob(
            job_id=UUID(int=1),
            owner_user_id=UUID(int=2),
            project_id=UUID(int=3),
            kind=GenerationJobKind.MOCKUP,
            operation=GenerationOperation.MOCKUP,
            key="key",
            alternative_id=None,
            started_at=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
        ).to_payload()
        assert list(job) == list(real_job)
        _, finished = client.call("GET", f"{base}/design/mockups/jobs/{job['job_id']}")
        assert list(finished) == list(real_job)
        package = finished["result"]["package"]
        assert set(package) == set(DesignPackagePayload.model_fields)
        DesignPackagePayload.model_validate(package)
        proposed = fits(
            DesignRevisionPayload,
            client.call("POST", base + "/design/revisions", {"package": package}),
            201,
        )
        fits(DesignPackageDiffPayload, (200, proposed["diff"]))
        decided = fits(
            DesignRevisionPayload,
            client.call(
                "POST",
                f"{base}/design/revisions/{proposed['diff']['id']}/decision",
                {"decision": "APPROVE"},
            ),
        )
        version = decided["version"]
        _, run = client.call(
            "POST",
            base + "/design/evaluations",
            {"design_version_id": version["id"], "design_content_hash": version["content_hash"]},
        )
        fits(ReviewPinsPayload, client.call("GET", f"{base}/design/evaluations/{run['id']}/pins"))
        fits(
            ReviewDocumentPayload,
            client.call("GET", f"{base}/design/evaluations/{run['id']}/document"),
        )
        fits(DesignGateSubmissionPayload, client.call("POST", base + "/design/gate/submit"))
        fits(
            DesignGateDecisionPayload,
            client.call("POST", base + "/design/gate/decision", {"action": "APPROVE"}),
        )
        fits(DesignReadinessPayload, client.call("GET", base + "/design/readiness"))

        published = fits(
            KnowledgePackagePublicationPayload,
            client.call("POST", base + "/knowledge-packages"),
            201,
        )
        fits(KnowledgePackageHistoryPayload, client.call("GET", base + "/knowledge-packages"))
        archive = urllib.request.Request(
            f"{client.base}{base}/knowledge-packages/1/archive",
            headers={"Authorization": f"Bearer {client.token}"},
        )
        with client.opener.open(archive, timeout=10) as response:
            content = response.read()
        assert published["version"]["archive_hash"] == response.headers["X-Content-SHA256"]
        body = (
            (
                f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="archive"; '
                'filename="folder.zip"\r\nContent-Type: application/zip\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{BOUNDARY}--\r\n".encode()
        )
        imported = fits(
            ProjectImportPayload,
            client.call(
                "POST",
                "/project-imports",
                content=body,
                content_type=f"multipart/form-data; boundary={BOUNDARY}",
            ),
            201,
        )
        copy_base = f"/projects/{imported['project']['id']}"
        fits(ProjectImportOriginPayload, client.call("GET", copy_base + "/import"))
        fits(
            DesignGenerationPayload,
            client.call("POST", copy_base + "/design/regenerations"),
            201,
        )
        assert generated["twin_versions"]
        assert studio.errors == []


def canonical_design(package: dict, codes: list[str]) -> None:
    parsed = DesignPackagePayload.model_validate(package)
    rebuilt = DesignPackagePayload.from_domain(parsed.to_domain())
    assert rebuilt.model_dump(mode="json") == parsed.model_dump(mode="json")
    bound = package["generated_mockup"]
    if bound is None:
        return
    alternative = next(
        item
        for item in package["alternatives"]
        if item["id"] == bound["mockup"]["design_alternative_id"]
    )
    visual = alternative["visual_language"]
    mockup = bound_mockup_from_snapshot(bound, token_names=visual["tokens"])
    assert mockup.prototype().to_snapshot() == package["prototype"]
    report = review_generated_mockup(
        mockup.mockup,
        tokens=visual["tokens"],
        requirement_codes=codes,
        text_contrast_threshold=MODES[
            VisualChoices.from_snapshot(visual["choices"]).color_mode
        ].text_threshold,
    )
    assert report.is_acceptable, report.to_snapshot()


@pytest.mark.parametrize(("language", "hosted"), [("it", True), ("en", True), ("en", False)])
def test_the_artifacts_of_the_fake_pass_the_real_domain_rules(language: str, hosted: bool) -> None:
    with FakeStudio(language=language, hosted=hosted, job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        client = _Client(studio)
        _, login = client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
        client.token = str(login["access_token"])
        base = f"/projects/{project.id}"
        specification = project.current("requirements")["specification"]
        parsed = RequirementsSpecificationPayload.model_validate(specification)
        rebuilt = RequirementsSpecificationPayload.from_domain(parsed.to_domain())
        assert rebuilt.model_dump(mode="json") == parsed.model_dump(mode="json")
        codes = [item["code"] for item in specification["requirements"]]
        _, history = client.call("GET", base + "/design")
        packages = [version["package"] for version in history]
        current = project.current("design")
        if hosted:
            _, started = client.call(
                "POST",
                base + "/design/iterations/jobs",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                    "request": "Metti il pulsante in alto",
                },
            )
            _, iteration = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
            packages.append(iteration["result"]["package"])
            other = next(
                item["id"]
                for item in current["package"]["alternatives"]
                if item["id"] != current["package"]["owner_selected_alternative_id"]
            )
            _, started = client.call(
                "POST",
                base + "/design/mockups/jobs",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                    "alternative_id": other,
                },
            )
            _, mockup = client.call("GET", f"{base}/design/mockups/jobs/{started['job_id']}")
            packages.append(mockup["result"]["package"])
            status, run = client.call(
                "POST",
                base + "/design/evaluations",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                },
            )
            assert status == 201
            findings = [
                finding for response in run["responses"] for finding in response["findings"]
            ]
            assert findings
            for finding in findings:
                assert synthetic_finding_from_snapshot(finding).to_snapshot() == finding
        assert len(packages) == (4 if hosted else 2)
        for package in packages:
            canonical_design(package, codes)
        assert studio.errors == []


def signed(studio: FakeStudio) -> _Client:
    studio.add_account(EMAIL, PASSWORD)
    client = _Client(studio)
    _, login = client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    client.token = str(login["access_token"])
    return client


def test_the_answers_of_a_studio_without_a_model_fit_the_real_models() -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        ready = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        created = fits(
            DesignGenerationPayload,
            client.call("POST", f"/projects/{ready.id}/design/proposals"),
            201,
        )
        package = created["version"]["package"]
        DesignPackagePayload.model_validate(package).to_domain()
        assert [item["code"] for item in package["alternatives"]] == [
            "DES-001",
            "DES-002",
            "DES-003",
        ]
        fits(
            MockupCapabilities,
            client.call("GET", f"/projects/{ready.id}/design/mockups/capabilities"),
        )
        old = studio.seed_project(
            owner=EMAIL,
            name="Squadra vecchia",
            through="requirements",
            team_without=["UX_UI_DESIGNER"],
        )
        fits(
            TeamProposalVersionResponse,
            client.call("GET", f"/projects/{old.id}/team-proposals/current"),
        )
        status, refused = client.call("POST", f"/projects/{old.id}/design/proposals")
        assert status == 409
        assert set(refused["detail"]) == {"code", "proposal_issue"}
        assert DesignProposalIssueCode(refused["detail"]["proposal_issue"])
        project = fits(
            ProjectResponse,
            client.call(
                "POST", "/projects", {"display_name": "Archivio", "mode": "GREENFIELD_GENERATION"}
            ),
            201,
        )
        base = f"/projects/{project['id']}"
        fields = {
            "name": "Archivio",
            "description": "Una app con database ma senza backend.",
            "problem": "Le ricette sono sparse.",
            "goals": ["Ritrovare una ricetta"],
            "target_users": ["Cuochi"],
            "functional_requirements": ["Cercare una ricetta"],
            "unknown_fields": [
                "domain",
                "technical_constraints",
                "temporal_constraints",
                "budget",
                "non_functional_requirements",
                "risks",
                "stakeholders",
                "available_artifacts",
                "definition_of_done",
            ],
        }
        assert client.call("POST", base + "/brief-versions", fields)[0] == 201
        assert client.call("POST", base + "/gates/project-brief/submit")[0] == 201
        decided = client.call(
            "POST", base + "/gates/project-brief/decisions", {"action": "APPROVE"}
        )
        assert decided[0] == 200
        blocked = fits(
            TeamProposalGenerationResponse, client.call("POST", base + "/team-proposals"), 409
        )
        assert blocked["status"] == "BLOCKED_BY_CONSTRAINTS"
        assert blocked["issues"]
        assert studio.errors == []


def test_the_latest_mockup_has_the_keys_of_the_real_answer() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        chosen = project.current("design")["package"]["owner_selected_alternative_id"]
        status, latest = client.call(
            "GET", f"/projects/{project.id}/design/mockups?alternative_id={chosen}"
        )
        assert status == 200
        assert list(latest) == [
            "status",
            "generation_id",
            "design_version_id",
            "design_content_hash",
            "package",
            "approach",
            "changes",
            "warnings",
            "cost_microusd",
        ]
        DesignPackagePayload.model_validate(latest["package"]).to_domain()
        assert studio.errors == []


def _closed_unit_of_work() -> IdentityUnitOfWork:
    raise AssertionError("a refused registration opens no transaction")


def _owner() -> UserAccount:
    return UserAccount(
        id=UUID(int=1),
        email=NormalizedEmail(EMAIL),
        password_hash="hash-not-real",
        is_active=True,
        created_at=MOMENT,
        updated_at=MOMENT,
    )


@pytest.fixture
def real_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=_closed_unit_of_work,
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(jwt_secret=SecretStr(JWT_SECRET), _env_file=None)
        ),
    )
    application = create_app(
        ApplicationSettings(
            application_name="OrchesTwin Fake Studio Answer Test",
            environment=RuntimeEnvironment.TEST,
            debug=False,
            log_level=LogLevel.INFO,
            api_prefix=PREFIX,
            _env_file=None,
        ),
        runtime=ApplicationRuntime(identity_service=identity),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    application.dependency_overrides[current_user_dependency] = _owner
    with TestClient(application) as client:
        yield client


def _fake_logout(studio: FakeStudio) -> tuple[int, str | None, bytes, bool]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(studio.address + PREFIX + "/auth/logout", method="POST")
    with opener.open(request, timeout=10) as response:
        headers = {name.lower(): value for name, value in response.headers.items()}
        return (
            response.status,
            headers.get("content-type"),
            response.read(),
            "content-length" in headers,
        )


def test_the_added_routes_answer_like_the_real_application(real_client: TestClient) -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = _Client(studio)
        for body in REFUSED_REGISTRATIONS:
            real = real_client.post(PREFIX + "/auth/register", json=body)
            assert real.status_code == 422
            assert client.call("POST", "/auth/register", body) == (real.status_code, real.json())
        real_logout = real_client.post(PREFIX + "/auth/logout")
        assert _fake_logout(studio) == (
            real_logout.status_code,
            real_logout.headers.get("content-type"),
            real_logout.content,
            "content-length" in real_logout.headers,
        )
        created = fits(
            AuthenticationResponse,
            client.call(
                "POST", "/auth/register", {"email": "new@example.com", "password": PASSWORD}
            ),
            201,
        )
        client.token = str(created["access_token"])
        real_readiness = real_client.get(PREFIX + "/model-runtime/readiness")
        assert client.call("GET", "/model-runtime/readiness") == (
            real_readiness.status_code,
            real_readiness.json(),
        )
        assert studio.errors == []


OTHER = "other@example.com"
PREFER = {"Prefer": "respond-async"}
CHANGE_KEYS = [
    "commit",
    "parent",
    "committed_at",
    "author",
    "message",
    "files",
    "recorded_at",
    "review",
    "decision",
]
RUN_KEYS = [
    "id",
    "commit",
    "reviewed_at",
    "locale",
    "reference",
    "critiques",
    "alignment",
    "cost_microusd",
]
ALIGNMENT_KEYS = [
    "project_id",
    "reference",
    "aligned",
    "pending_changes",
    "latest_change",
    "tasks",
    "review_available",
]
FIRST_GOALS = {"it": "Chiudere il conto in fretta", "en": "Settle the bill quickly"}
LOCALE = {"it": "it-IT", "en": "en-US"}
DIFF = "diff --git a/src/app.js b/src/app.js\n+// REQ-999 is not known, REQ-003 splits the bill\n"
FILE = {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}
LIMITS = (
    ({"commit": "abc123"}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": "a" * 65}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": "z" * 40}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": 7}, ["body", "commit"], "string_type"),
    ({"parent": "not-a-hash"}, ["body", "parent"], "string_pattern_mismatch"),
    ({"committed_at": "2026-09-29T10:15:00"}, ["body", "committed_at"], "timezone_aware"),
    ({"committed_at": "yesterday"}, ["body", "committed_at"], "datetime_from_date_parsing"),
    ({"author": "a" * 201}, ["body", "author"], "string_too_long"),
    ({"author": "Ann\x01"}, ["body", "author"], "value_error"),
    ({"message": ""}, ["body", "message"], "string_too_short"),
    ({"message": " \n "}, ["body", "message"], "value_error"),
    ({"message": "m" * 2001}, ["body", "message"], "string_too_long"),
    ({"files": [{**FILE, "kind": "MOVED"}]}, ["body", "files", 0, "kind"], "enum"),
    ({"files": [{**FILE, "path": ""}]}, ["body", "files", 0, "path"], "string_too_short"),
    ({"files": [{**FILE, "path": "   "}]}, ["body", "files", 0, "path"], "value_error"),
    ({"files": [{**FILE, "path": "p" * 501}]}, ["body", "files", 0, "path"], "string_too_long"),
    ({"files": [{**FILE, "added": -1}]}, ["body", "files", 0, "added"], "greater_than_equal"),
    ({"files": [{**FILE, "lines": 3}]}, ["body", "files", 0, "lines"], "extra_forbidden"),
    ({"files": ["src/app.js"]}, ["body", "files", 0], "model_attributes_type"),
    ({"files": [FILE] * 501}, ["body", "files"], "too_long"),
    ({"files": None}, ["body", "files"], "list_type"),
    ({"diff": "d" * 65537}, ["body", "diff"], "string_too_long"),
    ({"diff": "a\x00b"}, ["body", "diff"], "value_error"),
    ({"branch": "main"}, ["body", "branch"], "extra_forbidden"),
)
REVIEW_REFUSALS = (
    ({"locale": "x"}, ["body", "locale"], "string_too_short"),
    ({"locale": "x" * 21}, ["body", "locale"], "string_too_long"),
    ({"locale": "french"}, ["body", "locale"], "string_pattern_mismatch"),
    ({"again": "maybe"}, ["body", "again"], "bool_parsing"),
    ({"again": [True]}, ["body", "again"], "bool_type"),
    ({"prefer": "sync"}, ["body", "prefer"], "extra_forbidden"),
    (None, ["body"], "missing"),
)
DECISION_REFUSALS = (
    ({}, ["body", "kind"], "missing"),
    ({"kind": "LATER"}, ["body", "kind"], "enum"),
    ({"kind": "CODE_TASKS"}, ["body"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": []}, ["body"], "value_error"),
    ({"kind": "ALIGNED", "tasks": ["Uno"]}, ["body"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": ["Uno"] * 11}, ["body", "tasks"], "too_long"),
    ({"kind": "CODE_TASKS", "tasks": [""]}, ["body", "tasks", 0], "string_too_short"),
    ({"kind": "CODE_TASKS", "tasks": ["t" * 301]}, ["body", "tasks", 0], "string_too_long"),
    ({"kind": "CODE_TASKS", "tasks": [" \t "]}, ["body", "tasks"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": None}, ["body", "tasks"], "list_type"),
    ({"kind": "DISMISSED", "note": "n" * 2001}, ["body", "note"], "string_too_long"),
    ({"kind": "DISMISSED", "note": "a\x00"}, ["body", "note"], "value_error"),
    ({"kind": "DISMISSED", "reason": "x"}, ["body", "reason"], "extra_forbidden"),
)


def commit_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def change_body(commit: str, message: str = "Add the split of the bill", **changes: object) -> dict:
    body: dict[str, object] = {
        "commit": commit,
        "parent": None,
        "committed_at": "2026-09-29T10:15:00+02:00",
        "author": "Test Author",
        "message": message,
        "files": [dict(FILE)],
        "diff": DIFF,
    }
    body.update(changes)
    return body


def refused(code: str) -> dict:
    return {"detail": {"code": code}}


def invalid(location: list[object], kind: str) -> dict:
    return {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]}


def record(
    client: _Client, base: str, commit: str, message: str = "Add the split of the bill", **changes
) -> dict:
    status, created = client.call(
        "POST", base + "/code-changes", change_body(commit, message, **changes)
    )
    assert status == 201, created
    return created["change"]


def stranger(studio: FakeStudio) -> _Client:
    studio.add_account(OTHER, PASSWORD)
    client = _Client(studio)
    _, login = client.call("POST", "/auth/login", {"email": OTHER, "password": PASSWORD})
    client.token = str(login["access_token"])
    return client


def poll(client: _Client, base: str, job_id: str) -> dict:
    for _ in range(10):
        status, job = client.call("GET", f"{base}/generation-jobs/{job_id}")
        assert status == 200, job
        if job["status"] != "RUNNING":
            return job
    raise AssertionError("the job never ended")


def test_a_change_is_recorded_once_and_read_back_by_its_prefix() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        first, second = commit_of("first"), commit_of("second")
        status, created = client.call("POST", base + "/code-changes", change_body(first.upper()))
        change = created["change"]
        assert (status, created["status"], list(change)) == (201, "RECORDED", CHANGE_KEYS)
        assert [changed_file_from_snapshot(item).to_snapshot() for item in change["files"]] == [
            FILE
        ]
        assert change == {
            "commit": first,
            "parent": None,
            "committed_at": "2026-09-29T08:15:00+00:00",
            "author": "Test Author",
            "message": "Add the split of the bill",
            "files": [FILE],
            "recorded_at": change["recorded_at"],
            "review": None,
            "decision": None,
        }
        assert datetime.fromisoformat(change["recorded_at"]).utcoffset() == timedelta(0)
        repeated = client.call("POST", base + "/code-changes", change_body(first, "Other words"))
        assert repeated == (200, {"status": "ALREADY_RECORDED", "change": change})
        later = record(client, base, second, "Show the shares", parent=first.upper())
        assert later["parent"] == first
        assert client.call("GET", base + "/code-changes") == (200, {"items": [later, change]})
        assert project.changes() == [later, change]
        assert client.call("GET", f"{base}/code-changes/{first[:7]}") == (
            200,
            {**change, "diff": DIFF},
        )
        assert client.call("GET", f"{base}/code-changes/{second.upper()}")[1]["commit"] == second
        assert client.call("GET", f"{base}/code-changes/{'0' * 40}") == (
            404,
            refused("CODE_CHANGE_NOT_FOUND"),
        )
        for malformed in ("abc", "not-a-commit", "g" * 40):
            assert client.call("GET", f"{base}/code-changes/{malformed}") == (
                404,
                refused("CODE_CHANGE_NOT_FOUND"),
            )
        similar = ("abcdef1" + "0" * 33, "abcdef1" + "1" * 33)
        for commit in similar:
            record(client, base, commit)
        assert client.call("GET", f"{base}/code-changes/abcdef1") == (
            409,
            refused("CODE_CHANGE_AMBIGUOUS"),
        )
        assert client.call("GET", f"{base}/code-changes/abcdef11")[1]["commit"] == similar[1]
        other = stranger(studio)
        for path in ("/alignment", "/code-changes", f"/code-changes/{first}"):
            assert other.call("GET", base + path) == (404, refused("PROJECT_NOT_FOUND"))
        assert other.call("GET", f"{base}/code-changes/{first}/reviews") == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert other.call("POST", base + "/code-changes", change_body(first)) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert other.call(
            "POST", f"{base}/code-changes/{first}/decision", {"kind": "DISMISSED"}
        ) == (404, refused("PROJECT_NOT_FOUND"))
        assert studio.errors == []


def test_a_change_outside_the_limits_answers_422() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        commit = commit_of("limits")
        for changes, location, kind in LIMITS:
            reply = client.call("POST", base + "/code-changes", {**change_body(commit), **changes})
            assert reply == (422, invalid(location, kind)), changes
        same = client.call(
            "POST", base + "/code-changes", change_body(commit, parent=commit.upper())
        )
        assert same == (422, invalid(["body"], "value_error"))
        assert client.call("POST", base + "/code-changes") == (422, invalid(["body"], "missing"))
        assert project.changes() == []
        short = {
            key: value
            for key, value in change_body(commit, "  Add the split\n\n").items()
            if key not in {"parent", "author", "diff", "files"}
        }
        status, created = client.call("POST", base + "/code-changes", short)
        assert status == 201
        assert {
            key: created["change"][key] for key in ("parent", "author", "message", "files")
        } == {
            "parent": None,
            "author": None,
            "message": "Add the split",
            "files": [],
        }
        assert client.call("GET", f"{base}/code-changes/{commit}")[1]["diff"] == ""
        spaced = change_body(commit_of("spaced"), author="  Test \t Author  ")
        assert client.call("POST", base + "/code-changes", spaced)[1]["change"]["author"] == (
            "Test Author"
        )
        blank = change_body(commit_of("blank"), author="   ")
        assert client.call("POST", base + "/code-changes", blank)[1]["change"]["author"] is None
        largest = change_body(
            "b" * 64,
            "m" * 2000,
            author="a" * 200,
            files=[{**FILE, "path": "p" * 500}] * 500,
            diff="d" * 65536,
        )
        status, created = client.call("POST", base + "/code-changes", largest)
        assert (status, len(created["change"]["files"])) == (201, 500)
        assert record(client, base, "C" * 7)["commit"] == "c" * 7
        assert [item["commit"] for item in project.changes()] == [
            "c" * 7,
            "b" * 64,
            commit_of("blank"),
            commit_of("spaced"),
            commit,
        ]
        assert studio.errors == []


def test_changes_recorded_at_the_same_moment_are_ordered_like_the_real_list() -> None:
    moment = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    with FakeStudio(now=lambda: moment, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        early, late = "1" * 40, "2" * 40
        record(client, base, late, committed_at="2026-09-29T08:30:00+00:00")
        record(client, base, early, committed_at="2026-09-29T08:00:00+00:00")
        record(client, base, "3" * 40, committed_at="2026-09-29T08:30:00+00:00")
        assert [item["commit"] for item in project.changes()] == ["3" * 40, late, early]
        assert studio.errors == []


@pytest.mark.parametrize("hosted", [True, False])
def test_the_alignment_gives_the_reference_and_the_development_state(hosted: bool) -> None:
    with FakeStudio(hosted=hosted, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        requirements = project.current("requirements")
        design = project.current("design")
        package = design["package"]
        chosen = next(
            item["code"]
            for item in package["alternatives"]
            if item["id"] == package["owner_selected_alternative_id"]
        )
        status, alignment = client.call("GET", base + "/alignment")
        assert (status, list(alignment)) == (200, ALIGNMENT_KEYS)
        assert alignment == {
            "project_id": project.id,
            "reference": {
                "requirements": {
                    "version_id": requirements["id"],
                    "version_number": 1,
                    "content_hash": requirements["content_hash"],
                },
                "design": {
                    "version_id": design["id"],
                    "version_number": 2,
                    "content_hash": design["content_hash"],
                    "alternative_code": chosen,
                },
            },
            "aligned": None,
            "pending_changes": 0,
            "latest_change": None,
            "tasks": [],
            "review_available": hosted,
        }
        assert chosen == ("DES-002" if hosted else "DES-001")
        record(client, base, commit_of("one"))
        latest = record(client, base, commit_of("two"), "Show the shares")
        _, alignment = client.call("GET", base + "/alignment")
        assert (alignment["pending_changes"], alignment["latest_change"]) == (2, latest)
        for through, present in (("requirements", ["requirements"]), ("brief", [])):
            earlier = studio.seed_project(owner=EMAIL, name=f"Fino a {through}", through=through)
            _, other = client.call("GET", f"/projects/{earlier.id}/alignment")
            assert [stage for stage, value in other["reference"].items() if value] == present
            assert other["review_available"] is hosted
        assert studio.errors == []


@pytest.mark.parametrize(
    ("language", "message", "verdict"),
    [
        ("en", "Add the split of the bill", "ALIGNED"),
        ("it", "Nuova schermata per il design del risultato", "DESIGN_OUTDATED"),
        ("en", "Cover a new Requirement for the tip", "REQUIREMENTS_OUTDATED"),
        ("it", "Aggiunto il requisito del bis", "REQUIREMENTS_OUTDATED"),
        ("en", "Fix the drift of the form", "CODE_DRIFT"),
    ],
)
def test_a_review_follows_the_rules_of_the_fake(language: str, message: str, verdict: str) -> None:
    with FakeStudio(language=language, twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of(message)
        record(client, base, commit, f"{message}\n\nMore words in the body.")
        status, reviewed = client.call(
            "POST", f"{base}/code-changes/{commit[:10]}/reviews", {"locale": LOCALE[language]}
        )
        assert (status, reviewed["status"]) == (201, "REVIEWED")
        run = reviewed["run"]
        assert list(run) == RUN_KEYS
        assert (run["commit"], run["locale"]) == (commit, LOCALE[language])
        assert run["reference"] == {
            "requirements_version_number": 1,
            "design_version_number": 2,
            "alternative_code": "DES-002",
        }
        twins = project.current("twins")["snapshot"]["twin_versions"]
        critiques = run["critiques"]
        assert [(item["twin_id"], item["twin_name"]) for item in critiques] == [
            (twin["twin_id"], twin["profile"]["name"]) for twin in twins
        ]
        assert [item["verdict"] for item in critiques] == ["CONCERN", "FINE", "FINE"]
        assert [
            [(finding["severity"], finding["about"]) for finding in item["findings"]]
            for item in critiques
        ] == [
            [
                ("MEDIUM", {"requirement": "REQ-003", "screen": None, "file": "src/app.js"}),
                ("LOW", {"requirement": None, "screen": "SCR-001", "file": None}),
            ],
            [("LOW", {"requirement": "REQ-003", "screen": "SCR-001", "file": None})],
            [],
        ]
        for item in critiques:
            assert twin_critique_from_snapshot(item).to_snapshot() == item
            assert FIRST_GOALS[language] in item["summary"]
            assert message in item["summary"]
            assert "More words" not in item["summary"]
            for finding in item["findings"]:
                assert finding["text"] and finding["action"]
        alignment = run["alignment"]
        assert alignment_verdict_from_snapshot(alignment).to_snapshot() == alignment
        assert alignment["status"] == verdict
        assert message in alignment["summary"]
        assert alignment["affected"] == {"requirements": ["REQ-003"], "screens": ["SCR-001"]}
        assert (alignment["design_request"] is not None) is (verdict == "DESIGN_OUTDATED")
        assert (alignment["requirements_request"] is not None) is (
            verdict == "REQUIREMENTS_OUTDATED"
        )
        assert len(alignment["code_tasks"]) == (2 if verdict == "CODE_DRIFT" else 0)
        cost = 3 * COSTS["CODE_CHANGE_REVIEW"] + COSTS["CODE_ALIGNMENT"]
        assert run["cost_microusd"] == cost == 850_000
        assert studio.spent_microusd == project.spent_microusd == cost
        _, usage = client.call("GET", base + "/model-usage")
        assert [(item["purpose"], item["cost_microusd"]) for item in reversed(usage["items"])] == [
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_ALIGNMENT", 250_000),
        ]
        assert {item["task"] for item in usage["items"]} == {"user-twin-evaluation"}
        assert project.change_reviews() == [run]
        _, change = client.call("GET", f"{base}/code-changes/{commit}")
        assert change["review"] == {
            "run_id": run["id"],
            "reviewed_at": run["reviewed_at"],
            "verdict": verdict,
            "summary": alignment["summary"],
        }
        assert studio.errors == []


@pytest.mark.parametrize(
    ("diff", "requirement"),
    [
        (DIFF, "REQ-003"),
        ("+// REQ-002 and REQ-004 are both here\n", "REQ-002"),
        ("+// REQ-999 is the only code\n", "REQ-001"),
        ("", "REQ-001"),
    ],
)
def test_the_first_finding_cites_the_first_known_requirement_of_the_diff(
    diff: str, requirement: str
) -> None:
    with FakeStudio(language="en", twins=1, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of(diff)
        record(client, base, commit, diff=diff, files=[])
        _, reviewed = client.call(
            "POST", f"{base}/code-changes/{commit}/reviews", {"locale": "en-US"}
        )
        (critique,) = reviewed["run"]["critiques"]
        assert [finding["about"] for finding in critique["findings"]] == [
            {"requirement": requirement, "screen": None, "file": None},
            {"requirement": None, "screen": "SCR-001", "file": None},
        ]
        assert reviewed["run"]["alignment"]["affected"] == {
            "requirements": [requirement],
            "screens": ["SCR-001"],
        }
        assert reviewed["run"]["cost_microusd"] == 450_000


def test_a_second_review_repeats_the_content_in_a_new_run() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("again")
        record(client, base, commit, "Cambia il design del risultato")
        path = f"{base}/code-changes/{commit}/reviews"
        _, first = client.call("POST", path, {"locale": "it-IT"})
        status, second = client.call("POST", path, {"locale": "it-IT", "again": True})
        assert status == 201
        older, newer = first["run"], second["run"]
        assert newer["id"] != older["id"]
        assert datetime.fromisoformat(newer["reviewed_at"]) > datetime.fromisoformat(
            older["reviewed_at"]
        )
        same = ("commit", "locale", "reference", "critiques", "alignment", "cost_microusd")
        assert {key: newer[key] for key in same} == {key: older[key] for key in same}
        assert newer["alignment"]["status"] == "DESIGN_OUTDATED"
        assert client.call("GET", path) == (200, {"items": [newer, older]})
        assert project.change_reviews() == [newer, older]
        _, change = client.call("GET", f"{base}/code-changes/{commit}")
        assert change["review"]["run_id"] == newer["id"]
        assert studio.spent_microusd == 2 * 650_000
        for body, location, kind in REVIEW_REFUSALS:
            assert client.call("POST", path, body) == (422, invalid(location, kind)), body
        assert client.call("POST", path, {}) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        _, french = client.call("POST", path, {"locale": "fr-FR", "again": "yes"})
        _, default = client.call("POST", path, {"again": 1})
        assert (french["run"]["locale"], default["run"]["locale"]) == ("fr-FR", "it-IT")
        assert len(project.change_reviews()) == 4
        assert studio.errors == []


def test_the_refusals_of_a_review_come_in_the_order_of_the_contract() -> None:
    body = {"locale": "it-IT"}
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("refusals")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        assert stranger(studio).call("POST", f"{base}/code-changes/{'0' * 40}/reviews", body) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert client.call("POST", f"{base}/code-changes/{'0' * 40}/reviews", body) == (
            404,
            refused("CODE_CHANGE_NOT_FOUND"),
        )
        for similar in ("abcdef1" + "0" * 33, "abcdef1" + "1" * 33):
            record(client, base, similar)
        assert client.call("POST", f"{base}/code-changes/abcdef1/reviews", body) == (
            409,
            refused("CODE_CHANGE_AMBIGUOUS"),
        )
        assert client.call("POST", path, body)[0] == 201
        assert client.call("POST", path, body) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        edit = client.call(
            "PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited}
        )
        assert edit[0] == 201
        assert project.approved("design") and not project.approved("twins")
        assert client.call("POST", path, body) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        assert client.call("POST", path, {**body, "again": True}) == (
            409,
            refused("USER_MODELING_APPROVAL_REQUIRED"),
        )
        assert studio.spent_microusd == 650_000
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        expected = (
            ("twins", 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
            ("requirements", 409, "DESIGN_APPROVAL_REQUIRED"),
            ("design", 503, "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"),
        )
        for through, status, code in expected:
            project = studio.seed_project(owner=EMAIL, name=f"Fino a {through}", through=through)
            base = f"/projects/{project.id}"
            commit = commit_of(through)
            record(client, base, commit)
            path = f"{base}/code-changes/{commit}/reviews"
            assert client.call("POST", path, body) == (status, refused(code))
            started = client.call("POST", path, body, headers=PREFER)
            assert started[0] == 202
            job = poll(client, base, started[1]["job_id"])
            assert (job["status"], job["response"]) == (
                "FAILED",
                {"status_code": status, "body": refused(code)},
            )
            assert project.change_reviews() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_a_review_that_passes_the_ceiling_is_not_stored() -> None:
    exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(budget_usd=1.0, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("ceiling")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        assert client.call("POST", path, {"locale": "it-IT"})[0] == 201
        assert studio.spent_microusd == 650_000
        refused_review = client.call("POST", path, {"locale": "it-IT", "again": True})
        assert refused_review == (402, exceeded)
        assert studio.spent_microusd == 1_000_000 - 150_000
        started = client.call("POST", path, {"locale": "it-IT", "again": True}, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])
        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 402, "body": exceeded},
        )
        assert len(project.change_reviews()) == 1
        _, usage = client.call("GET", base + "/model-usage")
        assert usage["totals"]["cost_microusd"] == studio.spent_microusd
        assert studio.errors == []


def test_a_review_with_prefer_runs_as_a_request_job() -> None:
    body = {"locale": "en-US", "again": False}
    with FakeStudio(language="en", job_polls=2) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        commits = [commit_of(f"job {index}") for index in range(5)]
        for commit in commits:
            record(client, base, commit)
        path = f"{base}/code-changes/{commits[0]}/reviews"
        status, started = client.call("POST", path, body, headers=PREFER)
        assert (status, client.headers["preference-applied"]) == (202, "respond-async")
        assert (started["kind"], started["operation"], started["status"]) == (
            "REQUEST",
            "CODE_CHANGE_REVIEW",
            "RUNNING",
        )
        assert client.call("POST", path, body, headers=PREFER)[1]["job_id"] == started["job_id"]
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert studio._jobs[started["job_id"]].key == (
            f"CODE_CHANGE_REVIEW:commit={commits[0]}:{digest}"
        )
        again = client.call("POST", path, {**body, "again": True}, headers=PREFER)
        assert again[1]["job_id"] != started["job_id"]
        job_path = f"{base}/generation-jobs/{started['job_id']}"
        statuses = [client.call("GET", job_path)[1]["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        _, finished = client.call("GET", job_path)
        assert finished["response"] == {
            "status_code": 201,
            "body": {"status": "REVIEWED", "run": project.change_reviews()[0]},
        }
        for commit in commits[1:4]:
            later = client.call(
                "POST", f"{base}/code-changes/{commit}/reviews", body, headers=PREFER
            )
            assert later[0] == 202
        busy = client.call(
            "POST", f"{base}/code-changes/{commits[4]}/reviews", body, headers=PREFER
        )
        assert busy == (429, refused("TOO_MANY_GENERATIONS"))
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("failures")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        studio.fail_job("CODE_CHANGE_REVIEW", code="TIMEOUT")
        failed = poll(client, base, client.call("POST", path, body, headers=PREFER)[1]["job_id"])
        assert (failed["status"], failed["response"]) == (
            "FAILED",
            {
                "status_code": 503,
                "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
            },
        )
        studio.lose_job("CODE_CHANGE_REVIEW")
        lost = client.call("POST", path, body, headers=PREFER)[1]
        assert client.call("GET", f"{base}/generation-jobs/{lost['job_id']}") == (
            404,
            refused("GENERATION_JOB_NOT_FOUND"),
        )
        assert project.change_reviews() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_decisions_set_the_aligned_point_and_the_tasks() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        first, second, third = (commit_of(name) for name in ("first", "second", "third"))
        for commit in (first, second, third):
            record(client, base, commit)

        def decide(commit: str, body: object) -> tuple[int, object]:
            return client.call("POST", f"{base}/code-changes/{commit}/decision", body)

        assert client.call("POST", f"{base}/code-changes/{first}/reviews", {})[0] == 201
        texts = [
            "  Riportare il codice   in linea con la schermata SCR-002. ",
            "Coprire REQ-003 con un test automatico.",
        ]
        status, decided = decide(
            first[:8], {"kind": "CODE_TASKS", "note": "  Da fare\n", "tasks": texts}
        )
        assert (status, list(decided)) == (200, ["status", "change", "alignment"])
        assert decided["status"] == "DECIDED"
        moment = decided["change"]["decision"]["decided_at"]
        assert decided["change"]["decision"] == {
            "kind": "CODE_TASKS",
            "decided_at": moment,
            "note": "Da fare",
        }
        assert decided["alignment"] == client.call("GET", base + "/alignment")[1]
        subjects = {"requirements": ["REQ-003"], "screens": ["SCR-001"]}
        assert decided["alignment"]["tasks"] == [
            {
                "code": "TSK-001",
                "text": "Riportare il codice in linea con la schermata SCR-002.",
                "about": subjects,
                "from_commit": first,
                "created_at": moment,
                "status": "OPEN",
            },
            {
                "code": "TSK-002",
                "text": texts[1],
                "about": subjects,
                "from_commit": first,
                "created_at": moment,
                "status": "OPEN",
            },
        ]
        assert decided["alignment"]["pending_changes"] == 3
        _, aligned = decide(second, {"kind": "ALIGNED"})
        point = {
            "commit": second,
            "decided_at": aligned["change"]["decision"]["decided_at"],
            "requirements_version_number": 1,
            "design_version_number": 2,
        }
        assert aligned["change"]["decision"]["note"] is None
        assert (aligned["alignment"]["aligned"], aligned["alignment"]["pending_changes"]) == (
            point,
            1,
        )
        assert aligned["alignment"]["tasks"] == []
        assert [task["status"] for task in project.tasks()] == ["DONE", "DONE"]
        assert project.aligned() == point
        pending = client.call("GET", base + "/code-changes?pending=true")[1]["items"]
        assert [item["commit"] for item in pending] == [third]
        everything = client.call("GET", base + "/code-changes?pending=0")[1]["items"]
        assert [item["commit"] for item in everything] == [third, second, first]
        assert client.call("GET", base + "/code-changes?pending=maybe") == (
            422,
            {
                "detail": "invalid_request",
                "errors": [{"loc": ["query", "pending"], "type": "bool_parsing"}],
            },
        )
        assert decide(third, {"kind": "ALIGNED"})[1]["alignment"]["pending_changes"] == 0
        _, dismissed = decide(third, {"kind": "DISMISSED", "note": " \n "})
        assert dismissed["change"]["decision"]["note"] is None
        assert dismissed["alignment"]["aligned"] == point
        assert dismissed["alignment"]["pending_changes"] == 1
        for kind in ("DESIGN_CHANGE", "REQUIREMENTS_CHANGE"):
            _, recorded = decide(third, {"kind": kind, "note": "Nuova versione"})
            assert recorded["change"]["decision"]["kind"] == kind
            assert recorded["alignment"]["aligned"] == point
        _, more = decide(third, {"kind": "CODE_TASKS", "tasks": ["Rifare il riepilogo."]})
        assert more["alignment"]["tasks"] == [
            {
                "code": "TSK-003",
                "text": "Rifare il riepilogo.",
                "about": {"requirements": [], "screens": []},
                "from_commit": third,
                "created_at": more["change"]["decision"]["decided_at"],
                "status": "OPEN",
            }
        ]
        assert [task["code"] for task in project.tasks()] == ["TSK-001", "TSK-002", "TSK-003"]
        for body, location, kind in DECISION_REFUSALS:
            assert decide(first, body) == (422, invalid(location, kind)), body
        assert decide("0" * 40, {"kind": "ALIGNED"}) == (404, refused("CODE_CHANGE_NOT_FOUND"))
        largest = decide(
            first, {"kind": "CODE_TASKS", "tasks": ["t" * 300] * 10, "note": "n" * 2000}
        )
        assert largest[0] == 200
        assert len(project.tasks()) == 13
        assert project.aligned() == point
        assert studio.spent_microusd == 650_000
        assert studio.errors == []


def test_an_aligned_decision_closes_only_the_tasks_of_that_change_and_older_ones() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        older, middle, newer = (commit_of(name) for name in ("older", "middle", "newer"))
        for commit in (older, middle, newer):
            record(client, base, commit)

        def decide(commit: str, body: object) -> dict:
            status, answer = client.call("POST", f"{base}/code-changes/{commit}/decision", body)
            assert status == 200, answer
            return answer

        def statuses() -> list[tuple[str, str, str]]:
            return [(task["code"], task["from_commit"], task["status"]) for task in project.tasks()]

        for commit, text in ((older, "Primo."), (middle, "Secondo."), (newer, "Terzo.")):
            decide(commit, {"kind": "CODE_TASKS", "tasks": [text]})
        aligned = decide(middle, {"kind": "ALIGNED"})
        assert statuses() == [
            ("TSK-001", older, "DONE"),
            ("TSK-002", middle, "DONE"),
            ("TSK-003", newer, "OPEN"),
        ]
        assert [task["code"] for task in aligned["alignment"]["tasks"]] == ["TSK-003"]
        assert aligned["alignment"]["pending_changes"] == 1
        decide(older, {"kind": "CODE_TASKS", "tasks": ["Quarto."]})
        assert statuses()[3] == ("TSK-004", older, "OPEN")
        again = decide(middle, {"kind": "ALIGNED"})
        assert [task["code"] for task in again["alignment"]["tasks"]] == ["TSK-003"]
        assert statuses()[3] == ("TSK-004", older, "DONE")
        closed = decide(newer, {"kind": "ALIGNED"})
        assert closed["alignment"]["tasks"] == []
        assert [status for _, _, status in statuses()] == ["DONE"] * 4
        assert studio.errors == []


def test_invalid_alignment_requests_answer_like_the_real_application(
    real_client: TestClient,
) -> None:
    commit = commit_of("compared")
    cases = [
        *(("POST", "/code-changes", {**change_body(commit), **item[0]}) for item in LIMITS),
        ("POST", "/code-changes", change_body(commit, parent=commit.upper())),
        ("POST", "/code-changes", None),
        *(("POST", f"/code-changes/{commit}/reviews", item[0]) for item in REVIEW_REFUSALS),
        *(("POST", f"/code-changes/{commit}/decision", item[0]) for item in DECISION_REFUSALS),
        ("GET", "/code-changes?pending=maybe", None),
    ]
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        for method, path, body in cases:
            real = real_client.request(method, PREFIX + base + path, json=body)
            assert real.status_code == 422, (path, body, real.text)
            assert client.call(method, base + path, body) == (422, real.json()), (path, body)
        assert project.changes() == []
        assert studio.errors == []
