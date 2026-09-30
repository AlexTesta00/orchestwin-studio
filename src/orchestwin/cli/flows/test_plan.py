from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import jobs
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.errors import BUDGET_CODES, ApiFailure, CliError
from orchestwin.cli.project import json_bytes, read_json, write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

TESTS_FOLDER: Final = "tests"
PLAN_NAME: Final = "plan.json"
SCHEMA_VERSION: Final = 1
LIMIT_SECONDS: Final = 900.0
PAYMENT_REQUIRED: Final = 402
MICRO_USD: Final = 1_000_000
REQUIREMENTS_STAGE: Final = "requirements"
DESIGN_STAGE: Final = "design"
STALE_KEY: Final = "test.plan_stale"
UNCOVERED_KEY: Final = "test.plan_uncovered"


@dataclass(frozen=True, slots=True)
class SavedPlan:
    saved_at: str
    application: Mapping[str, object]
    plan: Mapping[str, object]
    replans: tuple[Mapping[str, object], ...] = ()

    @property
    def plan_id(self) -> str:
        return str(self.plan.get("id") or "")

    @property
    def replan_ids(self) -> list[str]:
        return [str(item["id"]) for item in self.replans if isinstance(item.get("id"), str)]

    @property
    def created_at(self) -> str | None:
        value = self.plan.get("created_at")
        return value if isinstance(value, str) else None

    def reference(self) -> tuple[int | None, int | None]:
        return reference_of(self.plan)

    def paths(self) -> list[Mapping[str, object]]:
        found = tests_api.mappings(self.plan.get("paths"))
        for replan in self.replans:
            replaced = set(tests_api.texts(replan.get("replan_of")))
            found = [path for path in found if path.get("code") not in replaced]
            found.extend(tests_api.mappings(replan.get("paths")))
        return found

    def not_covered(self) -> list[Mapping[str, object]]:
        seen: dict[str, Mapping[str, object]] = {}
        for source in (self.plan, *self.replans):
            for item in tests_api.mappings(source.get("not_covered")):
                code = item.get("criterion")
                if isinstance(code, str) and code not in seen:
                    seen[code] = item
        return list(seen.values())

    def criteria(self) -> list[str]:
        return tests_api.ordered(
            [
                code
                for source in (self.plan, *self.replans)
                for code in tests_api.texts(source.get("criteria"))
            ]
        )

    def covered(self) -> set[str]:
        named = {code for path in self.paths() for code in tests_api.texts(path.get("criteria"))}
        return named | {str(item["criterion"]) for item in self.not_covered()}

    def with_replan(self, replan: Mapping[str, object], *, saved_at: str) -> SavedPlan:
        return SavedPlan(
            saved_at=saved_at,
            application=self.application,
            plan=self.plan,
            replans=(*self.replans, replan),
        )

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at": self.saved_at,
            "application": dict(self.application),
            "plan": self.plan,
            "replans": list(self.replans),
        }


@dataclass(frozen=True, slots=True)
class PlanChoice:
    reuse: bool
    key: str | None = None
    values: Mapping[str, object] = field(default_factory=dict)


def tests_folder(project: ProjectFolder) -> Path:
    return project.local / TESTS_FOLDER


def plan_file(project: ProjectFolder) -> Path:
    return tests_folder(project) / PLAN_NAME


def read_plan(project: ProjectFolder) -> SavedPlan | None:
    return saved_plan_from(read_json(plan_file(project)))


def save_plan(project: ProjectFolder, saved: SavedPlan) -> Path:
    path = plan_file(project)
    write_atomically(path, json_bytes(saved.document()))
    return path


def saved_plan_from(document: object) -> SavedPlan | None:
    if not isinstance(document, Mapping) or document.get("schema_version") != SCHEMA_VERSION:
        return None
    plan = document.get("plan")
    replans = document.get("replans", [])
    if not valid_plan(plan) or not isinstance(replans, list):
        return None
    if not all(valid_plan(item) for item in replans):
        return None
    application = document.get("application")
    saved_at = document.get("saved_at")
    return SavedPlan(
        saved_at=saved_at if isinstance(saved_at, str) else "",
        application=application if isinstance(application, Mapping) else {},
        plan=plan,
        replans=tuple(replans),
    )


