from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import modeling as modeling_api
from orchestwin.cli.api import twin_chat
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows.code_order import project_language
from orchestwin.cli.flows.design_state import bullets, wrapped
from orchestwin.cli.flows.review import places, review_locale
from orchestwin.cli.messages import text as message_text
from orchestwin.cli.project import LOCAL_FOLDER, read_json

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

MICRO_USD: Final = 1_000_000
CRITIQUE_KEYS: Final[Mapping[str, str]] = {
    changes_api.FINE: "align.critique_fine",
    changes_api.CONCERN: "align.critique_concern",
    changes_api.DRIFT: "align.critique_drift",
}
SEVERITY_KEYS: Final[Mapping[str, str]] = {
    "LOW": "align.severity_low",
    "MEDIUM": "align.severity_medium",
    "HIGH": "align.severity_high",
}
VERDICT_KEYS: Final[Mapping[str, str]] = {
    changes_api.ALIGNED: "align.verdict_aligned",
    changes_api.CODE_DRIFT: "align.verdict_code_drift",
    changes_api.DESIGN_OUTDATED: "align.verdict_design_outdated",
    changes_api.REQUIREMENTS_OUTDATED: "align.verdict_requirements_outdated",
}
REQUIREMENTS_DOCUMENT: Final = ("requirements", "requirements.json")
DESIGN_DOCUMENT: Final = ("design", "design.json")
TWINS_DOCUMENT: Final = ("twins", "twins.json")


@dataclass(frozen=True, slots=True)
class Workspace:
    project: ProjectFolder
    client: StudioClient
    project_id: str
    root: Path
    alignment: Mapping[str, object]
    hinted: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Titles:
    requirements: Mapping[str, str]
    screens: Mapping[str, str]


def prepare(context: CommandContext, *, repository: bool = True) -> Workspace:
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    link = project.link()
    client = context.client()
    session = context.sessions.read(client.studio)
    if session is None or not session.signed_in:
        raise CliError("NOT_SIGNED_IN", values={"studio": client.studio.origin})
    root = git.repository_root(context, project.root) if repository else project.root
    if root is None:
        raise CliError("ALIGN_NO_GIT", values={"folder": str(project.root)})
    document = changes_api.alignment(client, link.project_id)
    if changes_api.reference(document, "design") is None:
        raise CliError("ALIGN_DESIGN_REQUIRED")
    return Workspace(project, client, link.project_id, root, document)


def local_prefixes(workspace: Workspace) -> tuple[str, ...]:
    try:
        relative = workspace.project.root.resolve().relative_to(workspace.root.resolve())
    except (OSError, ValueError):
        return ()
    base = relative.as_posix()
    base = "" if base in ("", ".") else f"{base}/"
    folder = workspace.project.link().knowledge_folder
    return (f"{base}{LOCAL_FOLDER}/", f"{base}{folder}/")


def uncommitted(context: CommandContext, workspace: Workspace) -> bool:
    return git.uncommitted(context, workspace.root, ignored=local_prefixes(workspace))


def folder_only(commit: git.Commit, prefixes: Sequence[str]) -> bool:
    wanted = tuple(prefixes)
    return bool(commit.files and wanted) and all(
        item.path.startswith(wanted) for item in commit.files
    )


def folder_commits(workspace: Workspace, commits: Sequence[git.Commit]) -> list[git.Commit]:
    prefixes = local_prefixes(workspace)
    return [commit for commit in commits if folder_only(commit, prefixes)]


def dismiss_folder_commit(
    context: CommandContext,
    workspace: Workspace,
    commits: Sequence[git.Commit],
    folder: Sequence[git.Commit],
    known: Mapping[str, Mapping[str, object]],
) -> bool:
    if not commits or commits[-1].hash not in {commit.hash for commit in folder}:
        return False
    newest = commits[-1]
    change = known.get(newest.hash)
    if change is not None and changes_api.decision_of(change) is not None:
        return False
    changes_api.decide(
        workspace.client,
        workspace.project_id,
        newest.hash,
        changes_api.DISMISSED,
        note=project_text(context, workspace, "align.folder_note"),
    )
    return True


def project_text(context: CommandContext, workspace: Workspace, key: str, **values: object) -> str:
    language = project_language(workspace.project, context.language)
    return message_text(key, "it" if language.lower().startswith("it") else "en", **values)


