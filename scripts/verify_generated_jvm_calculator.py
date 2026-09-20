"""Prepare or independently verify a generated console calculator.

Only generate-development calls the model; no command trains, edits generated
sources, approves gates or publishes Level D. Governed checks require the exact execution
receipt; development probes retain a separate receipt and never publish to the API.
Only pinned local Docker images execute application code.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.jvm_execution.workspaces import read_regular_file  # noqa: E402
from orchestwin.sandbox.docker_runtime import AsyncioHostProcessRunner  # noqa: E402

PROFILES = {
    "JVM_JAVA": ("jvm.java-gradle", "org.orchestwin.greeting.Main", "21", "9.5.0"),
    "JVM_KOTLIN": ("jvm.kotlin-gradle", "org.orchestwin.calculator.MainKt", "2.4.10", "9.5.0"),
    "JVM_SCALA": ("jvm.scala-sbt", "org.orchestwin.greeting.Main", "3.3.8", "1.12.14"),
}
INPUTS = (
    ("addition", "9", "+", "3"),
    ("subtraction", "9", "-", "3"),
    ("multiplication", "9", "*", "3"),
    ("division", "9", "/", "3"),
    ("comma-decimal", "1,5", "+", "2.25"),
    ("fractional-division", "7", "/", "2"),
    ("decimal-precision", "0.1", "+", "0.2"),
    ("negative-input", "-2.5", "*", "4"),
    ("negative-subtraction", "-5", "-", "-3"),
    ("large-result", "999999999", "+", "1"),
    ("whitespace", " 1.5 ", "+", " 2 "),
    ("zero-numerator", "0", "/", "7"),
    ("zero-divisor", "4", "/", "0"),
    ("negative-zero-divisor", "4", "/", "-0.0"),
    ("empty-left", "", "+", "2"),
    ("empty-right", "2", "+", " "),
    ("invalid-number", "abc", "+", "2"),
    ("nan", "NaN", "+", "2"),
    ("infinity", "Infinity", "+", "2"),
    ("unsupported-operation", "4", "%", "2"),
)
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)")
JAVA_PROBE = r"""
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Base64;

