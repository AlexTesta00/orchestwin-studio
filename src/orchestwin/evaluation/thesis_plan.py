"""Offline verification of pinned thesis plans, never collection or scientific results."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath

from orchestwin.evaluation.case_launch_inputs import (
    load_formal_case_launch_input,
    validate_launch_input_against_definition,
)
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.expert_package import assign_blinded_pairs


def verify_thesis_evaluation_plan(repo_root: Path, plan_path: Path) -> dict[str, object]:
    """Verify file identities and existing case/protocol contracts without inference."""
    root = repo_root.resolve()
    raw_plan = plan_path.read_bytes()
    plan = json.loads(raw_plan)
    if plan.get("schema_version") != 1 or plan.get("kind") != "THESIS_EVALUATION_EXECUTION_PLAN":
        raise ValueError("unsupported thesis plan contract")
    if plan.get("is_observed_result") is not False:
        raise ValueError("a thesis plan must not claim observed results")
    verified = {}
    for item in plan["pinned_files"]:
        relative = PurePosixPath(item["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in item["path"]
            or ":" in item["path"]
            or item["path"] in verified
        ):
            raise ValueError("unsafe or duplicate thesis input path")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("thesis input escapes the repository")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("pinned thesis input changed: " + item["path"])
        verified[item["path"]] = path
    if not verified:
        raise ValueError("thesis plan requires pinned inputs")
    cases = []
    for item in plan["formal_cases"]:
        definition_path = verified[item["definition_path"]]
        launch_path = verified[item["launch_input_path"]]
        definition = load_case_study_definition(definition_path)
        launch = load_formal_case_launch_input(launch_path)
        validate_launch_input_against_definition(launch, json.loads(definition_path.read_bytes()))
        if definition.case_id != item["case_id"] or definition.content_hash != item["content_hash"]:
            raise ValueError("thesis case identity mismatch")
        cases.append(definition.case_id)
    if len(cases) != len(set(cases)):
        raise ValueError("duplicate thesis case")
    campaign = json.loads(verified[plan["campaign_contract_path"]].read_bytes())
    if cases != campaign["formal_case_ids"]:
        raise ValueError("thesis case selection differs from the frozen campaign")
    protocol = json.loads(verified[plan["expert_protocol_path"]].read_bytes())
    selection = plan["expert_review"]
    for key in (
        "pair_count",
        "ratings_per_pair",
        "ratings_per_reviewer",
        "reviewer_aliases",
        "rubric_items",
    ):
        if selection[key] != protocol[key]:
            raise ValueError("expert schedule differs from the frozen protocol")
    # Planning aliases are neither observed output pairs nor registered participants.
    assignments = assign_blinded_pairs(
        tuple(f"planned-{index + 1:03}" for index in range(protocol["pair_count"])),
        reviewer_ids=tuple(protocol["reviewer_aliases"]),
    )
    counts = Counter(alias for assignment in assignments for alias in assignment.reviewer_ids)
    if any(count != protocol["ratings_per_reviewer"] for count in counts.values()):
        raise ValueError("expert schedule is unbalanced")
    expected_ratings = sum(len(item.reviewer_ids) for item in assignments)
    if expected_ratings != protocol["pair_count"] * protocol["ratings_per_pair"]:
        raise ValueError("expert schedule rating count mismatch")
    binding = json.loads(verified[plan["metric_binding_contract_path"]].read_bytes())
    if plan["metric_collection"]["required_raw_fields"] != binding["required_fields"]:
        raise ValueError("metric inputs differ from the observed binding contract")
    return {
        "status": "PLAN_REFERENCES_VERIFIED_NOT_EXECUTION_READINESS",
        "plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
        "pinned_files_verified": len(verified),
        "case_ids_verified": cases,
        "planned_expert_rating_count": expected_ratings,
        "planned_reviewer_counts": dict(sorted(counts.items())),
        "is_observed_result": False,
        "formal_execution_readiness_assessed": False,
        "human_participation_verified": False,
        "database_writes": 0,
        "inference_calls": 0,
    }
