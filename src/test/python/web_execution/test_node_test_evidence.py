"""A Node process that exits zero without executing tests cannot qualify as TEST passed."""

import pytest

from orchestwin.web_execution.node_test_evidence import failure_findings, has_executed_passing_tests


def summary(*, passed=2, failed=0, cancelled=0, skipped=0, todo=0):
    return f"# Subtest: addition returns the sum\nok 1 - addition returns the sum\n  ---\n  duration_ms: 1\n  type: 'test'\n  ...\n# tests {passed + failed + cancelled + skipped + todo}\n# suites 0\n# pass {passed}\n# fail {failed}\n# cancelled {cancelled}\n# skipped {skipped}\n# todo {todo}\n# duration_ms 12.3\n".encode()


def test_completed_tests_with_bounded_skips_are_observed():
    assert has_executed_passing_tests(summary())
    assert has_executed_passing_tests(summary(skipped=1))


def test_automatic_file_entry_does_not_count_as_an_application_test():
    raw = summary(passed=1).replace(b"addition returns the sum", b"app.test.cjs")
    assert not has_executed_passing_tests(raw, ("./app.test.cjs",))
    assert has_executed_passing_tests(summary(passed=1), ("./app.test.cjs",))


@pytest.mark.parametrize("directive", ["SKIP", "TODO"])
def test_empty_file_and_nonexecuted_suite_do_not_count_as_a_passing_test(directive):
    raw = (
        summary(passed=1, skipped=1).replace(b"addition returns the sum", b"empty.test.cjs")
        + (
            f"# Subtest: suite\n    # Subtest: not executed\n    ok 1 - not executed # {directive}\n"
            "      ---\n      type: 'test'\n      ...\n"
            "ok 2 - suite\n  ---\n  type: 'suite'\n  ...\n"
        ).encode()
    )
    assert not has_executed_passing_tests(raw, ("./empty.test.cjs", "./skipped.test.cjs"))


def test_passing_nested_test_counts_and_suite_record_alone_does_not():
    leaf = summary(passed=1)
    nested = b"\n".join(b"    " + line for line in leaf.splitlines())
    counts = leaf[leaf.index(b"# tests ") :]
    assert has_executed_passing_tests(nested + b"\n" + counts)
    assert not has_executed_passing_tests(leaf.replace(b"type: 'test'", b"type: 'suite'"))


def test_a_passing_record_without_complete_node_diagnostics_is_not_accepted():
    assert not has_executed_passing_tests(summary().replace(b"  ...\n", b""))


def test_runtime_error_keeps_actual_message_and_source_location_for_repair():
    findings = failure_findings(
        b"# /workspace/app.test.cjs:4\n# ReferenceError: describe is not defined\n", b""
    )
    assert len(findings) == 1
    assert findings[0].message == "ReferenceError: describe is not defined"
    assert findings[0].location == "app.test.cjs:4"
    assert findings[0].source_tool == "node:test"


def test_absent_diagnostic_does_not_invent_a_failure_message():
    assert failure_findings(b"", b"") == ()


def test_errors_from_different_files_keep_their_own_locations():
    findings = failure_findings(
        b"# /workspace/first.test.cjs:4\n# ReferenceError: first is not defined\n\n# /workspace/second.test.cjs:9\n# TypeError: second is not a function\n",
        b"",
    )
    assert {item.location for item in findings} == {"first.test.cjs:4", "second.test.cjs:9"}


def test_same_message_with_known_and_unknown_locations_remains_valid():
    findings = failure_findings(
        b"# ReferenceError: missing is not defined\n\n# /workspace/app.test.cjs:3\n# ReferenceError: missing is not defined\n",
        b"",
    )
    assert [item.location for item in findings] == [None, "app.test.cjs:3"]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"all tests passed",
        summary(passed=0),
        summary(passed=0, skipped=2),
        summary(failed=1),
        summary(cancelled=1),
        summary().replace(b"# tests 2", b"# tests 3"),
    ],
)
def test_missing_empty_skipped_failed_or_inconsistent_summaries_are_rejected(raw):
    assert not has_executed_passing_tests(raw)
