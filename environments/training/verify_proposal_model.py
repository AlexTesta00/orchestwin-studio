#!/usr/bin/env python3
"""Capture one real team-proposal integration probe, never a formal case run.

Run with the API Python environment. The probe creates no database records or
Gate decisions. Each invocation retains its original request and HTTP response.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.agents.selection_rules import determine_team_constraints  # noqa: E402
from orchestwin.models.model_proposals import ModelTeamProposalAdapter  # noqa: E402
from orchestwin.models.proposal_generation import (  # noqa: E402
    DirectProposalTransport,
    ProposalGenerationError,
    build_proposal_generator,
)
from orchestwin.models.team_proposals import TeamProposalRequest  # noqa: E402
from orchestwin.projects.briefs import (  # noqa: E402
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import ProjectMode  # noqa: E402
from orchestwin.projects.requirements_primitives import canonical_json  # noqa: E402


def make_request():
    brief = create_project_brief(
        name="Calculator model integration probe",
        description="A small accessible responsive calculator for basic arithmetic, using HTML, CSS and JavaScript without network access.",
        target_users=["Novice end user"],
        technical_constraints=[
            "Static HTML, CSS and JavaScript",
            "Keyboard and pointer input",
            "No external services",
        ],
        functional_requirements=[
            "Add, subtract, multiply and divide numbers",
            "Explain division by zero",
            "Clear the current calculation",
        ],
        unknown_fields=[
            field
            for field in BriefField
            if field
            not in {
                BriefField.NAME,
                BriefField.DESCRIPTION,
                BriefField.TARGET_USERS,
                BriefField.TECHNICAL_CONSTRAINTS,
                BriefField.FUNCTIONAL_REQUIREMENTS,
            }
        ],
    )
    version = ProjectBriefVersion(
        id=uuid4(),
        project_id=uuid4(),
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    mode = ProjectMode.GREENFIELD_GENERATION
    return TeamProposalRequest(
        mode, version, determine_team_constraints(project_mode=mode, brief=brief)
    )


class CapturingTransport(DirectProposalTransport):
    def __init__(self, directory):
        self.directory = directory

    async def post_json(self, **kwargs):
        # Authentication headers are deliberately excluded from retained evidence.
        (self.directory / "request.json").write_text(
            canonical_json(kwargs["payload"]), encoding="utf-8"
        )
        response = await super().post_json(**kwargs)
        (self.directory / "response.bin").write_bytes(response.body)
        (self.directory / "http.json").write_text(
            canonical_json(
                {
                    "status": response.status_code,
                    "latency_milliseconds": response.elapsed_milliseconds,
                }
            ),
            encoding="utf-8",
        )
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=False, exist_ok=False)
    generator = build_proposal_generator(
        args.runtime_config.resolve(),
        transport=CapturingTransport(directory),
    )
    source_paths = [
        *sorted((ROOT / "src/orchestwin/models").glob("*.py")),
        Path(__file__),
        ROOT / "environments/training/serve_proposal_model.py",
        ROOT / "environments/training/run_model_spike.py",
    ]
    source_hashes = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_paths
    }
    started = datetime.now(UTC).isoformat()
    try:
        result = asyncio.run(ModelTeamProposalAdapter(generator).propose(make_request()))
        if result.proposal is None:
            raise ProposalGenerationError("CONSTRAINTS_BLOCKED")
        (directory / "proposal.json").write_text(
            canonical_json(result.proposal.to_snapshot()), encoding="utf-8"
        )
        outcome = "ACCEPTED_MODEL_PROPOSAL"
    except ProposalGenerationError as error:
        outcome = error.code
    if source_hashes != {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_paths
    }:
        outcome = "SOURCE_CHANGED_DURING_PROBE"
    artifacts = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }
    report = {
        "schema_version": 1,
        "scope": "REAL_MODEL_ENGINEERING_PROBE_NOT_FORMAL_CASE",
        "task": "team",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "outcome": outcome,
        "database_writes": 0,
        "gate_decisions": 0,
        "model_identity": generator.configuration.identity.to_snapshot(),
        "generation": {
            "temperature": generator.configuration.temperature,
            "max_output_tokens": generator.configuration.max_output_tokens,
        },
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": source_hashes,
        "artifacts_sha256": artifacts,
    }
    (directory / "report.json").write_text(canonical_json(report), encoding="utf-8")
    print(json.dumps({"outcome": outcome, "report": str(directory / "report.json")}))
    return 0 if outcome == "ACCEPTED_MODEL_PROPOSAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
