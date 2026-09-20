"""Seal verified JVM observations and atomically publish their exact evidence catalog.

Publication requires an independently supplied package hash. It never executes
application code, decides gates, or writes project/attempt/source records.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from orchestwin.jvm_execution.operation_governance import content_hash
from orchestwin.jvm_execution.profile_registry import evaluate_sprint09_jvm_profile_promotions
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.jvm_execution.validation_campaign import TARGETS, write_once
from orchestwin.jvm_execution.validation_evidence import (
    JvmProfileValidationEvidence,
    JvmProfileValidationEvidenceCatalog,
    JvmProfileValidationEvidenceKind,
)
from orchestwin.jvm_execution.validation_evidence_persistence import (
    SqlAlchemyJvmValidationEvidenceRepository,
    canonical_jvm_validation_evidence,
)
from orchestwin.jvm_execution.validation_fixtures import fixture_bundle
from orchestwin.jvm_execution.validation_prerequisites import (
    COMPARISON,
    FILESYSTEM_EXCLUSIONS,
    execution_configuration,
)
from orchestwin.jvm_execution.validation_verification import (
    MAX_JSON,
    CampaignVerifier,
    junit_counts,
    read_document,
    require,
    same,
)
from orchestwin.jvm_execution.workspaces import portable_path, read_regular_file

Kind = JvmProfileValidationEvidenceKind
LIMITATIONS = (
    "Validated only on Docker Desktop Linux amd64 with the recorded JDK 21 and pinned toolchains.",
    "Closed single-module CLI recipes only; arbitrary build scripts, plugins and repositories remain unsupported.",
    "Gradle STATIC_CHECKS runs check with tests excluded; it does not claim an additional lint or static-analysis tool.",
    "Reproducibility means independent fresh-cache executions with equal behavior and passing tests; byte-identical images or archives are not guaranteed.",
    "Docker identities are local configuration digests, not registry manifest digests. Recipe comparison excludes timestamps, Docker-injected host files and the historical org.orchestwin.jvm-bootstrap ownership label; all execution configuration must match.",
    "Fixture campaigns use an explicitly designated account in disposable PostgreSQL; original SQL source, attempt and Gate 7 snapshots are retained in the sealed package.",
    "Initial campaign repair descriptions retain a historical web-execution prefix with the exact JVM attempt ID/hash; typed JVM operation and source lineage are verified. The API prefix correction is covered by PostgreSQL regression tests; original evidence is unchanged.",
    "Validation evidence is collected by the trusted local operator; hashes provide integrity, not third-party signatures or a remote CI attestation.",
    "Profile validation does not train twins, validate a thesis case study, or resume any frozen attempt.",
)


def file_identity(path):
    data = read_regular_file(path.absolute(), maximum_bytes=128 * 1024 * 1024)
    return {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def verify_contract_tests(root, repo):
    receipt = read_document(root / "contract-tests.json")
    require(
        receipt["exit_code"] == 0 and receipt["database"] == "DISPOSABLE_TEST_ONLY",
        "CONTRACT_TEST_RUN_FAILED",
    )
    require(receipt["inputs"], "CONTRACT_TEST_INPUTS_MISSING")
    for path, identity in receipt["inputs"].items():
        same(file_identity(repo / portable_path(path)), identity, "TESTED_SOURCE_DRIFT")
    all_counts, passed_cases, skipped_cases = [], set(), set()
    for item in receipt["junit_reports"]:
        path = root / portable_path(item["path"])
        same(file_identity(path), item["identity"], "CONTRACT_TEST_REPORT_CHANGED")
        xml = read_regular_file(path, maximum_bytes=MAX_JSON)
        counts = junit_counts([xml])
        require(
            counts["passed"] > 0 and counts["failed"] == counts["errors"] == 0,
            "CONTRACT_TESTS_NOT_ALL_EXECUTED",
        )
        for case in ElementTree.fromstring(xml).iter("testcase"):
            identity = (case.get("classname"), case.get("name"))
            (skipped_cases if case.find("skipped") is not None else passed_cases).add(identity)
        all_counts.append(counts)
    require(len(all_counts) >= 2, "CONTRACT_TEST_SQL_AND_UNIT_REPORTS_REQUIRED")
    require(skipped_cases <= passed_cases, "SKIPPED_CONTRACT_TESTS_WITHOUT_PLATFORM_COVERAGE")
    return receipt


def verify_recipe(root, repo, family):
    folder = root / "prerequisites" / family
    receipt = read_document(folder / "build.json")
    paths = {f"infra/jvm-runners/Dockerfile.{family}", "infra/jvm-runners/images.lock.json"}
    if family == "gradle":
        paths.add("infra/jvm-runners/resolve-dependencies.gradle.kts")
    require(
        set(receipt["inputs"]) == paths
        and receipt["exit_code"] == receipt["toolchain_exit_code"] == 0,
        "RUNNER_BUILD_FAILED",
    )
    for path, identity in receipt["inputs"].items():
        same(file_identity(repo / path), identity, "RUNNER_RECIPE_DRIFT")
    require(
        file_identity(folder / "build.log")["sha256"] == receipt["log_sha256"], "BUILD_LOG_CHANGED"
    )
    require(
        file_identity(folder / "java-version.log")["sha256"] == receipt["toolchain_sha256"],
        "JDK_LOG_CHANGED",
    )
    jdk = read_regular_file(folder / "java-version.log", maximum_bytes=32768).decode()
    require('version "21.' in jdk, "JDK_21_NOT_OBSERVED")
    image = read_document(folder / "image.json")
    rebuilt_image = read_document(folder / "rebuilt-image.json")
    require(
        rebuilt_image["Id"] == receipt["rebuilt_image_id"]
        and rebuilt_image["Os"] == image["Os"]
        and rebuilt_image["Architecture"] == image["Architecture"],
        "REBUILT_IMAGE_IDENTITY_INVALID",
    )
    same(
        execution_configuration(rebuilt_image["Config"]),
        execution_configuration(image["Config"]),
        "REBUILT_IMAGE_CONFIGURATION_MISMATCH",
    )
    require(
        image["Id"] == receipt["image_id"]
        and image["Os"] == "linux"
        and image["Architecture"] == "amd64"
        and receipt["image_id_kind"] == "LOCAL_CONFIG_DIGEST",
        "RUNNER_IMAGE_MISMATCH",
    )
    first, second = (read_document(folder / f"filesystem-{index}.json") for index in (0, 1))
    same(first, second, "REBUILT_FILESYSTEM_MISMATCH")
    comparison = receipt["filesystem_comparison"]
    require(
        comparison["verified"] is True
        and comparison["containers_removed"] is True
        and comparison["comparison"] == COMPARISON
        and comparison["excluded_docker_injected_files"] == list(FILESYSTEM_EXCLUSIONS)
        and comparison["inventory_hash"] == content_hash(first)
        and comparison["entries"] == len(first),
        "RUNNER_FILESYSTEM_PROOF_INVALID",
    )
    return receipt


def harvest_campaign(*, root, repo_root, distribution_path):
    root, repo = Path(root).absolute(), Path(repo_root).absolute()
    require(not (root / "publication.json").exists(), "PUBLICATION_ALREADY_SEALED")
    terminal = read_document(root / "result.json")
    require(
        terminal["status"] == "PASSED"
        and terminal["cleanup_status"] == "REMOVED"
        and {item["target"] for item in terminal["runs"]} == {target.value for target in TARGETS}
        and all(item["status"] == "PASSED" for item in terminal["runs"]),
        "CAMPAIGN_NOT_COMPLETED",
    )
    tests = verify_contract_tests(root, repo)
    recipes = {family: verify_recipe(root, repo, family) for family in ("gradle", "sbt")}
    images = {family: receipt["image_id"] for family, receipt in recipes.items()}
    environment = read_document(root / "prerequisites/environment.json")
    require(
        environment["OSType"] == "linux" and environment["Architecture"] == "x86_64",
        "ENVIRONMENT_UNSUPPORTED",
    )
    recorded_at = datetime.now(UTC)
    records, summary = [], []
    for target in TARGETS:
        verifier = CampaignVerifier(
            root=root / target.value,
            repo_root=repo,
            target=target,
            images=images,
            distribution_path=distribution_path,
        )
        observations = verifier.verify()
        family = "sbt" if target.value == "JVM_SCALA" else "gradle"
        recipe = recipes[family]
        positive = observations[("positive", "initial")]
        toolchain = {
            "java": recipe["toolchain_sha256"],
            "validate_stdout": positive["phases"]["VALIDATE"]["stdout"],
            "validate_stderr": positive["phases"]["VALIDATE"]["stderr"],
            "setup_stdout": positive["phases"]["SETUP"]["stdout"],
            "image": images[family],
        }
        scope, bundle = jvm_scope_for(target), fixture_bundle(repo, target)
        identity = dict(
            profile_id=scope.profile_id,
            profile_version=scope.profile_version,
            baseline_scope_hash=scope.content_hash,
            runner_image_digest=images[family].removeprefix("sha256:"),
            runner_build_recipe_hash=content_hash(recipe),
            toolchain_manifest_hash=content_hash(toolchain),
            fixture_bundle_hash=bundle["content_hash"],
            environment_fingerprint=content_hash(
                {"daemon": environment, "network": verifier.network["environment"]}
            ),
            recorded_at=recorded_at,
            passed=True,
        )
        documents = [
            (Kind.CONTRACT_TESTS, tests),
            (Kind.RUNNER_IMAGE, read_document(root / "prerequisites" / family / "image.json")),
            (Kind.RUNNER_BUILD_RECIPE, recipe),
            (Kind.TOOLCHAIN_MANIFEST, toolchain),
            (Kind.SOURCE_FIXTURE, bundle),
            (Kind.KNOWN_LIMITATIONS, {"limitations": list(LIMITATIONS)}),
            (
                Kind.FAILURE_MATRIX,
                {
                    case: observations[(case, "initial")]
                    for case in ("compile_failure", "test_failure", "runtime_failure", "timeout")
                },
            ),
            (
                Kind.REPAIR_RERUN,
                {
                    "before": observations[("compile_failure", "initial")],
                    "repair": read_document(
                        verifier.campaign / target.value / "compile_failure/repair/terminal.json"
                    ),
                    "after": observations[("compile_failure", "rerun")],
                },
            ),
            (Kind.REPRODUCIBILITY, positive),
            (Kind.REPRODUCIBILITY, observations[("positive", "repeat")]),
        ]
        documents.extend(
            (kind, positive["phases"][phase])
            for kind, phase in (
                (Kind.VALIDATE_REPORT, "VALIDATE"),
                (Kind.SETUP_REPORT, "SETUP"),
                (Kind.STATIC_CHECK_REPORT, "STATIC_CHECKS"),
                (Kind.BUILD_REPORT, "BUILD"),
                (Kind.TEST_REPORT, "TEST"),
                (Kind.RUN_REPORT, "RUN"),
                (Kind.ARTIFACT_INVENTORY, "COLLECT_ARTIFACTS"),
            )
        )
        for index, (kind, document) in enumerate(documents):
            digest = content_hash(document)
            write_once(root / "validation-objects" / f"{digest}.json", document)
            # The reference hash addresses canonical JSON without a trailing newline.
            records.append(
                JvmProfileValidationEvidence(
                    evidence_id=f"evidence.{scope.profile_id}.{verifier.manifest['campaign_id']}.{index}",
                    kind=kind,
                    artifact_content_hash=digest,
                    reference=f"jvm-validation:sha256:{digest}",
                    **identity,
                )
            )
        summary.append(
            {
                "target": target.value,
                "profile_id": scope.profile_id,
                "attempts": 7,
                "successful_attempts": 3,
                "expected_failed_attempts": 4,
                "approved_operations": 8,
                "phase_containers_removed": len(verifier.container_ids),
                "records": len(documents),
            }
        )
    catalog = JvmProfileValidationEvidenceCatalog(canonical_jvm_validation_evidence(tuple(records)))
    decisions = evaluate_sprint09_jvm_profile_promotions(catalog)
    require(all(decision.is_eligible for decision in decisions), "CATALOG_INELIGIBLE")
    inputs = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        # Seal the primary campaign and proofs, excluding temporary execution,
        # publisher transports and supplementary development environments.
        included = relative_path.parts[0] in {
            *(target.value for target in TARGETS),
            "prerequisites",
            "contract-reports",
            "validation-objects",
            "authority.json",
            "result.json",
            "contract-tests.json",
            "platform-sources.tar",
        }
        if included and path.is_file() and "workspaces" not in relative_path.parts:
            relative = portable_path(relative_path.as_posix())
            inputs[relative] = file_identity(path)
    publication = {
        "schema_version": 1,
        "catalog": catalog.to_snapshot(),
        "catalog_hash": catalog.content_hash,
        "summary": summary,
        "decisions": [decision.to_snapshot() for decision in decisions],
        "artifacts": inputs,
        "recorded_at": recorded_at.isoformat(),
        "database_published": False,
    }
    write_once(root / "publication.json", publication)
    return {
        "package_hash": content_hash(publication),
        "catalog_hash": catalog.content_hash,
        "summary": summary,
    }


def load_publication(root, *, expected_package_hash):
    root = Path(root).absolute()
    publication = read_document(root / "publication.json")
    require(content_hash(publication) == expected_package_hash, "PACKAGE_HASH_MISMATCH")
    for path, identity in publication["artifacts"].items():
        same(file_identity(root / portable_path(path)), identity, "SEALED_ARTIFACT_CHANGED")
    records = []
    for snapshot in publication["catalog"]["records"]:
        record = JvmProfileValidationEvidence(
            **{
                **snapshot,
                "kind": Kind(snapshot["kind"]),
                "recorded_at": datetime.fromisoformat(snapshot["recorded_at"]),
            }
        )
        digest = record.artifact_content_hash
        require(
            record.reference == f"jvm-validation:sha256:{digest}", "PUBLICATION_REFERENCE_INVALID"
        )
        require(
            content_hash(read_document(root / "validation-objects" / f"{digest}.json")) == digest,
            "EVIDENCE_DOCUMENT_CHANGED",
        )
        records.append(record)
    catalog = JvmProfileValidationEvidenceCatalog(canonical_jvm_validation_evidence(tuple(records)))
    require(
        catalog.content_hash == publication["catalog_hash"]
        and len(catalog.records) == 51
        and all(
            decision.is_eligible for decision in evaluate_sprint09_jvm_profile_promotions(catalog)
        ),
        "PUBLICATION_CATALOG_INVALID",
    )
    return catalog


async def publish_catalog(sessions, *, root, expected_package_hash):
    catalog = load_publication(root, expected_package_hash=expected_package_hash)
    async with sessions() as session, session.begin():
        repository = SqlAlchemyJvmValidationEvidenceRepository(session)
        for record in catalog.records:
            status = await repository.append(record)
            require(status.value in {"APPENDED", "ALREADY_PRESENT"}, "EVIDENCE_CONFLICT")
        stored = JvmProfileValidationEvidenceCatalog(await repository.history())
        decisions = evaluate_sprint09_jvm_profile_promotions(stored)
        require(all(decision.is_eligible for decision in decisions), "STORED_CATALOG_INELIGIBLE")
    return {
        "database_published": True,
        "package_hash": expected_package_hash,
        "catalog_hash": stored.content_hash,
        "decisions": [decision.to_snapshot() for decision in decisions],
    }
