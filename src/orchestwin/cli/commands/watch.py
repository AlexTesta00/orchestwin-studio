from __future__ import annotations

import argparse
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import usage
from orchestwin.cli.errors import (
    BUDGET_CODES,
    SIGN_IN_STATUS,
    UNREACHABLE_STATUS,
    USAGE_STATUS,
    ApiFailure,
    CliError,
)
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import verify_review

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.verify_review import Titles, Workspace

NAME = "watch"
DEFAULT_MAX_USD: Final = 5.0
DEFAULT_INTERVAL: Final = 15.0
MINIMUM_INTERVAL: Final = 2.0
TOLERANCE: Final = 1e-9
INTERRUPTED: Final = "GENERATION_INTERRUPTED"
UNREACHABLE: Final = "STUDIO_UNREACHABLE"
STOPPING_CODES: Final = frozenset(
    {
        changes_api.NO_REVIEW_MODEL,
        "REQUIREMENTS_APPROVAL_REQUIRED",
        "DESIGN_APPROVAL_REQUIRED",
        "USER_MODELING_APPROVAL_REQUIRED",
        *BUDGET_CODES,
    }
)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--twins", action="store_true", help="watch.option_twins")
    parser.add_argument(
        "--max-usd",
        type=float,
        default=DEFAULT_MAX_USD,
        metavar="USD",
        help="watch.option_max_usd",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        metavar="SECONDS",
        help="watch.option_interval",
    )
    parser.add_argument("--once", action="store_true", help="watch.option_once")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    interval = float(arguments.interval)
    cap = float(arguments.max_usd)
    if not math.isfinite(interval) or interval < MINIMUM_INTERVAL:
        raise CliError(
            "WATCH_INTERVAL_INVALID", status=USAGE_STATUS, values={"minimum": int(MINIMUM_INTERVAL)}
        )
    if not math.isfinite(cap) or cap <= 0:
        raise CliError("WATCH_MAX_USD_INVALID", status=USAGE_STATUS)
    workspace = verify_review.prepare(context)
    watcher = Watcher(context, workspace, twins=arguments.twins, cap=cap, interval=interval)
    return watcher.run(once=arguments.once)