def known_changes(workspace: Workspace) -> dict[str, Mapping[str, object]]:
    return {
        str(item.get("commit")): item
        for item in changes_api.changes(workspace.client, workspace.project_id)
    }


def record(
    context: CommandContext,
    workspace: Workspace,
    commits: Sequence[git.Commit],
    known: Mapping[str, Mapping[str, object]],
) -> int:
    count = 0
    for commit in commits:
        if commit.hash in known:
            continue
        body = git.change_body(commit, git.diff_of(context, workspace.root, commit))
        status, _ = changes_api.record(workspace.client, workspace.project_id, body)
        if status == 201:
            count += 1
    return count


def twins_count(client: StudioClient, project: ProjectFolder) -> int:
    document = read_json(project.knowledge.joinpath(*TWINS_DOCUMENT))
    versions = twin_chat.twin_versions(document if isinstance(document, Mapping) else None)
    if not versions:
        snapshot = modeling_api.snapshot(client, project.link().project_id)
        versions = twin_chat.twin_versions(snapshot)
    return max(len(versions), 1)


def review_operations(twins: int, commits: int) -> list[str]:
    one = [changes_api.REVIEW_OPERATION] * max(twins, 1) + [changes_api.ALIGNMENT_OPERATION]
    return one * max(commits, 0)


def review_estimate(twins: int) -> costs.Estimate:
    return costs.estimate(review_operations(twins, 1))


def locale(context: CommandContext, project: ProjectFolder) -> str:
    return review_locale(project_language(project, context.language))


def review(
    context: CommandContext,
    workspace: Workspace,
    commit: str,
    *,
    locale: str,
    again: bool = False,
) -> Mapping[str, object]:
    label = context.text("align.review_label", commit=git.short(commit))
    result = jobs.generate(
        context,
        workspace.client,
        workspace.project_id,
        changes_api.review_path(workspace.project_id, commit),
        changes_api.review_body(locale, again),
        label=label,
    )
    body = result.body
    if result.status_code < 400:
        run = body.get("run") if isinstance(body, Mapping) else None
        if not isinstance(run, Mapping):
            raise ApiFailure("API_FAILURE", http_status=result.status_code)
        return run
    failure = failure_of(result.status_code, body)
    if failure.code == changes_api.REVIEW_EXISTS:
        found = latest_run(workspace, commit)
        if found is not None:
            return found
    raise failure


def latest_run(workspace: Workspace, commit: str) -> Mapping[str, object] | None:
    runs = changes_api.reviews(workspace.client, workspace.project_id, commit)
    return runs[0] if runs else None


def failure_of(status: int, body: object) -> ApiFailure:
    code = changes_api.code_of(body)
    if code is None and isinstance(body, Mapping):
        failure = body.get("failure")
        found = failure.get("code") if isinstance(failure, Mapping) else None
        code = found if isinstance(found, str) and found else None
    detail = body.get("detail") if isinstance(body, Mapping) else body
    return ApiFailure(code or "API_FAILURE", http_status=status, detail=detail)


def titles(project: ProjectFolder) -> Titles:
    requirements: dict[str, str] = {}
    document = read_json(project.knowledge.joinpath(*REQUIREMENTS_DOCUMENT))
    specification = document.get("specification") if isinstance(document, dict) else None
    items = specification.get("requirements") if isinstance(specification, dict) else None
    for item in items if isinstance(items, list) else []:
        code = item.get("code") if isinstance(item, dict) else None
        title = _text(item.get("title")) if isinstance(item, dict) else ""
        if isinstance(code, str) and title:
            requirements[code] = title
    design = read_json(project.knowledge.joinpath(*DESIGN_DOCUMENT))
    package = design.get("package") if isinstance(design, dict) else None
    screens, _ = places(package) if isinstance(package, Mapping) else ({}, {})
    return Titles(requirements=requirements, screens=screens)


def commit_line(context: CommandContext, commit: git.Commit) -> str:
    return context.text(
        "align.commit_line",
        commit=git.short(commit.hash),
        date=git.commit_date(commit.committed_at),
        line=git.first_line(commit.message),
        files=len(commit.files),
    )


