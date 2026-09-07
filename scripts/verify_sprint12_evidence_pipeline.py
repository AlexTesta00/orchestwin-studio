#!/usr/bin/env python3
"""Verify frozen Sprint 12 evidence contracts without running models or case studies."""

from __future__ import annotations

import json
from pathlib import Path

from orchestwin.evaluation.pipeline_validation import verify_sprint12_evidence_pipeline


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    summary = verify_sprint12_evidence_pipeline(repo_root)
    print("S12_EVIDENCE_PIPELINE_CONTRACT_VERIFIED")
    print(json.dumps(summary.to_snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
