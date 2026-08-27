"""Structurally validated WEB_STATIC profile kept capability-honest until evidence exists."""

from __future__ import annotations

from dataclasses import dataclass

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.profile_contracts import (
    WebProfileContract,
    WebProfileIssue,
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidation,
    common_profile_issues,
    create_profile_contract,
    create_profile_validation,
    require_paths,
)
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec
from orchestwin.web_execution.targets import (
    WebTargetSelection,
    WebValidationScope,
    web_scope_for,
)


@dataclass(frozen=True, slots=True)
class WebStaticExecutionProfile:
    """Profile for root HTML/CSS/JavaScript projects without package managers."""

    @property
    def scope(self) -> WebValidationScope:
        return web_scope_for(ExecutionTarget.WEB_STATIC)

    def validate(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
    ) -> WebProfileValidation:
        issues: list[WebProfileIssue] = common_profile_issues(
            snapshot,
            selection=selection,
            lock_report=lock_report,
            expected_target=ExecutionTarget.WEB_STATIC,
        )
        issues.extend(require_paths(snapshot, "index.html"))
        unsupported = tuple(
            path
            for path in snapshot.included_paths
            if path in {"composer.json", "package.json"}
            or path.endswith((".php", ".ts", ".tsx", ".vue"))
        )
        issues.extend(
            WebProfileIssue(
                code=WebProfileIssueCode.UNSUPPORTED_PROJECT,
                path=path,
                message="Static Web profile contains a framework or compiled-language indicator.",
            )
            for path in unsupported
        )
        return create_profile_validation(
            snapshot=snapshot,
            selection=selection,
            lock_report=lock_report,
            scope=self.scope,
            issues=issues,
        )

    def create_contract(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
        source_revision_content_hash: str,
        source_tree_hash: str,
        runners: WebProfileRunnerSet,
        declared_routes: tuple[WebBrowserRouteSpec, ...] = (),
    ) -> WebProfileContract:
        validation = self.validate(
            snapshot,
            selection=selection,
            lock_report=lock_report,
        )
        return create_profile_contract(
            validation=validation,
            snapshot=snapshot,
            lock_report=lock_report,
            source_revision_content_hash=source_revision_content_hash,
            source_tree_hash=source_tree_hash,
            runners=runners,
            health_checks=(
                WebHealthCheckSpec(
                    check_id="static.root",
                    host="127.0.0.1",
                    port=4173,
                    path="/",
                    expected_status_codes=(200,),
                    request_timeout_seconds=2,
                    maximum_attempts=10,
                    interval_milliseconds=250,
                ),
            ),
            browser_base_url="http://127.0.0.1:4173",
            declared_routes=declared_routes,
        )
