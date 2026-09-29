from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

STATE_KIND: Final = "orchestwin.project-state"
CHANGE_REVIEWS_KIND: Final = "orchestwin.change-reviews"
STATE_FOLDER: Final = "state"
STATE_DOCUMENT: Final = f"{STATE_FOLDER}/state.json"
STATE_TEXT: Final = f"{STATE_FOLDER}/state.md"
FEEDBACK_CHANGES: Final = "twins/feedback/changes.json"

VERDICTS: Final = ("ALIGNED", "CODE_DRIFT", "DESIGN_OUTDATED", "REQUIREMENTS_OUTDATED")
DECISIONS: Final = ("ALIGNED", "DESIGN_CHANGE", "REQUIREMENTS_CHANGE", "CODE_TASKS", "DISMISSED")
CRITIQUE_VERDICTS: Final = ("FINE", "CONCERN", "DRIFT")
FILE_KINDS: Final = ("ADDED", "MODIFIED", "DELETED", "RENAMED")
SEVERITIES: Final = ("LOW", "MEDIUM", "HIGH")
TASK_STATUSES: Final = ("OPEN", "DONE")

MAX_COMMIT_LENGTH: Final = 64
MIN_COMMIT_LENGTH: Final = 7
MAX_MESSAGE_LENGTH: Final = 2000
MAX_AUTHOR_LENGTH: Final = 200
MAX_PATH_LENGTH: Final = 500
MAX_FILES: Final = 500
MAX_DIFF_LENGTH: Final = 65536
MAX_CONTEXT_DIFF_LENGTH: Final = 48000
MAX_SUMMARY_LENGTH: Final = 600
MAX_FINDING_LENGTH: Final = 400
MAX_ACTION_LENGTH: Final = 300
MAX_FINDINGS: Final = 6
MAX_DESIGN_REQUEST_LENGTH: Final = 1000
MAX_REQUIREMENTS_REQUEST_LENGTH: Final = 2000
MAX_TASK_LENGTH: Final = 300
MAX_TASKS: Final = 10
MAX_MODEL_TASKS: Final = 6
MAX_NOTE_LENGTH: Final = 2000


@dataclass(frozen=True, slots=True)
class ProjectStateSources:
    aligned: Mapping[str, object] | None = None
    changes: tuple[Mapping[str, object], ...] = ()
    runs: tuple[Mapping[str, object], ...] = ()
    tasks: tuple[Mapping[str, object], ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.aligned is None and not self.changes and not self.runs and not self.tasks

    @property
    def pending_changes(self) -> int:
        aligned = None if self.aligned is None else str(self.aligned.get("commit"))
        count = 0
        for change in self.changes:
            if aligned is not None and str(change.get("commit")) == aligned:
                break
            count += 1
        return count

    @property
    def open_tasks(self) -> int:
        return sum(1 for task in self.tasks if task.get("status") == "OPEN")


__all__ = [
    "CHANGE_REVIEWS_KIND",
    "CRITIQUE_VERDICTS",
    "DECISIONS",
    "FEEDBACK_CHANGES",
    "FILE_KINDS",
    "MAX_ACTION_LENGTH",
    "MAX_AUTHOR_LENGTH",
    "MAX_COMMIT_LENGTH",
    "MAX_CONTEXT_DIFF_LENGTH",
    "MAX_DESIGN_REQUEST_LENGTH",
    "MAX_DIFF_LENGTH",
    "MAX_FILES",
    "MAX_FINDINGS",
    "MAX_FINDING_LENGTH",
    "MAX_MESSAGE_LENGTH",
    "MAX_MODEL_TASKS",
    "MAX_NOTE_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_REQUIREMENTS_REQUEST_LENGTH",
    "MAX_SUMMARY_LENGTH",
    "MAX_TASKS",
    "MAX_TASK_LENGTH",
    "MIN_COMMIT_LENGTH",
    "SEVERITIES",
    "STATE_DOCUMENT",
    "STATE_FOLDER",
    "STATE_KIND",
    "STATE_TEXT",
    "TASK_STATUSES",
    "VERDICTS",
    "ProjectStateSources",
]
