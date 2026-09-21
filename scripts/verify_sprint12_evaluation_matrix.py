"""Print the validated revised Sprint 12 evaluation matrix as deterministic JSON."""

from __future__ import annotations

import json
from pathlib import Path

from orchestwin.evaluation.matrix_validation import verify_sprint12_evaluation_matrix


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    summary = verify_sprint12_evaluation_matrix(repo_root)
    print(json.dumps(summary.to_snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