class CalculatorProbe {
  static String encoded(String value) {
    return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
  }
  public static void main(String[] args) throws Exception {
    Class<?> type = Class.forName(args[0]);
    Object receiver = null;
    Method method;
    try {
      method = type.getMethod("calculate", String.class, String.class, String.class);
      if (!Modifier.isStatic(method.getModifiers())) receiver = type.getConstructor().newInstance();
    } catch (NoSuchMethodException absentForwarder) {
      type = Class.forName(args[0] + "$");
      receiver = type.getField("MODULE$").get(null);
      method = type.getMethod("calculate", String.class, String.class, String.class);
    }
    for (String row : Files.readAllLines(Path.of(args[1]), StandardCharsets.UTF_8)) {
      String[] cells = row.split("\t", -1);
      try {
        Object value = method.invoke(receiver, cells[1], cells[2], cells[3]);
        if (!(value instanceof Number)) throw new IllegalStateException("NON_NUMERIC_RETURN");
        System.out.println(args[2] + cells[0] + "\tVALUE\t" + ((Number)value).doubleValue());
      } catch (InvocationTargetException invocation) {
        Throwable cause = invocation.getCause();
        System.out.println(args[2] + cells[0] + "\tERROR\t" + encoded(cause.getClass().getName())
          + "\t" + encoded(String.valueOf(cause.getMessage())));
      }
    }
  }
}
""".lstrip()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def identity(data):
    return {"sha256_digest": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def expected(left, operation, right):
    if not NUMBER.fullmatch(left.strip()) or not NUMBER.fullmatch(right.strip()):
        return {"kind": "ERROR"}
    a, b = (Decimal(value.strip().replace(",", ".")) for value in (left, right))
    if operation not in {"+", "-", "*", "/"} or (operation == "/" and b == 0):
        return {"kind": "ERROR"}
    result = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b}[
        operation
    ]()
    return {"kind": "VALUE", "value": str(result)}


def contract(target):
    profile, main_class, language_version, build_version = PROFILES[target]
    return {
        "schema_version": 1,
        "purpose": "INDEPENDENT_GENERATED_JVM_CALCULATOR_CHECK",
        "target": target,
        "profile_id": profile,
        "profile_version": "1.0.0",
        "jdk_major": 21,
        "language_version": language_version,
        "build_tool_version": build_version,
        "main_class": main_class,
        "approved_requirement_text": (
            "Build a console calculator. On the pinned entrypoint expose public "
            "calculate(left: String, operation: String, right: String): Double/double. "
            "Use a public static method on Java Main, a top-level function in Kotlin Main.kt, "
            "or a public method of Scala object Main. Support +, -, *, /, signed decimal "
            "numbers with dot or comma, and surrounding whitespace. Return the actual numeric "
            "result. Reject empty or invalid numbers, NaN, infinity, unknown operations and "
            "division by zero (including -0.0) with IllegalArgumentException or ArithmeticException "
            "and a useful message. The no-argument main must demonstrate 9 + 3, print the actual "
            "result and terminate. Do not wait for input, start a server, or emit HTML. "
            "Preserve the reviewed build recipe and exact package/entrypoint. Generate the "
            "implementation and its normal tests; independent verification is performed separately."
        ),
        "checks": [
            {
                "id": name,
                "left": left,
                "operation": op,
                "right": right,
                "expected": expected(left, op, right),
            }
            for name, left, op, right in INPUTS
        ],
        "prerequisites": [
            "Generate fresh sources from these approved requirements using the selected real model.",
            "Complete governed JVM execution and export its immutable attempt and source snapshots.",
            "Export the application JAR recorded in that attempt and its runtime dependency JARs.",
            "Use an existing pinned local JDK 21 Docker image; no image pull or network is performed.",
        ],
        "claims": {"executed": False, "graphical_preview": False, "level_d_publication": False},
    }


def read_snapshot(path):
    document = json.loads(read_regular_file(path.absolute(), maximum_bytes=8 * 1024 * 1024))
    return document.get("snapshot", document)


def check_binding(source, attempt, target, jar_data):
    source_hash = hashlib.sha256(
        canonical(
            {
                key: value
                for key, value in source.items()
                if key not in {"content_hash", "source_tree_hash"}
            }
        )
    ).hexdigest()
    attempt_hash = hashlib.sha256(
        canonical({key: value for key, value in attempt.items() if key != "content_hash"})
    ).hexdigest()
    if source_hash != source["content_hash"] or attempt_hash != attempt["content_hash"]:
        raise ValueError("INPUT_SNAPSHOT_HASH_MISMATCH")
    if source["origin"] != "GENERATED_PLAN":
        raise ValueError("FRESH_GENERATED_SOURCE_REQUIRED")
    reference = attempt["source_revision"]
    if any(
        (
            source["target_selection"]["target"] != target,
            attempt["report"]["target_selection"]["target"] != target,
            attempt["profile_id"] != PROFILES[target][0],
            attempt["profile_version"] != "1.0.0",
            reference["revision_id"] != source["id"],
            reference["content_hash"] != source["content_hash"],
            reference["source_tree_hash"] != source["source_tree_hash"],
            reference["project_id"] != source["project_id"],
            reference["version_number"] != source["version_number"],
        )
    ):
        raise ValueError("EXECUTION_SOURCE_BINDING_MISMATCH")
    if attempt["report"]["status"] != "PASSED":
        raise ValueError("SUCCESSFUL_GOVERNED_EXECUTION_REQUIRED")
    jar = identity(jar_data)
    artifacts = [
        ref for phase in attempt["report"]["phase_results"] for ref in phase["artifact_refs"]
    ]
    if not any(all(ref.get(key) == value for key, value in jar.items()) for ref in artifacts):
        raise ValueError("APPLICATION_JAR_NOT_IN_EXECUTION_EVIDENCE")


def evaluate_output(text, nonce):
    observations = {}
    for line in text.splitlines():
        if not line.startswith(nonce):
            continue
        cells = line[len(nonce) :].split("\t")
        if len(cells) not in {3, 4} or cells[0] in observations:
            raise ValueError("INVALID_OR_DUPLICATE_PROBE_RESULT")
        observations[cells[0]] = cells[1:]
    if set(observations) != {row[0] for row in INPUTS}:
        raise ValueError("INCOMPLETE_PROBE_RESULTS")
    results = []
    for name, left, op, right in INPUTS:
        wanted, actual = expected(left, op, right), observations[name]
        passed = False
        observation = {"kind": actual[0]}
        if actual[0] == "VALUE" and len(actual) == 2:
            value = float(actual[1])
            observation["value"] = actual[1]
            passed = (
                wanted["kind"] == "VALUE"
                and math.isfinite(value)
                and math.isclose(value, float(wanted["value"]), abs_tol=1e-12, rel_tol=1e-12)
            )
        elif actual[0] == "ERROR" and len(actual) == 3:
            error_type, message = (
                base64.b64decode(item, validate=True).decode("utf-8") for item in actual[1:]
            )
            observation.update(error_type=error_type, message=message)
            passed = (
                wanted["kind"] == "ERROR"
                and error_type
                in {
                    "java.lang.ArithmeticException",
                    "java.lang.IllegalArgumentException",
                    "java.lang.NumberFormatException",
                }
                and bool(message.strip())
                and message != "null"
            )
        results.append({"id": name, "expected": wanted, "observed": observation, "passed": passed})
    return results


def console_demo_passed(text):
    numbers = re.findall(r"(?<![A-Za-z0-9])[+-]?[0-9]+(?:[.,][0-9]+)?", text)
    return bool(numbers) and Decimal(numbers[-1].replace(",", ".")) == 12


async def process(arguments, timeout=60):
    result = await AsyncioHostProcessRunner().run(
        tuple(arguments),
        timeout_seconds=timeout,
        maximum_output_bytes_per_stream=1024 * 1024,
        environment_overrides={},
    )
    return {
        "status": result.status.value,
        "exit_code": result.exit_code,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
    }


async def readiness(configuration=None):
    """Inspect trusted runtime inputs and live Docker metadata without starting containers."""
    from orchestwin.api.governed_jvm_context import GovernedJvmSettings
    from orchestwin.jvm_execution.dependency_network import verify_dependency_network
    from orchestwin.jvm_execution.launcher_cache import GRADLE_DISTRIBUTION_SHA256
    from orchestwin.jvm_execution.source_policy import pinned_build_files
    from orchestwin.sandbox.execution_profiles import ExecutionTarget

    values = {} if configuration is None else read_snapshot(configuration)
    config = GovernedJvmSettings(**values)
    blockers = []
    if not config.enabled:
        blockers.append("JVM_EXECUTION_RUNTIME_DISABLED")
    for target in PROFILES:
        try:
            pinned_build_files(ExecutionTarget(target), repo_root=config.repo_root or ROOT)
        except (OSError, ValueError):
            blockers.append(f"PINNED_RECIPE_UNAVAILABLE:{target}")
    if config.enabled:
        for family in ("gradle", "sbt"):
            image = getattr(config, f"{family}_image_id")
            result = await process(
                [
                    "docker",
                    "--context",
                    config.docker_context,
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    image,
                ]
            )
            if result["exit_code"] != 0 or result["stdout"].strip() != image:
                blockers.append(f"RUNNER_IMAGE_UNAVAILABLE:{family}")
        try:
            raw = read_regular_file(config.distribution_path, maximum_bytes=256 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != GRADLE_DISTRIBUTION_SHA256:
                blockers.append("GRADLE_DISTRIBUTION_HASH_MISMATCH")
        except (OSError, ValueError):
            blockers.append("GRADLE_DISTRIBUTION_UNAVAILABLE")
        try:
            await verify_dependency_network(
                config.dependency_network_manifest,
                expected_content_hash=config.dependency_network_manifest_hash,
                docker_context=config.docker_context,
            )
        except (OSError, ValueError, RuntimeError):
            blockers.append("DEPENDENCY_NETWORK_UNAVAILABLE_OR_CHANGED")
    return {
        "runtime_inputs_ready": not blockers,
        "blockers": blockers,
        "catalog_validation_checked": False,
        "executed_application": False,
        "level_d_publication": False,
    }


async def verify(args):
    source, attempt = read_snapshot(args.source_revision), read_snapshot(args.execution_attempt)
    app_data = read_regular_file(args.application_jar.absolute(), maximum_bytes=64 * 1024 * 1024)
    check_binding(source, attempt, args.target, app_data)
    return await verify_jar_bundle(
        args,
        source=source,
        app_data=app_data,
        binding={
            "mode": "SUPPLEMENTARY_GOVERNED_CHECK",
            "execution_attempt_id": attempt["id"],
            "execution_attempt_hash": attempt["content_hash"],
        },
    )


async def verify_jar_bundle(args, *, source, app_data, binding):
    """Check an already bound bundle; each caller must establish its provenance first."""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.image):
        raise ValueError("PINNED_LOCAL_IMAGE_ID_REQUIRED")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.docker_context):
        raise ValueError("DOCKER_CONTEXT_INVALID")
    if len(args.runtime_jar) > 64:
        raise ValueError("TOO_MANY_RUNTIME_JARS")
    args.output.mkdir(parents=True, exist_ok=False)
    bundle = args.output / "probe-inputs"
    bundle.mkdir()
    (bundle / "application.jar").write_bytes(app_data)
    dependencies = []
    total_dependency_bytes = 0
    for index, path in enumerate(args.runtime_jar):
        raw = read_regular_file(path.absolute(), maximum_bytes=64 * 1024 * 1024)
        total_dependency_bytes += len(raw)
        if total_dependency_bytes > 256 * 1024 * 1024:
            raise ValueError("RUNTIME_DEPENDENCY_BUDGET_EXCEEDED")
        destination = f"dependency-{index:02d}.jar"
        (bundle / destination).write_bytes(raw)
        dependencies.append({"name": path.name, "mounted_name": destination, **identity(raw)})
    (bundle / "CalculatorProbe.java").write_text(JAVA_PROBE, encoding="utf-8")
    (bundle / "cases.tsv").write_text(
        "\n".join("\t".join(row) for row in INPUTS) + "\n", encoding="utf-8"
    )
    nonce = f"ORCHESTWIN_{uuid4().hex}_"
    classpath = ":".join(
        [
            "/probe/application.jar",
            *[f"/probe/{dependency['mounted_name']}" for dependency in dependencies],
        ]
    )
    base = ["docker", "--context", args.docker_context]
    image = await process([*base, "image", "inspect", "--format", "{{.Id}}", args.image])
    if image["exit_code"] != 0 or image["stdout"].strip() != args.image:
        raise ValueError("PINNED_DOCKER_IMAGE_UNAVAILABLE")
    mounted = str(bundle.resolve())
    if "," in mounted:
        raise ValueError("DOCKER_MOUNT_PATH_CONTAINS_COMMA")
    records = []
    for label, invocation in (
        (
            "independent-cases",
            ["/probe/CalculatorProbe.java", PROFILES[args.target][1], "/probe/cases.tsv", nonce],
        ),
        ("console-demo", [PROFILES[args.target][1]]),
    ):
        container = "orchestwin-calculator-check-" + uuid4().hex
        command = [
            *base,
            "run",
            "--name",
            container,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=512m",
            "--cpus=1",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--mount",
            f"type=bind,source={mounted},target=/probe,readonly",
            "--entrypoint=java",
            args.image,
            "-Xmx256m",
            "-cp",
            classpath,
            *invocation,
        ]
        try:
            observation = await process(command)
        finally:
            cleanup = await process([*base, "rm", "--force", container], timeout=15)
        (args.output / f"{label}.stdout.log").write_text(observation["stdout"], encoding="utf-8")
        (args.output / f"{label}.stderr.log").write_text(observation["stderr"], encoding="utf-8")
        records.append(
            {
                "label": label,
                "command": command,
                **observation,
                "cleanup_confirmed": cleanup["exit_code"] == 0,
            }
        )
    failure = None
    try:
        cases = evaluate_output(records[0]["stdout"], nonce) if records[0]["exit_code"] == 0 else []
    except ValueError as error:
        cases, failure = [], str(error)
    passed = (
        bool(cases)
        and all(case["passed"] for case in cases)
        and all(record["exit_code"] == 0 and record["cleanup_confirmed"] for record in records)
        and console_demo_passed(records[1]["stdout"])
    )
    report = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "purpose": "SUPPLEMENTARY_GENERATED_CONSOLE_CALCULATOR_VERIFICATION",
        "target": args.target,
        "profile_id": PROFILES[args.target][0],
        "source_revision_id": source["id"],
        "source_content_hash": source["content_hash"],
        **binding,
        "source_origin": source["origin"],
        "application_jar": identity(app_data),
        "runtime_dependencies": dependencies,
        "image_id": args.image,
        "contract_hash": hashlib.sha256(canonical(contract(args.target))).hexdigest(),
        "probe_hash": hashlib.sha256(JAVA_PROBE.encode()).hexdigest(),
        "checks": cases,
        "probe_failure": failure,
        "console_demo_expected_result": "12",
        "console_demo_passed": records[1]["exit_code"] == 0
        and console_demo_passed(records[1]["stdout"]),
        "processes": records,
        "passed": passed,
        "claims": {
            "graphical_preview": False,
            "level_d_publication": False,
            "proves_autonomous_model_quality": False,
        },
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser(
        "contract", help="Print the generation requirement and checks only"
    )
    prepare.add_argument("--target", choices=PROFILES, required=True)
    preflight = commands.add_parser(
        "readiness", help="Inspect runner inputs without executing apps"
    )
    preflight.add_argument("--configuration", type=Path)
    command = commands.add_parser(
        "verify", help="Run supplementary checks after governed execution"
    )
    command.add_argument("--target", choices=PROFILES, required=True)
    for option in ("source-revision", "execution-attempt", "application-jar", "output"):
        command.add_argument(f"--{option}", type=Path, required=True)
    command.add_argument("--runtime-jar", type=Path, action="append", default=[])
    command.add_argument("--image", required=True, help="Existing local sha256:<64 hex> image ID")
    command.add_argument("--docker-context", default="desktop-linux")
    development = commands.add_parser(
        "development-probe",
        help="Compile exact model-generated sources in isolation; no governed publication",
    )
    development.add_argument("--target", choices=PROFILES, required=True)
    for option in (
        "configuration",
        "source-revision",
        "source-root",
        "generation-evidence",
        "output",
    ):
        development.add_argument(f"--{option}", type=Path, required=True)
    generation = commands.add_parser(
        "generate-development",
        help="Call the real source adapter and retain unpublished original JVM sources",
    )
    generation.add_argument("--target", choices=PROFILES, required=True)
    for option in ("configuration", "runtime-config", "output"):
        generation.add_argument(f"--{option}", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "contract":
        print(json.dumps(contract(args.target), indent=2))
        return 0
    try:
        options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        if args.action == "readiness":
            result = asyncio.run(readiness(args.configuration), **options)
            print(json.dumps(result, indent=2))
            return 0 if result["runtime_inputs_ready"] else 1
        if args.action == "development-probe":
            from scripts.jvm_calculator_development_probe import development_probe

            report = asyncio.run(development_probe(args), **options)
        elif args.action == "generate-development":
            from scripts.jvm_calculator_development_probe import generate_development

            report = asyncio.run(generate_development(args), **options)
        else:
            report = asyncio.run(verify(args), **options)
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "checks": len(report["checks"]),
                    "report": str(args.output / "report.json"),
                }
            )
        )
        return 0 if report["passed"] else 1
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