def show_run(
    context: CommandContext,
    run: Mapping[str, object],
    names: Titles,
    *,
    message: str | None = None,
) -> None:
    console = context.console
    commit = git.short(run.get("commit"))
    console.write()
    if message:
        console.heading(context.text("align.review_heading", commit=commit, line=message))
    else:
        console.heading(context.text("align.review_heading_plain", commit=commit))
    critiques = _mappings(run.get("critiques"))
    if not critiques:
        console.say("align.no_critiques")
    for critique in critiques:
        name = _text(critique.get("twin_name")) or context.text("align.twin_unknown")
        verdict = critique.get("verdict")
        key = CRITIQUE_KEYS.get(verdict) if isinstance(verdict, str) else None
        console.write()
        console.write(
            context.text(
                "align.twin_line",
                name=name,
                verdict=context.text(key) if key else str(verdict or "-"),
            )
        )
        summary = _text(critique.get("summary"))
        if summary:
            wrapped(context, summary, indent="  ")
        findings = _mappings(critique.get("findings"))
        if findings:
            bullets(context, [finding_line(context, item, names) for item in findings], indent="  ")
        else:
            wrapped(context, context.text("align.no_findings"), indent="  ")
    show_verdict(context, run, names)
    cost = run.get("cost_microusd")
    if isinstance(cost, int) and not isinstance(cost, bool) and cost > 0:
        console.say("align.review_cost", amount=costs.usd_text(cost / MICRO_USD, context.language))


def show_verdict(context: CommandContext, run: Mapping[str, object], names: Titles) -> None:
    console = context.console
    alignment = changes_api.run_alignment(run)
    status = alignment.get("status")
    key = VERDICT_KEYS.get(status) if isinstance(status, str) else None
    console.write()
    console.heading(context.text("align.verdict_heading"))
    if key is not None:
        wrapped(context, context.text(key))
    else:
        wrapped(context, context.text("align.verdict_other", status=str(status or "-")))
    summary = _text(alignment.get("summary"))
    if summary:
        wrapped(context, summary, indent="  ")
    affected = alignment.get("affected")
    affected = affected if isinstance(affected, Mapping) else {}
    requirements = [item for item in _list(affected.get("requirements")) if isinstance(item, str)]
    screens = [item for item in _list(affected.get("screens")) if isinstance(item, str)]
    if requirements:
        items = "; ".join(named(context, code, names.requirements) for code in requirements)
        wrapped(context, context.text("align.affected_requirements", items=items))
    if screens:
        items = "; ".join(named(context, code, names.screens) for code in screens)
        wrapped(context, context.text("align.affected_screens", items=items))
    design_request = _text(alignment.get("design_request"))
    if design_request:
        console.say("align.proposed_design")
        wrapped(context, context.text("align.quoted", text=design_request), indent="  ")
    requirements_request = _text(alignment.get("requirements_request"))
    if requirements_request:
        console.say("align.proposed_requirements")
        wrapped(context, context.text("align.quoted", text=requirements_request), indent="  ")
    tasks = [_text(item) for item in _list(alignment.get("code_tasks"))]
    tasks = [item for item in tasks if item]
    if tasks:
        console.say("align.proposed_tasks")
        bullets(context, tasks, indent="  ")


def finding_line(context: CommandContext, finding: Mapping[str, object], names: Titles) -> str:
    severity = finding.get("severity")
    key = SEVERITY_KEYS.get(severity) if isinstance(severity, str) else None
    line = context.text(
        "align.finding",
        severity=context.text(key) if key else str(severity or "-"),
        text=_text(finding.get("text")),
    )
    about = finding.get("about")
    about = about if isinstance(about, Mapping) else {}
    parts: list[str] = []
    requirement = about.get("requirement")
    if isinstance(requirement, str) and requirement:
        title = names.requirements.get(requirement)
        parts.append(
            context.text("align.about_requirement", code=requirement, title=title)
            if title
            else context.text("align.about_requirement_code", code=requirement)
        )
    screen = about.get("screen")
    if isinstance(screen, str) and screen:
        title = names.screens.get(screen)
        parts.append(
            context.text("align.about_screen", code=screen, title=title)
            if title
            else context.text("align.about_screen_code", code=screen)
        )
    path = about.get("file")
    if isinstance(path, str) and path:
        parts.append(context.text("align.about_file", path=path))
    if parts:
        line = context.text("align.finding_about", finding=line, about=", ".join(parts))
    action = _text(finding.get("action"))
    if action:
        line = context.text("align.finding_action", finding=line, action=action)
    return line


def named(context: CommandContext, code: str, titles_by_code: Mapping[str, str]) -> str:
    title = titles_by_code.get(code)
    return context.text("align.named", code=code, title=title) if title else code


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
