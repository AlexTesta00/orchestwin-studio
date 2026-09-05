"""Tests for the repository-owned JVM runner and fixture CI verifier."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_jvm_execution_contracts import ContractError, verify_repository

_REPOSITORY_ROOT = Path(__file__).parents[4]


def _copy_contract_tree(target: Path) -> Path:
    repository = target / "repository"
    for relative in (
        Path("infra/jvm-runners"),
        Path("src/test/fixtures/jvm_execution"),
    ):
        source = _REPOSITORY_ROOT / relative
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    return repository


def test_repository_jvm_contracts_are_pinned_bounded_and_capability_honest() -> None:
    report = verify_repository(_REPOSITORY_ROOT)

    assert report == {
        "base_images": 2,
        "runners": 2,
        "targets": 3,
        "fixtures": 3,
        "fixture_files": report["fixture_files"],
        "capability_status": "DESIGN_ONLY_LEVEL_C",
        "execution_attested": False,
    }
    assert isinstance(report["fixture_files"], int)
    assert report["fixture_files"] > 0


def test_verifier_rejects_an_unearned_runner_attestation(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    lock_path = repository / "infra/jvm-runners/images.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["runners"][0]["capability_status"] = "VALIDATED_LEVEL_D"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ContractError, match="must remain DESIGN_ONLY_LEVEL_C"):
        verify_repository(repository)


def test_verifier_rejects_new_source_input_until_fixture_contract_is_updated(
    tmp_path: Path,
) -> None:
    repository = _copy_contract_tree(tmp_path)
    undeclared = (
        repository
        / "src/test/fixtures/jvm_execution/jvm-kotlin-calculator/src/main/kotlin/Extra.kt"
    )
    undeclared.parent.mkdir(parents=True, exist_ok=True)
    undeclared.write_text("fun extra() = Unit\n", encoding="utf-8")

    with pytest.raises(ContractError, match="undeclared source-like contract inputs"):
        verify_repository(repository)


def test_verifier_rejects_mobile_material_in_the_jvm_fixture_package(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    forbidden = (
        repository / "src/test/fixtures/jvm_execution/jvm-kotlin-calculator/AndroidManifest.xml"
    )
    forbidden.write_text("<manifest />", encoding="utf-8")

    with pytest.raises(ContractError, match="mobile target material"):
        verify_repository(repository)
