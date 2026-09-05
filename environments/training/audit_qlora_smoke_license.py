#!/usr/bin/env python3
"""Audit the captured Qwen license evidence before owner authorization of QLoRA smoke."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.model_license_audit import (  # noqa: E402
    ModelLicenseAuditError,
    audit_model_license,
    write_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-evidence", required=True, type=Path)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        created_at = datetime.fromisoformat(args.created_at)
        report = audit_model_license(
            repository_root=ROOT,
            source_evidence_path=args.source_evidence,
            created_at=created_at,
        )
        write_audit(args.output, report)
    except (ModelLicenseAuditError, OSError, ValueError) as error:
        print(f"qlora_smoke_license_audit_failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 22
    print(args.output.absolute())
    print(
        "qlora_smoke_license_audit: VERIFIED_EVIDENCE_READY_FOR_OWNER_DECISION "
        "(no legal conclusion, no training)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
