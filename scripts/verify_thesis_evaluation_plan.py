"""Check frozen thesis plan inputs; does not execute models or contact participants."""

import argparse
import json
from pathlib import Path

from orchestwin.evaluation.thesis_plan import verify_thesis_evaluation_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("experiments/case-studies/thesis-evaluation-plan-20260920.json"),
    )
    args = parser.parse_args()
    print(json.dumps(verify_thesis_evaluation_plan(args.repo_root, args.plan), indent=2))


if __name__ == "__main__":
    main()
