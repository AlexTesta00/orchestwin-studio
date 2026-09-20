"""Resumable validation orchestration through the production Web operation services.

Only explicit owner decisions approve operations. Local plans are indexes; source,
attempt, repair and approval facts are reloaded from owner-scoped PostgreSQL.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from orchestwin.api.web_execution import (
    WebApiCommandStatus,
    WebExecutionStartCommand,
    WebRepairChangeCommand,
    WebRepairProposalApplyCommand,
    WebRepairProposalCreateCommand,
)
from orchestwin.artifacts.web_change_sets import WebSourceChangeOperation
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_EXECUTION_POLICY
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.static_browser_jobs import content_hash
from orchestwin.workflow.web_execution import WebExecutionPurpose


class CampaignError(ValueError):
    """Stable operator-facing error without source, SQL or credentials."""


def checked_commit(repo_root, *, expected=None):
    """Read Git only; dirty/untracked sources cannot collect Level D evidence."""

    def git(*args):
        result = subprocess.run(
            ("git", "-C", str(repo_root), *args),
            capture_output=True,
            timeout=30,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        if result.returncode != 0:
            raise CampaignError("WEB_VALIDATION_GIT_READ_FAILED")
        return result.stdout

    if git("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise CampaignError("WEB_VALIDATION_DIRTY_SOURCE_TREE")
    commit = git("rev-parse", "HEAD").decode("ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise CampaignError("WEB_VALIDATION_COMMIT_INVALID")
    if expected is not None and commit != expected:
        raise CampaignError("WEB_VALIDATION_COMMIT_CHANGED")
    return commit


def create_campaign_plan(*, owner_user_id, commit, configuration_hash, fixtures):
    value = {
        "schema_version": 1,
        "campaign_id": str(uuid4()),
        "owner_user_id": str(owner_user_id),
        "platform_commit": commit,
        "configuration_hash": configuration_hash,
        "created_at": datetime.now(UTC).isoformat(),
        "cases": [
            {
                "fixture_id": fixture.fixture_id,
                "fixture_bundle_hash": fixture.fixture_bundle_hash,
                "role": role,
                "project_id": str(uuid4()),
                "source_id": str(uuid4()),
            }
            for fixture in fixtures
            for role in ("valid", "repeated", "failed")
        ],
    }
    return {**value, "content_hash": content_hash(value)}


def verify_campaign_plan(plan, *, commit, configuration_hash, fixtures):
    try:
        if (
            set(plan)
            != {
                "schema_version",
                "campaign_id",
                "owner_user_id",
                "platform_commit",
                "configuration_hash",
                "created_at",
                "cases",
                "content_hash",
            }
            or plan["schema_version"] != 1
            or plan["content_hash"]
            != content_hash({k: v for k, v in plan.items() if k != "content_hash"})
            or plan["platform_commit"] != commit
            or plan["configuration_hash"] != configuration_hash
        ):
            raise ValueError
        UUID(plan["campaign_id"]), UUID(plan["owner_user_id"])
        if datetime.fromisoformat(plan["created_at"]).utcoffset() is None:
            raise ValueError
        expected = {
            (item.fixture_id, role, item.fixture_bundle_hash)
            for item in fixtures
            for role in ("valid", "repeated", "failed")
        }
        cases = plan["cases"]
        if (
            len(cases) != 24
            or len({row["project_id"] for row in cases}) != 24
            or len({row["source_id"] for row in cases}) != 24
            or {(row["fixture_id"], row["role"], row["fixture_bundle_hash"]) for row in cases}
            != expected
        ):
            raise ValueError
        for row in cases:
            if set(row) != {"fixture_id", "fixture_bundle_hash", "role", "project_id", "source_id"}:
                raise ValueError
            UUID(row["project_id"]), UUID(row["source_id"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CampaignError("WEB_VALIDATION_PLAN_BINDING_INVALID") from None


class ValidationCampaign:
    def __init__(
        self,
        *,
        plan,
        fixtures,
        governance,
        runner_identities,
        guard,
        policy_content_hash=DEFAULT_SANDBOX_EXECUTION_POLICY.content_hash,
    ):
        self.plan, self.governance, self.guard = plan, governance, guard
        self.owner = UUID(plan["owner_user_id"])
        self.policy_content_hash = policy_content_hash
        self.fixtures = {item.fixture_id: item for item in fixtures}
        self.runners = {
            item.kind: item.image_id.removeprefix("sha256:") for item in runner_identities
        }

    async def prepare(self):
        for row in self.plan["cases"]:
            self.guard()
            fixture = self.fixtures[row["fixture_id"]]
            await self.governance.seed_fixture(
                owner_user_id=self.owner,
                project_id=UUID(row["project_id"]),
                source_id=UUID(row["source_id"]),
                created_at=datetime.fromisoformat(self.plan["created_at"]),
                fixture=fixture,
                defective=row["role"] == "failed",
            )
        # Preparation only proposes commands. It cannot consume an existing approval.
        return await self.advance(execute=False)

    def command(self, fixture, source, *, rerun=False):
        return WebExecutionStartCommand(
            source_revision_id=source.id,
            profile_id=fixture.profile_id,
            profile_version=fixture.profile_version,
            policy_content_hash=self.policy_content_hash,
            execution_runner_image_digest=self.runners[
                "PHP" if fixture.profile_id == "web.php" else "NODE"
            ],
            browser_runner_image_digest=None
            if fixture.profile_id == "web.node-express"
            else self.runners["BROWSER"],
            purpose=WebExecutionPurpose.PROFILE_VALIDATION,
            trigger=WebExecutionAttemptTrigger.REPAIR_RERUN
            if rerun
            else WebExecutionAttemptTrigger.PROFILE_VALIDATION,
            authorization_id=None,
            rerun_phases=tuple(WebExecutionPhase) if rerun else None,
            declared_routes=fixture.browser_routes,
            browser_interactions=fixture.browser_interactions,
        )

    async def _state(self, row):
        kwargs = {"owner_user_id": self.owner, "project_id": UUID(row["project_id"])}
        sources = await self.governance.source_history(**kwargs)
        operations = await self.governance.operation_history(**kwargs)
        if not sources or sources[0].id != UUID(row["source_id"]):
            raise CampaignError("WEB_VALIDATION_SEED_MISSING")
        fixture = self.fixtures[row["fixture_id"]]
        if sources[0].source_tree_hash != fixture.source_tree_hash(
            defective=row["role"] == "failed"
        ):
            raise CampaignError("WEB_VALIDATION_SOURCE_MISMATCH")
        if len(sources) > (2 if row["role"] == "failed" else 1) or len(operations) > (
            3 if row["role"] == "failed" else 1
        ):
            raise CampaignError("WEB_VALIDATION_UNEXPECTED_HISTORY")
        return kwargs, sources, operations

    async def _operation_state(self, kwargs, operation):
        async with self.governance.operation_store.scope(**kwargs) as scope:
            current = await scope.get(operation.id)
            gate = await scope.gate(current)
            return current, gate, await scope.snapshot(current)

    async def approve(self, decisions):
        """Decisions must name already prepared operations in this exact campaign."""
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 24:
            raise CampaignError("WEB_VALIDATION_DECISIONS_INVALID")
        operations = {}
        for row in self.plan["cases"]:
            kwargs, _, history = await self._state(row)
            operations.update(
                {str(item.id): (kwargs, item) for item in history if item.state == "PENDING"}
            )
        seen = set()
        checked = []
        for decision in decisions:
            if (
                not isinstance(decision, dict)
                or set(decision) != {"operation_id", "content_hash", "event_sequence"}
                or decision["operation_id"] not in operations
                or decision["operation_id"] in seen
                or type(decision["event_sequence"]) is not int
                or decision["event_sequence"] < 1
            ):
                raise CampaignError("WEB_VALIDATION_DECISION_OUTSIDE_CAMPAIGN")
            kwargs, operation = operations[decision["operation_id"]]
            if decision["content_hash"] != operation.content_hash:
                raise CampaignError("WEB_VALIDATION_DECISION_HASH_MISMATCH")
            seen.add(decision["operation_id"])
            checked.append((kwargs, operation, decision))
        for kwargs, operation, decision in checked:
            self.guard()
            await self.governance.approve(
                **kwargs,
                operation_id=operation.id,
                expected_hash=decision["content_hash"],
                expected_event_sequence=decision["event_sequence"],
            )

    @staticmethod
    def _accepted(result, expected):
        if result.status is not expected:
            raise CampaignError(
                f"WEB_VALIDATION_OPERATION_REJECTED:{result.status}:{result.message}"
            )
        return result.snapshot

    async def advance(self, *, execute=True):
        """At most one existing approved operation per case; new proposals await review."""
        for row in self.plan["cases"]:
            self.guard()
            kwargs, sources, operations = await self._state(row)
            fixture = self.fixtures[row["fixture_id"]]
            if not operations:
                result = await self.governance.prepare_execution(
                    **kwargs, command=self.command(fixture, sources[0])
                )
                self._accepted(result, WebApiCommandStatus.EXECUTION_PREPARED)
                continue
            latest = operations[-1]
            current, gate, _ = await self._operation_state(kwargs, latest)
            if current.state in {"FAILED", "RUNNING"}:
                raise CampaignError("WEB_VALIDATION_OPERATION_NEEDS_RECONCILIATION")
            if current.state == "PENDING":
                if not execute or gate.status != "APPROVED":
                    continue
                if current.kind == "EXECUTION":
                    command = self.command(fixture, sources[-1], rerun=len(sources) == 2)
                    result = await self.governance.start_execution(
                        **kwargs, command=replace(command, authorization_id=current.id)
                    )
                    self._accepted(result, WebApiCommandStatus.EXECUTION_RECORDED)
                else:
                    result = await self.governance.apply_repair_proposal(
                        owner_user_id=self.owner,
                        execution_id=UUID(current.payload["execution_id"]),
                        proposal_id=current.id,
                        command=WebRepairProposalApplyCommand(
                            sources[0].content_hash, current.content_hash, gate.id
                        ),
                    )
                    self._accepted(result, WebApiCommandStatus.REPAIR_APPLIED)
                self.guard()
                kwargs, sources, operations = await self._state(row)
                current = operations[-1]
            if current.kind == "REPAIR" and current.state == "COMPLETED":
                if len(sources) != 2 or sources[-1].source_tree_hash != fixture.source_tree_hash():
                    raise CampaignError("WEB_VALIDATION_REPAIR_SOURCE_MISMATCH")
                result = await self.governance.prepare_execution(
                    **kwargs, command=self.command(fixture, sources[-1], rerun=True)
                )
                self._accepted(result, WebApiCommandStatus.EXECUTION_PREPARED)
            elif current.state == "COMPLETED":
                receipt = await self.governance.harvest_attempt(**kwargs, attempt_id=current.id)
                if row["role"] != "failed" or len(sources) == 2:
                    if receipt.attempt.report.status != "PASSED":
                        raise CampaignError("WEB_VALIDATION_POSITIVE_FIXTURE_FAILED")
                elif len(operations) == 1:
                    signatures = receipt.attempt.report.failure_signatures()
                    signature = signatures[0] if len(signatures) == 1 else None
                    if (
                        receipt.attempt.report.status != "FAILED"
                        or signature is None
                        or signature.phase != fixture.expected_failure_phase
                    ):
                        raise CampaignError("WEB_VALIDATION_NEGATIVE_CONTROL_NOT_OBSERVED")
                    original = next(
                        item for item in fixture.files if item.path == fixture.failure_path
                    )
                    result = await self.governance.create_repair_proposal(
                        owner_user_id=self.owner,
                        execution_id=current.id,
                        command=WebRepairProposalCreateCommand(
                            sources[0].content_hash,
                            signature.digest,
                            (
                                WebRepairChangeCommand(
                                    WebSourceChangeOperation.REPLACE,
                                    original.path,
                                    original.content.decode("utf-8"),
                                    original.media_type,
                                ),
                            ),
                            "Restore the repository fixture after the observed negative control.",
                        ),
                    )
                    self._accepted(result, WebApiCommandStatus.REPAIR_PROPOSED)
        return await self.review()

    async def review(self):
        cases = []
        for row in self.plan["cases"]:
            kwargs, sources, operations = await self._state(row)
            snapshots = []
            for operation in operations:
                _, _, snapshot = await self._operation_state(kwargs, operation)
                snapshots.append(snapshot)
            cases.append(
                {
                    **row,
                    "source_revisions": [source.to_snapshot() for source in sources],
                    "operations": snapshots,
                }
            )
        return {
            "schema_version": 1,
            "campaign_hash": self.plan["content_hash"],
            "platform_commit": self.plan["platform_commit"],
            "cases": cases,
        }
