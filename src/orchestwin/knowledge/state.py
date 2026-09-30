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

TEST_REVIEWS_KIND: Final = "orchestwin.test-reviews"
FEEDBACK_TESTS: Final = "twins/feedback/tests.json"
APPLICATION_KINDS: Final = ("URL", "STATIC")
TEST_ACTIONS: Final = ("OPEN", "CLICK", "TYPE", "SELECT", "PRESS", "CHECK")
TEST_EXPECTATIONS: Final = (
    "TEXT_VISIBLE",
    "TEXT_ABSENT",
    "ELEMENT_VISIBLE",
    "ELEMENT_ABSENT",
    "VALUE_IS",
    "URL_CONTAINS",
    "TITLE_CONTAINS",
)
TEST_KEYS: Final = (
    "Enter",
    "Escape",
    "Tab",
    "Space",
    "Backspace",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Home",
    "End",
)
TEST_ROLES: Final = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "slider",
    "spinbutton",
    "switch",
    "heading",
    "text",
    "image",
    "alert",
    "status",
    "dialog",
    "tab",
    "listitem",
    "cell",
    "progressbar",
)
INTERACTIVE_ROLES: Final = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "slider",
    "spinbutton",
    "switch",
    "tab",
)
PATH_STATUSES: Final = ("PASSED", "FAILED", "BLOCKED", "NOT_RUN")
CRITERION_STATUSES: Final = ("PASSED", "FAILED", "BLOCKED", "NOT_COVERED", "NOT_RUN")
STEP_STATUSES: Final = ("DONE", "FAILED", "BLOCKED", "SKIPPED")
BROWSER_NAMES: Final = ("chrome", "firefox")

MAX_PATHS: Final = 20
MAX_STEPS: Final = 12
MAX_CRITERIA_PER_PATH: Final = 6
MAX_TARGET_NAME_LENGTH: Final = 200
MAX_STEP_VALUE_LENGTH: Final = 200
MAX_EXPECTED_TEXT_LENGTH: Final = 200
MAX_PATH_HEADING_LENGTH: Final = 120
MAX_REASON_LENGTH: Final = 300
MAX_SNAPSHOT_ELEMENTS: Final = 150
MAX_SNAPSHOT_TEXT_LENGTH: Final = 6000
MAX_SNAPSHOT_OPTIONS: Final = 20
MAX_EARLIER_PATHS: Final = 5
MAX_BROWSERS: Final = 3
MAX_RESULTS: Final = MAX_PATHS * MAX_BROWSERS
MAX_STEP_DETAIL_LENGTH: Final = 300
MAX_PAGE_TEXT_LENGTH: Final = 1500
MAX_SCREENSHOT_PATH_LENGTH: Final = 200
MAX_ADDRESS_LENGTH: Final = 500
MAX_BROWSER_VERSION_LENGTH: Final = 80
MAX_FOLDER_TEST_RUNS: Final = 20


@dataclass(frozen=True, slots=True)
class ProjectStateSources:
    aligned: Mapping[str, object] | None = None
    changes: tuple[Mapping[str, object], ...] = ()
    runs: tuple[Mapping[str, object], ...] = ()
    tasks: tuple[Mapping[str, object], ...] = ()
    tests: tuple[Mapping[str, object], ...] = ()

    @property
    def is_empty(self) -> bool:
        return (
            self.aligned is None
            and not self.changes
            and not self.runs
            and not self.tasks
            and not self.tests
        )

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
    "APPLICATION_KINDS",
    "BROWSER_NAMES",
    "CHANGE_REVIEWS_KIND",
    "CRITERION_STATUSES",
    "CRITIQUE_VERDICTS",
    "DECISIONS",
    "FEEDBACK_CHANGES",
    "FEEDBACK_TESTS",
    "FILE_KINDS",
    "INTERACTIVE_ROLES",
    "MAX_ACTION_LENGTH",
    "MAX_ADDRESS_LENGTH",
    "MAX_AUTHOR_LENGTH",
    "MAX_BROWSERS",
    "MAX_BROWSER_VERSION_LENGTH",
    "MAX_COMMIT_LENGTH",
    "MAX_CONTEXT_DIFF_LENGTH",
    "MAX_CRITERIA_PER_PATH",
    "MAX_DESIGN_REQUEST_LENGTH",
    "MAX_DIFF_LENGTH",
    "MAX_EARLIER_PATHS",
    "MAX_EXPECTED_TEXT_LENGTH",
    "MAX_FILES",
    "MAX_FINDINGS",
    "MAX_FINDING_LENGTH",
    "MAX_FOLDER_TEST_RUNS",
    "MAX_MESSAGE_LENGTH",
    "MAX_MODEL_TASKS",
    "MAX_NOTE_LENGTH",
    "MAX_PAGE_TEXT_LENGTH",
    "MAX_PATHS",
    "MAX_PATH_HEADING_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_REASON_LENGTH",
    "MAX_REQUIREMENTS_REQUEST_LENGTH",
    "MAX_RESULTS",
    "MAX_SCREENSHOT_PATH_LENGTH",
    "MAX_SNAPSHOT_ELEMENTS",
    "MAX_SNAPSHOT_OPTIONS",
    "MAX_SNAPSHOT_TEXT_LENGTH",
    "MAX_STEPS",
    "MAX_STEP_DETAIL_LENGTH",
    "MAX_STEP_VALUE_LENGTH",
    "MAX_SUMMARY_LENGTH",
    "MAX_TARGET_NAME_LENGTH",
    "MAX_TASKS",
    "MAX_TASK_LENGTH",
    "MIN_COMMIT_LENGTH",
    "PATH_STATUSES",
    "SEVERITIES",
    "STATE_DOCUMENT",
    "STATE_FOLDER",
    "STATE_KIND",
    "STATE_TEXT",
    "STEP_STATUSES",
    "TASK_STATUSES",
    "TEST_ACTIONS",
    "TEST_EXPECTATIONS",
    "TEST_KEYS",
    "TEST_REVIEWS_KIND",
    "TEST_ROLES",
    "VERDICTS",
    "ProjectStateSources",
]
