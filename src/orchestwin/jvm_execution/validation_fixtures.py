"""Closed, deterministic JVM Level D fixtures, including intentional real failures."""

import hashlib
import json
from pathlib import Path

from orchestwin.jvm_execution.operation_governance import content_hash
from orchestwin.jvm_execution.source_policy import pinned_build_files
from orchestwin.jvm_execution.workspaces import portable_path, read_regular_file

CASES = ("positive", "compile_failure", "test_failure", "runtime_failure", "timeout")
FIXTURES = {
    "JVM_JAVA": "jvm-java-greeting",
    "JVM_KOTLIN": "jvm-kotlin-calculator",
    "JVM_SCALA": "jvm-scala-greeting",
}


def fixture_bytes(repo: Path, target, case="positive"):
    if case not in CASES:
        raise ValueError("JVM_VALIDATION_CASE_UNKNOWN")
    root = repo / "src/test/fixtures/jvm_execution" / FIXTURES[target.value]
    manifest = json.loads(read_regular_file(root / "fixture.json", maximum_bytes=32768))
    files = pinned_build_files(target, repo_root=repo)
    for path in manifest["source_paths"]:
        if path.startswith("src/"):
            files[path] = read_regular_file(root / portable_path(path), maximum_bytes=1024 * 1024)
    main = next(name for name in files if name.endswith(("/Main.java", "/Main.kt", "/Main.scala")))
    test = next(name for name in files if name.startswith("src/test/"))
    if case == "compile_failure":
        files[main] += b"\nORCHESTWIN_INTENTIONAL_COMPILER_ERROR\n"
    elif case == "test_failure":
        text = files[test].decode()
        if target.value == "JVM_KOTLIN":
            text = text.replace("assertEquals(42,", "assertEquals(-999,", 1)
        else:
            text = text.replace('"Hello, JVM!"', '"ORCHESTWIN_INTENTIONAL_TEST_FAILURE"', 1)
        files[test] = text.encode()
    elif case in {"runtime_failure", "timeout"}:
        if target.value == "JVM_JAVA":
            code = (
                'throw new IllegalStateException("ORCHESTWIN_RUNTIME_FAILURE");'
                if case == "runtime_failure"
                else 'System.out.println("ORCHESTWIN_TIMEOUT_PROBE"); while (true) { Thread.sleep(1000); }'
            )
            text = f"package org.orchestwin.greeting;\npublic final class Main {{ public static void main(String[] args) throws InterruptedException {{ {code} }} }}\n"
        elif target.value == "JVM_KOTLIN":
            code = (
                'error("ORCHESTWIN_RUNTIME_FAILURE")'
                if case == "runtime_failure"
                else 'println("ORCHESTWIN_TIMEOUT_PROBE"); while (true) { Thread.sleep(1000) }'
            )
            text = f"package org.orchestwin.calculator\nfun main() {{ {code} }}\n"
        else:
            code = (
                'throw new RuntimeException("ORCHESTWIN_RUNTIME_FAILURE")'
                if case == "runtime_failure"
                else 'println("ORCHESTWIN_TIMEOUT_PROBE")\n    while true do Thread.sleep(1000)'
            )
            text = f"package org.orchestwin.greeting\nobject Main:\n  def main(args: Array[String]): Unit =\n    {code}\n"
        files[main] = text.encode()
    return files


def fixture_inventory(files):
    return {
        path: {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
        for path, data in sorted(files.items())
    }


def fixture_bundle(repo, target):
    cases = {case: fixture_inventory(fixture_bytes(repo, target, case)) for case in CASES}
    return {"target": target.value, "cases": cases, "content_hash": content_hash(cases)}