class Watcher:
    def __init__(
        self,
        context: CommandContext,
        workspace: Workspace,
        *,
        twins: bool,
        cap: float,
        interval: float,
    ) -> None:
        self.context = context
        self.console = context.console
        self.workspace = workspace
        self.twins = twins
        self.cap = cap
        self.interval = interval
        self.reviewing = twins and changes_api.review_available(workspace.alignment)
        self.subscription = False
        self.spent = 0.0
        self.queue: list[git.Commit] = []
        self.last: str | None = None
        self.count = 1
        self.names: Titles | None = None
        self.locale = verify_review.locale(context, workspace.project)

    def run(self, *, once: bool) -> int:
        try:
            self.introduce(once=once)
            while True:
                found = self.check()
                if once:
                    if not found:
                        self.console.say("watch.nothing_new")
                    return 0
                self.context.environment.sleep(self.interval)
        except KeyboardInterrupt:
            self.console.write()
            self.console.say("watch.stopped")
            return 0
        except CliError as error:
            if error.code != INTERRUPTED:
                raise
            self.console.say("watch.review_interrupted", label=error.values.get("label", "-"))
            self.console.say("watch.stopped")
            return 0

    def introduce(self, *, once: bool) -> None:
        context, console, workspace = self.context, self.console, self.workspace
        console.heading(context.text("watch.heading", name=workspace.project.link().project_name))
        console.say("watch.folder", path=str(workspace.project.root))
        name = git.branch(context, workspace.root)
        if name is None:
            console.say("watch.branch_detached")
        else:
            console.say("watch.branch", branch=name)
        point = changes_api.aligned(workspace.alignment)
        commit = None if point is None else point.get("commit")
        if isinstance(commit, str) and commit:
            self.last = commit
            console.say("watch.aligned", commit=git.short(commit))
        else:
            self.last = self.latest_recorded()
            if self.last is not None:
                console.say("watch.not_aligned", commit=git.short(self.last))
            else:
                self.last = git.head(context, workspace.root)
                console.say("watch.not_aligned_head")
        if not self.twins:
            console.say("watch.twins_off")
        elif not self.reviewing:
            console.say("watch.review_unavailable")
        else:
            self.count = verify_review.twins_count(workspace.client, workspace.project)
            budget = usage.budget(workspace.client)
            self.subscription = usage.on_subscription(budget)
            cap = costs.usd_text(self.cap, context.language)
            if self.subscription:
                console.say("watch.twins_on_subscription", cap=cap)
            else:
                console.say("watch.twins_on", cap=cap)
                remaining = None if budget is None else usage.remaining_usd(budget)
                if remaining is not None:
                    console.say(
                        "watch.credit", remaining=costs.usd_text(remaining, context.language)
                    )
        if not once:
            console.say("watch.waiting", seconds=_seconds(self.interval))

    def latest_recorded(self) -> str | None:
        latest = self.workspace.alignment.get("latest_change")
        commit = latest.get("commit") if isinstance(latest, Mapping) else None
        if not isinstance(commit, str) or not commit:
            return None
        return git.resolve(self.context, self.workspace.root, commit)

    def check(self) -> bool:
        context, workspace = self.context, self.workspace
        current = git.head(context, workspace.root)
        found = False
        if current is not None and current != self.last:
            try:
                commits = git.commits_after(context, workspace.root, self.last)
            except CliError as error:
                if error.code != "GIT_COMMIT_UNKNOWN":
                    raise
                self.console.say("watch.history_changed", commit=git.short(self.last))
                self.last = current
                return True
            if commits and not self.store(commits):
                return True
            found = bool(commits)
            self.last = current
        if self.reviewing and self.queue:
            self.review_queue()
        return found

    def store(self, commits: tuple[git.Commit, ...]) -> bool:
        console = self.console
        folder = verify_review.folder_commits(self.workspace, commits)
        try:
            known = verify_review.known_changes(self.workspace)
            verify_review.record(self.context, self.workspace, commits, known)
            dismissed = verify_review.dismiss_folder_commit(
                self.context, self.workspace, commits, folder, known
            )
        except CliError as error:
            if not self.passing(error):
                raise
            return False
        console.write()
        console.say("watch.new_commits", count=len(commits))
        console.items([verify_review.commit_line(self.context, commit) for commit in commits])
        if folder:
            console.say(
                "watch.folder_only_dismissed" if dismissed else "watch.folder_only",
                count=len(folder),
                commits=", ".join(git.short(commit.hash) for commit in folder),
            )
        if self.reviewing:
            skipped = {commit.hash for commit in [*self.queue, *folder]}
            self.queue.extend(
                commit
                for commit in commits
                if commit.hash not in skipped
                and changes_api.verdict_of(known.get(commit.hash, {})) is None
            )
        return True

    def review_queue(self) -> None:
        context, console = self.context, self.console
        need = verify_review.review_estimate(self.count).high_usd
        while self.queue:
            commit = self.queue[0]
            if self.spent + need > self.cap + TOLERANCE:
                cap = costs.usd_text(self.cap, context.language)
                if self.subscription:
                    console.say("watch.cap_reached_subscription", cap=cap)
                else:
                    console.say("watch.cap_reached", cap=cap)
                self.stop_reviews()
                return
            try:
                run = verify_review.review(context, self.workspace, commit.hash, locale=self.locale)
            except CliError as error:
                if error.code == INTERRUPTED or error.status == SIGN_IN_STATUS:
                    raise
                if error.code == UNREACHABLE:
                    self.passing(error)
                    return
                if error.code in STOPPING_CODES or _refused(error):
                    console.say("watch.review_stopped", code=error.code)
                    self.stop_reviews()
                    return
                self.queue.pop(0)
                self.spent += need
                console.say("watch.review_failed", commit=git.short(commit.hash), code=error.code)
                continue
            self.queue.pop(0)
            self.spent += need
            verify_review.show_run(
                context, run, self.titles(), message=git.first_line(commit.message)
            )
            console.say("watch.review_reminder")

    def stop_reviews(self) -> None:
        self.reviewing = False
        self.queue.clear()

    def titles(self) -> Titles:
        if self.names is None:
            self.names = verify_review.titles(self.workspace.project)
        return self.names

    def passing(self, error: CliError) -> bool:
        if error.status == SIGN_IN_STATUS:
            return False
        if error.code == UNREACHABLE or error.status == UNREACHABLE_STATUS:
            address = error.values.get("address") or self.workspace.client.studio.origin
            self.console.say("watch.unreachable", address=address)
            return True
        if isinstance(error, ApiFailure):
            self.console.say("watch.failed", code=error.code)
            return True
        return False


def _refused(error: CliError) -> bool:
    return isinstance(error, ApiFailure) and error.http_status == 402


def _seconds(value: float) -> str:
    return f"{value:g}"
