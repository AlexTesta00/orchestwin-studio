"""Real repository fixture capture and clean-commit boundary regression tests."""

from pathlib import Path

import pytest

from orchestwin.web_execution.validation_fixtures import load_repository_validation_fixtures

REPO = Path(__file__).resolve().parents[4]
IDS = (
    "static",
    "vue-js",
    "vue-ts",
    "express-js",
    "express-ts",
    "php",
    "vue-node-js",
    "vue-node-ts",
)


@pytest.mark.parametrize("fixture_id", IDS)
def test_repository_fixture_contract(fixture_id):
    fixtures = {item.fixture_id: item for item in load_repository_validation_fixtures(REPO)}
    assert set(fixtures) == set(IDS)
    fixture = fixtures[fixture_id]
    assert fixture.source_tree_hash() != fixture.source_tree_hash(defective=True)
    originals = {item.path: item.content for item in fixture.files}
    defective = {item.path: item.content for item in fixture.source_files(defective=True)}
    assert [key for key in originals if originals[key] != defective[key]] == [fixture.failure_path]
    assert fixture.repair_content == originals[fixture.failure_path]
    assert fixture.expected_failure_marker == "LEVEL_D_NEGATIVE_CONTROL"
    assert len(fixture.fixture_bundle_hash) == 64


def test_missing_matrix_cannot_create_partial_catalog(tmp_path):
    with pytest.raises((ValueError, OSError, RuntimeError)):
        load_repository_validation_fixtures(tmp_path)
