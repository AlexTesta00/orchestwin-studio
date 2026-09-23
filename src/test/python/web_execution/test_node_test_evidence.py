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


TAP_FAILURES = (
    b"TAP version 13\n"
    b"# Subtest: calculateTip calcola correttamente la mancia e il totale\n"
    b"ok 1 - calculateTip calcola correttamente la mancia e il totale\n"
    b"  ---\n  duration_ms: 0.787863\n  type: 'test'\n  ...\n"
    b"# Subtest: calculateTip gestisce valori decimali correttamente\n"
    b"not ok 2 - calculateTip gestisce valori decimali correttamente\n"
    b"  ---\n  duration_ms: 0.758694\n  type: 'test'\n"
    b"  location: '/workspace/app.test.cjs:17:1'\n"
    b"  failureType: 'testCodeFailure'\n"
    b"  error: |-\n    Expected values to be strictly equal:\n    \n    4.575 !== 4.58\n    \n"
    b"  code: 'ERR_ASSERTION'\n  name: 'AssertionError'\n  expected: 4.58\n  actual: 4.575\n"
    b"  operator: 'strictEqual'\n"
    b"  stack: |-\n    TestContext.<anonymous> (/workspace/app.test.cjs:19:10)\n"
    b"    Test.runInAsyncScope (node:async_hooks:226:14)\n"
    b"  ...\n"
    b"# Subtest: validateInput accetta input validi\n"
    b"not ok 3 - validateInput accetta input validi\n"
    b"  ---\n  duration_ms: 0.123052\n  type: 'test'\n"
    b"  location: '/workspace/app.test.cjs:23:1'\n"
    b"  failureType: 'testCodeFailure'\n"
    b"  error: 'hideErrorMessage is not defined'\n"
    b"  code: 'ERR_TEST_FAILURE'\n  name: 'ReferenceError'\n"
    b"  stack: |-\n    validateInput (/workspace/app.js:24:3)\n"
    b"    TestContext.<anonymous> (/workspace/app.test.cjs:24:19)\n"
    b"  ...\n"
    b"1..3\n# tests 3\n# suites 0\n# pass 1\n# fail 2\n# cancelled 0\n# skipped 0\n# todo 0\n"
    b"# duration_ms 70\n"
)


def test_tap_records_name_the_failing_test_its_error_and_the_raising_frame():
    findings = failure_findings(TAP_FAILURES, b"")
    assert [(item.code, item.message, item.location) for item in findings] == [
        (
            "NODE_TEST_ASSERTIONERROR",
            "calculateTip gestisce valori decimali correttamente: "
            "Expected values to be strictly equal: 4.575 !== 4.58",
            "app.test.cjs:19:10",
        ),
        (
            "NODE_TEST_REFERENCEERROR",
            "validateInput accetta input validi: hideErrorMessage is not defined",
            "app.js:24:3",
        ),
    ]
    assert all(item.source_tool == "node:test" for item in findings)


def test_first_error_and_stack_win_when_an_assertion_wraps_an_inner_error():
    raw = (
        b"TAP version 13\n# Subtest: validateInput throws error for negative number\n"
        b"not ok 1 - validateInput throws error for negative number\n"
        b"  ---\n  duration_ms: 0.5\n  type: 'test'\n  location: '/workspace/app.test.cjs:16:1'\n"
        b"  failureType: 'testCodeFailure'\n"
        b"  error: |-\n    The input did not match the regular expression /negativa/. Input:\n"
        b"    \n    'Error: Input non valido'\n    \n"
        b"  code: 'ERR_ASSERTION'\n  name: 'AssertionError'\n  expected:\n  actual:\n"
        b"  error: 'Input non valido'\n"
        b"  stack: |-\n    validateInput (/workspace/app.js:18:11)\n    /workspace/app.test.cjs:18:5\n"
        b"  operator: 'throws'\n"
        b"  stack: |-\n    TestContext.<anonymous> (/workspace/app.test.cjs:17:10)\n"
        b"  ...\n1..1\n# tests 1\n# suites 0\n# pass 0\n# fail 1\n# cancelled 0\n# skipped 0\n"
        b"# todo 0\n# duration_ms 7\n"
    )
    (finding,) = failure_findings(raw, b"")
    assert finding.code == "NODE_TEST_ASSERTIONERROR"
    assert finding.message == (
        "validateInput throws error for negative number: The input did not match the regular "
        "expression /negativa/. Input: 'Error: Input non valido'"
    )
    assert finding.location == "app.js:18:11"


def test_suite_records_are_skipped_and_nested_leaves_keep_their_own_location():
    raw = (
        b"TAP version 13\n# Subtest: suite\n"
        b"    # Subtest: leaf\n    not ok 1 - leaf\n      ---\n      duration_ms: 1\n"
        b"      type: 'test'\n      location: '/workspace/app.test.cjs:5:3'\n"
        b"      failureType: 'testCodeFailure'\n      error: 'boom'\n"
        b"      code: 'ERR_TEST_FAILURE'\n      name: 'Error'\n"
        b"      stack: |-\n        TestContext.<anonymous> (node:internal/test_runner/test:1:1)\n"
        b"      ...\n    1..1\n"
        b"not ok 1 - suite\n  ---\n  duration_ms: 2\n  type: 'suite'\n"
        b"  location: '/workspace/app.test.cjs:4:1'\n  failureType: 'subtestsFailed'\n"
        b"  error: '1 subtest failed'\n  code: 'ERR_TEST_FAILURE'\n  ...\n"
        b"1..1\n# tests 1\n# suites 1\n# pass 0\n# fail 1\n# cancelled 0\n# skipped 0\n"
        b"# todo 0\n# duration_ms 3\n"
    )
    (finding,) = failure_findings(raw, b"")
    assert (finding.code, finding.message, finding.location) == (
        "NODE_TEST_ERROR",
        "leaf: boom",
        "app.test.cjs:5:3",
    )


def test_tap_findings_stay_bounded_to_eight_records():
    record = "# Subtest: t{n}\nnot ok {n} - t{n}\n  ---\n  type: 'test'\n  error: 'e{n}'\n  ...\n"
    raw = ("TAP version 13\n" + "".join(record.format(n=n) for n in range(1, 12))).encode()
    findings = failure_findings(raw, b"")
    assert len(findings) == 8
    assert {item.code for item in findings} == {"NODE_TEST_FAILURE"}