def valid_plan(plan: object) -> bool:
    if not isinstance(plan, Mapping):
        return False
    identifier = plan.get("id")
    paths = plan.get("paths")
    if not isinstance(identifier, str) or not identifier or not isinstance(paths, list):
        return False
    if not isinstance(plan.get("not_covered", []), list):
        return False
    return all(
        isinstance(path, Mapping)
        and isinstance(path.get("code"), str)
        and isinstance(path.get("steps"), list)
        for path in paths
    )


def reference_of(plan: Mapping[str, object]) -> tuple[int | None, int | None]:
    reference = plan.get("reference")
    reference = reference if isinstance(reference, Mapping) else {}
    requirements = reference.get("requirements_version_number")
    design = reference.get("design_version_number")
    return (_number(requirements), _number(design))


def decide(
    saved: SavedPlan | None,
    versions: tuple[int | None, int | None],
    criteria: Sequence[str],
    *,
    new: bool,
) -> PlanChoice:
    if new or saved is None:
        return PlanChoice(reuse=False)
    requirements, design = saved.reference()
    if (requirements, design) != tuple(versions):
        return PlanChoice(
            reuse=False,
            key=STALE_KEY,
            values={
                "plan_requirements": _shown(requirements),
                "plan_design": _shown(design),
                "requirements": _shown(versions[0]),
                "design": _shown(versions[1]),
            },
        )
    covered = saved.covered()
    missing = [code for code in criteria if code not in covered]
    if missing:
        return PlanChoice(reuse=False, key=UNCOVERED_KEY, values={"codes": ", ".join(missing)})
    return PlanChoice(reuse=True)


def plan_body(
    locale: str,
    application: Mapping[str, object],
    snapshot: Mapping[str, object],
    *,
    criteria: Sequence[str] | None = None,
    earlier: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "locale": locale,
        "application": dict(application),
        "snapshot": dict(snapshot),
        "criteria": None if criteria is None else list(criteria),
        "earlier": None if earlier is None else [dict(item) for item in earlier],
    }


def earlier_item(
    path: Mapping[str, object],
    blocked_step: int,
    detail: str | None,
    snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "code": path.get("code"),
        "heading": path.get("heading"),
        "criteria": tests_api.texts(path.get("criteria")),
        "steps": tests_api.mappings(path.get("steps")),
        "blocked_step": blocked_step,
        "detail": None if detail is None else detail[: tests_api.MAX_STEP_DETAIL_LENGTH],
        "snapshot": None if snapshot is None else dict(snapshot),
    }


def request_plan(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    body: Mapping[str, object],
    *,
    label: str,
) -> Mapping[str, object]:
    project_id = project.link().project_id
    result = jobs.generate(
        context,
        client,
        project_id,
        tests_api.plans_path(project_id),
        dict(body),
        label=label,
        limit_seconds=LIMIT_SECONDS,
    )
    if result.status_code < 400:
        return planned(result.body, result.status_code)
    raise refusal(
        context, client, project, result.status_code, result.body, tests_api.PLAN_OPERATION
    )


def planned(body: object, status: int) -> Mapping[str, object]:
    plan = body.get("plan") if isinstance(body, Mapping) else None
    if not valid_plan(plan):
        raise ApiFailure("API_FAILURE", http_status=status)
    return plan


def refusal(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    status: int,
    body: object,
    operation: str,
) -> CliError:
    failure = tests_api.failure(status, body)
    if status == PAYMENT_REQUIRED or failure.code in BUDGET_CODES:
        return budget_error(context, client, project, failure.code, operation)
    return failure


def budget_error(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    code: str,
    operation: str,
) -> CliError:
    from orchestwin.cli.commands.init import Journey

    journey = Journey(context, client, project, script=None, until=None, idea=None)
    return journey.budget_error(code, operation)


def plan_cost_usd(plan: Mapping[str, object], fallback: float) -> float:
    cost = plan.get("cost_microusd")
    if isinstance(cost, int) and not isinstance(cost, bool) and cost >= 0:
        return cost / MICRO_USD
    return fallback


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _shown(value: int | None) -> object:
    return "-" if value is None else value
