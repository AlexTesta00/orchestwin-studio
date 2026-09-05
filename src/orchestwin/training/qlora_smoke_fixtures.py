"""Frozen, fictional QLoRA smoke supervision; never an efficacy evaluation dataset."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.training.benchmark_measurement_v2 import (
    OUTPUT_SCHEMA_SHA256,
    measure_evaluator_output_v2,
    strict_json_loads,
)
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmark_tasks import (
    BenchmarkEvidenceItem,
    BenchmarkExpectedEvaluation,
    BenchmarkTaskCategory,
    create_benchmark_task,
)
from orchestwin.training.benchmarking import evaluator_benchmark_output_schema
from orchestwin.training.dataset_examples import DatasetLanguage

SMOKE_FIXTURE_PATH: Final = "experiments/qlora-smoke/evaluator-smoke-v1.json"
SMOKE_FIXTURE_SHA256: Final = "b94f0092134d7eb36b8c3c76537ebc3c97e0a93b5fab4c38108057f4dcdb638f"
SMOKE_PURPOSE: Final = "PIPELINE_SMOKE_ONLY"
SMOKE_LIMITATION: Final = (
    "Assistant-authored fictional technical fixtures pending owner review. "
    "Not target-user evidence, not a final training dataset, and not an efficacy test. "
    "The validation split only exercises trainer evaluation/checkpoint mechanics."
)
_METADATA: Final = {
    "schema_version": 1,
    "fixture_set_id": "ut-evaluator-qlora-smoke-v1",
    "purpose": SMOKE_PURPOSE,
    "source_kind": "DETERMINISTIC_FIXTURE",
    "authoring_status": "ASSISTANT_AUTHORED_PENDING_OWNER_REVIEW",
    "real_user_data": False,
    "human_validation_performed": False,
    "use_as_final_training_dataset": False,
    "use_as_quality_evaluation": False,
    "output_schema_sha256": OUTPUT_SCHEMA_SHA256,
    "split_policy": "SCENARIO_FAMILY_WITH_TRANSLATIONS_KEPT_TOGETHER",
}
_INPUT_FIELDS = {
    "project_brief_summary",
    "profile_summary",
    "profile_status",
    "scenario",
    "target_task",
    "artifact_summary",
    "evidence",
}
_SAMPLE_FIELDS = {
    "sample_id",
    "scenario_family_id",
    "split",
    "language",
    "input",
    "expected_output",
}
_FORMAL_CASE_WORDS = re.compile(r"\b(calculator|calcolatrice|hotel|albergo|weather|meteo)\b", re.I)


class SmokePreparationError(ValueError):
    """Smoke preparation input is invalid; no training should start."""


def regular_smoke_path(path: Path) -> Path:
    """Reject links in any component, rather than resolving them before inspection."""
    if ".." in path.parts:
        raise SmokePreparationError("parent traversal is not permitted in smoke paths")
    path = path.absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise SmokePreparationError("symbolic links are not permitted in smoke inputs")
    if not path.is_file() or path.stat().st_size > 8_000_000:
        raise SmokePreparationError("smoke input must be a bounded regular file")
    return path


@dataclass(frozen=True, slots=True)
class SmokeSample:
    """Immutable sample with structured content stored as canonical JSON strings."""

    sample_id: str
    scenario_family_id: str
    split: str
    language: str
    input_json: str
    output_json: str

    def snapshot(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "scenario_family_id": self.scenario_family_id,
            "split": self.split,
            "language": self.language,
            "input": json.loads(self.input_json),
            "expected_output": json.loads(self.output_json),
        }

    def training_record(self) -> dict[str, object]:
        """Return conversational prompt/completion, with no answers inside the prompt."""
        language = "English" if self.language == "en" else "Italian"
        instruction = (
            f"Evaluate the fictional interface from the supplied draft role in {language}. "
            "Return exactly one JSON object matching output_schema, without Markdown. "
            "Use at most one finding. Use only supplied evidence references. "
            "Findings are MODEL_INFERRED hypotheses, never empirical user evidence, "
            "and require human validation. If evidence is insufficient, set abstained=true, "
            "findings=[] and explain what is missing in evidence_gaps. If the stated "
            "requirement is met, findings=[] with abstained=false is allowed. "
            "This is simulated feedback, not evidence of real-user behavior."
        )
        model_input = {
            "sample_id": self.sample_id,
            "input": json.loads(self.input_json),
            "output_schema": json.loads(evaluator_benchmark_output_schema().canonical_schema_json),
        }
        return {
            "prompt": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": canonical_json(model_input)},
            ],
            "completion": [{"role": "assistant", "content": self.output_json}],
        }


@dataclass(frozen=True, slots=True)
class SmokeFixtureSet:
    samples: tuple[SmokeSample, ...]
    leakage_report_json: str

    def for_split(self, split: str) -> tuple[SmokeSample, ...]:
        return tuple(sample for sample in self.samples if sample.split == split)

    @property
    def leakage_report(self) -> dict[str, object]:
        return json.loads(self.leakage_report_json)


def _validate_sample(sample: object) -> SmokeSample:
    if not isinstance(sample, dict) or set(sample) != _SAMPLE_FIELDS:
        raise SmokePreparationError("smoke sample fields differ from the frozen contract")
    sid = sample["sample_id"]
    match = re.fullmatch(r"SMK-(EN|IT)-(00[1-9]|010)", str(sid))
    if match is None or sample["language"] != match.group(1).lower():
        raise SmokePreparationError("invalid smoke sample ID or language")
    if sample["split"] not in {"train", "validation"}:
        raise SmokePreparationError("invalid smoke split")
    family = sample["scenario_family_id"]
    if not isinstance(family, str) or not re.fullmatch(r"smoke-[a-z0-9-]+", family):
        raise SmokePreparationError("invalid smoke scenario family")
    model_input = sample["input"]
    if not isinstance(model_input, dict) or set(model_input) != _INPUT_FIELDS:
        raise SmokePreparationError("smoke input fields are inconsistent")
    if model_input["profile_status"] != "DRAFT_UT":
        raise SmokePreparationError("smoke profiles cannot claim real owner approval")
    for key in _INPUT_FIELDS - {"evidence"}:
        text = model_input[key]
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise SmokePreparationError("smoke input text must be short and nonempty")
    evidence = model_input["evidence"]
    if not isinstance(evidence, list) or len(evidence) != 2:
        raise SmokePreparationError("each smoke example requires two fictional evidence items")
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"reference_id", "text"}:
            raise SmokePreparationError("invalid smoke evidence shape")
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise SmokePreparationError("smoke evidence text is required")
    expected_refs = (f"{sid}-ART", f"{sid}-BRIEF")
    if tuple(item["reference_id"] for item in evidence) != expected_refs:
        raise SmokePreparationError("smoke references must be independent of benchmark references")
    output = sample["expected_output"]
    if not isinstance(output, dict) or not isinstance(output.get("findings"), list):
        raise SmokePreparationError("supervised output must be an object, not repaired text")
    findings = output["findings"]
    if len(findings) > 1 or not isinstance(output.get("abstained"), bool):
        raise SmokePreparationError("smoke output violates the explicit one-finding contract")
    abstained = output["abstained"]
    if abstained and (findings or not output.get("evidence_gaps")):
        raise SmokePreparationError("smoke abstention requires no findings and an evidence gap")
    if output.get("role_statement") != model_input["profile_summary"]:
        raise SmokePreparationError("supervised role statement differs from the fictional role")
    for finding in findings:
        if not isinstance(finding, dict):
            raise SmokePreparationError("smoke finding must be an object")
        if finding.get("epistemic_status") != "MODEL_INFERRED":
            raise SmokePreparationError("smoke findings cannot claim empirical or human evidence")
        if finding.get("requires_human_validation") is not True:
            raise SmokePreparationError("smoke findings require human validation")
        refs = finding.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not set(refs) <= set(expected_refs):
            raise SmokePreparationError("smoke finding references unavailable evidence")
    # Reuse the v2 structural/protocol validator on a separate technical task object.
    # These 9xx task objects are not inserted into, or read from, the frozen benchmark.
    task = create_benchmark_task(
        task_id=f"bench-{sample['language']}-{900 + int(match.group(2)):03d}",
        version_number=1,
        category=(
            BenchmarkTaskCategory.ABSTENTION
            if abstained
            else BenchmarkTaskCategory.SCHEMA_AND_PROVENANCE
        ),
        language=DatasetLanguage(sample["language"]),
        profile_summary=model_input["profile_summary"],
        scenario=model_input["scenario"],
        target_task=model_input["target_task"],
        artifact_summary=model_input["artifact_summary"],
        evidence=tuple(BenchmarkEvidenceItem(**item) for item in evidence),
        expected=BenchmarkExpectedEvaluation(
            should_abstain=abstained,
            minimum_findings=len(findings),
            maximum_findings=len(findings),
            allowed_evidence_refs=expected_refs,
            required_evidence_refs=expected_refs if findings else (),
            expected_criteria=tuple(SyntheticFindingCriterion(f["criterion"]) for f in findings),
            expected_severities=tuple(SyntheticFindingSeverity(f["severity"]) for f in findings),
            required_role_terms=(),
            forbidden_claim_fragments=(),
        ),
    )
    result = measure_evaluator_output_v2(
        task=task,
        raw_output=canonical_json(output),
        output_schema=json.loads(evaluator_benchmark_output_schema().canonical_schema_json),
    )
    if not result.json_schema_valid or any(value is False for _, value in result.protocol_checks):
        raise SmokePreparationError(f"invalid supervised schema/protocol: {sid}")
    return SmokeSample(
        sid,
        family,
        sample["split"],
        sample["language"],
        canonical_json(model_input),
        canonical_json(output),
    )


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def _narrative(value: dict[str, object]) -> str:
    return " ".join(
        str(value[key])
        for key in (
            "profile_summary",
            "scenario",
            "target_task",
            "artifact_summary",
        )
    )


def _trigrams(text: str) -> set[tuple[str, ...]]:
    tokens = _normalized(text).split()
    return {tuple(tokens[index : index + 3]) for index in range(max(0, len(tokens) - 2))}


def _similarity(a: str, b: str) -> float:
    left, right = _trigrams(a), _trigrams(b)
    return len(left & right) / len(left | right) if left or right else 1.0


def validate_smoke_payload(payload: object, benchmark_suite: object) -> SmokeFixtureSet:
    """Validate labels/splits and a bounded lexical screen, not a semantic leakage proof."""
    if not isinstance(payload, dict) or set(payload) != {*_METADATA, "samples"}:
        raise SmokePreparationError("smoke fixture metadata fields changed")
    if canonical_json({key: payload[key] for key in _METADATA}) != canonical_json(_METADATA):
        raise SmokePreparationError("smoke purpose or provenance metadata changed")
    if not isinstance(payload["samples"], list) or len(payload["samples"]) != 20:
        raise SmokePreparationError("smoke set must contain exactly twenty examples")
    samples = tuple(_validate_sample(sample) for sample in payload["samples"])
    ids = [sample.sample_id for sample in samples]
    if ids != sorted(set(ids)):
        raise SmokePreparationError("smoke sample IDs must be unique and canonical")
    counts = Counter((sample.split, sample.language) for sample in samples)
    if counts != {
        ("train", "en"): 8,
        ("train", "it"): 8,
        ("validation", "en"): 2,
        ("validation", "it"): 2,
    }:
        raise SmokePreparationError("smoke split language counts changed")
    groups: dict[str, list[SmokeSample]] = {}
    for sample in samples:
        groups.setdefault(sample.scenario_family_id, []).append(sample)
    if len(groups) != 10 or any(
        len(group) != 2
        or {item.language for item in group} != {"en", "it"}
        or len({item.split for item in group}) != 1
        for group in groups.values()
    ):
        raise SmokePreparationError("scenario translations must remain in the same split")
    narratives = [(sample, json.loads(sample.input_json)) for sample in samples]
    protected = [
        {
            key: getattr(task, key)
            for key in (
                "profile_summary",
                "scenario",
                "target_task",
                "artifact_summary",
            )
        }
        for task in benchmark_suite.tasks
    ]
    maximum_benchmark = 0.0
    maximum_cross_split = 0.0
    for sample, model_input in narratives:
        story = _narrative(model_input)
        if _FORMAL_CASE_WORDS.search(story):
            raise SmokePreparationError("formal case-study domain found in smoke data")
        for task in protected:
            if any(
                _normalized(str(model_input[key])) == _normalized(str(task[key]))
                for key in ("scenario", "target_task", "artifact_summary")
            ):
                raise SmokePreparationError("frozen benchmark narrative reused in smoke data")
            similarity = _similarity(story, _narrative(task))
            maximum_benchmark = max(maximum_benchmark, similarity)
        for other, other_input in narratives:
            if sample.split != other.split:
                maximum_cross_split = max(
                    maximum_cross_split, _similarity(story, _narrative(other_input))
                )
    if max(maximum_benchmark, maximum_cross_split) >= 0.75:
        raise SmokePreparationError("smoke narrative failed the lexical near-duplicate screen")
    return SmokeFixtureSet(
        samples,
        canonical_json(
            {
                "benchmark_sample_reuse": False,
                "shared_cross_split_families": [],
                "translations_share_split": True,
                "benchmark_suite_content_hash": benchmark_suite.content_hash,
                "method": "NORMALIZED_NARRATIVE_TRIGRAM_JACCARD",
                "rejection_threshold": 0.75,
                "maximum_benchmark_similarity": maximum_benchmark,
                "maximum_cross_split_similarity": maximum_cross_split,
                "semantic_leakage_proven_absent": False,
                "scope": "No semantic guarantee; schema and protocol instructions intentionally shared.",
            }
        ),
    )


def load_smoke_fixtures(repository_root: Path) -> SmokeFixtureSet:
    path = regular_smoke_path(repository_root / SMOKE_FIXTURE_PATH)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SMOKE_FIXTURE_SHA256:
        raise SmokePreparationError("frozen smoke fixture file digest changed")
    return validate_smoke_payload(
        strict_json_loads(raw.decode("utf-8")),
        load_frozen_evaluator_benchmark_suite(repository_root),
    )
