#!/usr/bin/env python3
"""Materialize one immutable owner-authorized request for the eight-step QLoRA smoke."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.qlora_smoke_requests import (  # noqa: E402
    QloraSmokeRequestError,
    build_request,
    write_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--tokenized", required=True, type=Path)
    parser.add_argument("--source-evidence", required=True, type=Path)
    parser.add_argument("--collator-report", required=True, type=Path)
    parser.add_argument("--license-audit", required=True, type=Path)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--approve-fixtures", action="store_true")
    parser.add_argument("--approve-model-license", action="store_true")
    parser.add_argument("--approve-local-training", action="store_true")
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        request = build_request(
            repository_root=ROOT,
            prepared_root=args.prepared,
            tokenized_root=args.tokenized,
            source_evidence_path=args.source_evidence,
            collator_report_path=args.collator_report,
            license_audit_path=args.license_audit,
            owner_id=args.owner_id,
            approve_fixtures=args.approve_fixtures,
            approve_model_license=args.approve_model_license,
            approve_local_training=args.approve_local_training,
            created_at=datetime.fromisoformat(args.created_at),
        )
        write_request(args.output, request)
    except (QloraSmokeRequestError, OSError, ValueError) as error:
        print(f"qlora_smoke_request_failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 22
    print(args.output.absolute())
    print("qlora_smoke_request: OWNER_AUTHORIZED_REQUEST_MATERIALIZED (training not executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
