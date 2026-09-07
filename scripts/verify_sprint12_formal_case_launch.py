from __future__ import annotations

import json
from pathlib import Path

from orchestwin.evaluation.case_launch_validation import verify_formal_case_launch_configuration


def main() -> int:
    summary = verify_formal_case_launch_configuration(Path.cwd())
    print(json.dumps(summary.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
