from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import design_generate, design_state, review
from orchestwin.cli.flows.publish import publish_and_pull

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_generate import Prices
    from orchestwin.cli.flows.design_state import Alternative, DesignState
    from orchestwin.cli.project import ProjectFolder

SELECTION_FIELDS: Final = (
    "owner_selected_alternative_id",
    "prototype",
    "generated_mockup",
    "owner_assertions",
)
PROPOSED: Final = "PROPOSED"
SUCCEEDED: Final = "SUCCEEDED"
RESULT_OPERATIONS: Final = frozenset({"MOCKUP", "ITERATION"})
ALREADY_APPROVED: Final = "ALREADY_APPROVED"
PENDING: Final = "DIFF_ALREADY_PENDING"
NO_CHANGES: Final = "NO_CHANGES"


def choose(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    alternative: Alternative,
    prices: Prices,
) -> int:
    console = context.console
    chosen = state.chosen
    if chosen is not None and chosen.id == alternative.id:
        console.say("design.already_chosen", code=alternative.code, title=alternative.title)
        return 0
    if prices.modelless(state):
        console.say("design.no_model_choice")
        return 1
    try:
        result = mockup_result(context, client, state, alternative)
    except ApiFailure as failure:
        if failure.code != design_api.NO_MOCKUP_MODEL:
            raise
        console.say("design.no_model_choice")
        return 1
    if result is None:
        if prices.shown():
            console.say("design.choose_needs_mockup", code=alternative.code)
        else:
            console.say("design.choose_needs_mockup_plain", code=alternative.code)
        return 1
    version = apply_package(client, state, choice_package(state, alternative, result))
    number = version.get("version_number") or "-"
    console.say("design.chosen", code=alternative.code, title=alternative.title, version=number)
    return review.review_after(
        context, client, project, key="design.choice_not_reviewed", number=number
    )


def mockup_result(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    alternative: Alternative,
) -> Mapping[str, object] | None:
    found = stored_result(client, state, alternative.id)
    if found is not None or state.generated:
        return found
    console = context.console
    console.say("design.about_declarative", code=alternative.code)
    label = context.text("design.label_declarative", code=alternative.code)
    try:
        with console.progress(label):
            result = design_api.declarative_mockup(
                client, state.project_id, state.version or {}, alternative.id
            )
            if not usable(result, alternative.id, generated=False):
                raise ApiFailure("API_FAILURE", http_status=200)
    except ApiFailure as failure:
        design_generate.raise_failure(failure)
    return result


def stored_result(
    client: StudioClient,
    state: DesignState,
    alternative_id: str,
    *,
    content_hash: str | None = None,
) -> Mapping[str, object] | None:
    latest = design_api.latest_mockup(client, state.project_id, alternative_id)
    if usable(latest, alternative_id, generated=state.generated, content_hash=content_hash):
        return latest
    for job in reversed(design_api.project_jobs(client, state.project_id)):
        if (
            job.get("status") != SUCCEEDED
            or job.get("operation") not in RESULT_OPERATIONS
            or job.get("alternative_id") != alternative_id
        ):
            continue
        result = job.get("result")
        if usable(result, alternative_id, generated=state.generated, content_hash=content_hash):
            return result
    return None


def usable(
    result: object,
    alternative_id: str,
    *,
    generated: bool,
    content_hash: str | None = None,
) -> bool:
    if not isinstance(result, Mapping):
        return False
    package = result.get("package")
    if not isinstance(package, Mapping):
        return False
    prototype = package.get("prototype")
    if (
        package.get("owner_selected_alternative_id") != alternative_id
        or not isinstance(prototype, Mapping)
        or prototype.get("design_alternative_id") != alternative_id
    ):
        return False
    if generated and not isinstance(package.get("generated_mockup"), Mapping):
        return False
    return content_hash is None or result.get("design_content_hash") == content_hash


def choice_package(
    state: DesignState, alternative: Alternative, result: Mapping[str, object]
) -> dict[str, object]:
    proposed = result.get("package")
    proposed = proposed if isinstance(proposed, Mapping) else {}
    version = state.version or {}
    if (result.get("design_version_id"), result.get("design_content_hash")) == (
        version.get("id"),
        version.get("content_hash"),
    ):
        return dict(proposed)
    package = dict(state.package)
    package["owner_selected_alternative_id"] = alternative.id
    package["prototype"] = proposed.get("prototype")
    package["generated_mockup"] = proposed.get("generated_mockup")
    return package


def apply_package(
    client: StudioClient, state: DesignState, package: Mapping[str, object]
) -> Mapping[str, object]:
    project_id = state.project_id
    try:
        answer = design_api.propose_revision(client, project_id, package)
    except ApiFailure as failure:
        if failure.code == NO_CHANGES and state.version is not None:
            return state.version
        if failure.code != PENDING:
            design_generate.raise_failure(failure)
        diff = pending_diff(client, state, package)
        if diff is None:
            raise CliError(PENDING) from failure
        return _decide(client, project_id, str(diff.get("id")))
    diff = answer.get("diff")
    identifier = diff.get("id") if isinstance(diff, Mapping) else None
    return _decide(client, project_id, str(identifier))


def pending_diff(
    client: StudioClient, state: DesignState, package: Mapping[str, object]
) -> Mapping[str, object] | None:
    base = None if state.version is None else state.version.get("id")
    wanted = _selection(package)
    for diff in design_api.revisions(client, state.project_id):
        proposed = diff.get("proposed_package")
        if (
            diff.get("status") == PROPOSED
            and diff.get("base_version_id") == base
            and isinstance(proposed, Mapping)
            and _selection(proposed) == wanted
        ):
            return diff
    return None


def approve(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
) -> int:
    console = context.console
    chosen = state.chosen
    if state.approved and chosen is not None:
        console.say(
            "design.already_approved",
            code=chosen.code,
            title=chosen.title,
            version=state.version_number or "-",
        )
        design_state.show_folder(context, client, project, state)
        return 0
    if chosen is None or state.version is None:
        console.say("design.approve_needs_choice")
        return 1
    try:
        submission = design_api.submit_gate(client, state.project_id)
        gate = submission.get("gate")
        if submission.get("status") != ALREADY_APPROVED:
            gate = design_api.decide_gate(client, state.project_id).get("gate")
    except ApiFailure as failure:
        design_generate.raise_failure(failure)
    project.save_step(
        "design",
        state.version,
        gate if isinstance(gate, Mapping) else None,
        context.environment.now(),
    )
    console.say(
        "design.approved",
        code=chosen.code,
        title=chosen.title,
        version=state.version_number or "-",
    )
    try:
        summary = publish_and_pull(context, client, project)
    except CliError:
        console.say("design.publish_later")
        raise
    console.say(
        "design.folder_ready",
        path=str(project.knowledge),
        version=summary.version_number,
        files=summary.file_count,
    )
    console.say("design.folder_contents")
    console.say("design.after_heading")
    design_state.show_next_commands(context)
    return 0


def _decide(client: StudioClient, project_id: str, diff_id: str) -> Mapping[str, object]:
    try:
        answer = design_api.decide_revision(client, project_id, diff_id)
    except ApiFailure as failure:
        design_generate.raise_failure(failure)
    version = answer.get("version")
    if not isinstance(version, Mapping):
        raise ApiFailure("API_FAILURE", http_status=200)
    return version


def _selection(package: Mapping[str, object]) -> str:
    return json.dumps(
        {name: package.get(name) or None for name in SELECTION_FIELDS},
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
