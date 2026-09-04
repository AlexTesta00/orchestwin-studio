"""Regression contracts for exact-revision, lazily imported Unsloth loading."""

from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = REPOSITORY_ROOT / "environments" / "training" / "run_model_spike.py"


def _runner() -> ModuleType:
    specification = importlib.util.spec_from_file_location("spike_loader_contract", RUNNER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _request(candidate_index: int = 0) -> dict[str, object]:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidates[candidate_index]
    return {
        "candidate_id": candidate.candidate_id,
        "model_repository": candidate.repository_id,
        "model_revision": candidate.revision,
        "tokenizer_repository": candidate.tokenizer_repository_id,
        "tokenizer_revision": candidate.tokenizer_revision,
        "generation": matrix.generation.to_snapshot(),
        "model_card_sha256": "b" * 64,
        "license_evidence_sha256": "c" * 64,
    }


def _noop(*_arguments: object) -> None:
    return None


def _fake_runtime(
    request: dict[str, object],
    *,
    model_revision: str | None = None,
    tokenizer_revision: str | None = None,
) -> tuple[object, object, object, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []
    model = SimpleNamespace(
        config=SimpleNamespace(_commit_hash=model_revision or request["model_revision"]),
    )
    tokenizer = SimpleNamespace(
        chat_template="fixture chat template",
        pad_token_id=0,
        eos_token_id=1,
        init_kwargs={"_commit_hash": tokenizer_revision or request["tokenizer_revision"]},
    )

    def from_pretrained(**values: object) -> tuple[object, object]:
        calls.append(values)
        return model, tokenizer

    def tokenizer_from_pretrained(**_values: object) -> object:
        raise AssertionError("The identical-revision bundled tokenizer should be reused")

    torch = SimpleNamespace(
        manual_seed=_noop,
        cuda=SimpleNamespace(
            is_available=lambda: True,
            manual_seed_all=_noop,
            empty_cache=_noop,
            reset_peak_memory_stats=_noop,
            synchronize=_noop,
            max_memory_reserved=lambda: 1024 * 1024,
        ),
    )
    fast_model = SimpleNamespace(from_pretrained=from_pretrained, for_inference=_noop)
    auto_tokenizer = SimpleNamespace(from_pretrained=tokenizer_from_pretrained)
    return torch, auto_tokenizer, fast_model, calls


def test_unsloth_is_imported_before_transformers_and_torch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()
    imported: list[str] = []
    torch = SimpleNamespace()
    fast_model = object()
    auto_tokenizer = object()
    replacements = {
        "unsloth": SimpleNamespace(FastLanguageModel=fast_model),
        "torch": torch,
        "transformers": SimpleNamespace(AutoTokenizer=auto_tokenizer),
    }
    real_import = builtins.__import__

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in replacements:
            imported.append(name)
            return replacements[name]
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", controlled_import)
        loaded = module._load_runtime_dependencies()

    assert imported == ["unsloth", "torch", "transformers"]
    assert loaded == (torch, auto_tokenizer, fast_model)


@pytest.mark.parametrize("candidate_index", (0, 1, 2))
@pytest.mark.parametrize("network_authorized", (False, True))
def test_each_frozen_candidate_loads_the_exact_repo_without_vllm_or_remapping(
    candidate_index: int,
    network_authorized: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()
    request = _request(candidate_index)
    torch, tokenizer, fast_model, calls = _fake_runtime(request)
    monkeypatch.setattr(
        module, "_load_runtime_dependencies", lambda: (torch, tokenizer, fast_model)
    )

    _, _, _, evidence = module._load_model(request, network_authorized=network_authorized)

    assert len(calls) == 1
    assert calls[0] == {
        "model_name": request["model_repository"],
        "revision": request["model_revision"],
        "max_seq_length": 4096,
        "dtype": None,
        "load_in_4bit": True,
        "trust_remote_code": False,
        "local_files_only": not network_authorized,
        "use_exact_model_name": True,
        "fast_inference": False,
    }
    assert evidence["observed_model_revision"] == request["model_revision"]
    assert evidence["observed_tokenizer_revision"] == request["tokenizer_revision"]
    assert evidence["loader_policy"] == module._loader_policy()


def test_loader_rejects_an_api_that_would_drop_the_exact_model_flag() -> None:
    module = _runner()

    def legacy_loader(model_name: str, revision: str) -> None:
        raise AssertionError("An unsupported loader must not be invoked")

    with pytest.raises(module.ModelSpikeIdentityError, match="required loading arguments"):
        module._supported_kwargs(
            legacy_loader,
            {"model_name": "Qwen/example", "revision": "a" * 40, "use_exact_model_name": True},
        )


def test_loader_preserves_all_arguments_for_a_kwargs_api() -> None:
    module = _runner()

    def supported_loader(**_values: object) -> None:
        return None

    values = {"revision": "a" * 40, "use_exact_model_name": True, "local_files_only": True}
    assert module._supported_kwargs(supported_loader, values) == values


def test_loader_rejects_positional_only_or_uninspectable_apis() -> None:
    module = _runner()

    def positional_loader(model_name: str, /, **_values: object) -> None:
        return None

    for loader in (positional_loader, object()):
        with pytest.raises(module.ModelSpikeIdentityError, match="required loading arguments"):
            module._supported_kwargs(loader, {"model_name": "Qwen/example"})


@pytest.mark.parametrize("mismatched_component", ("model", "tokenizer"))
def test_revision_mismatch_remains_a_hard_failure_with_requested_and_observed_values(
    mismatched_component: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()
    request = _request(1)
    different_revision = "f" * 40
    values = {f"{mismatched_component}_revision": different_revision}
    torch, tokenizer, fast_model, calls = _fake_runtime(request, **values)
    monkeypatch.setattr(
        module, "_load_runtime_dependencies", lambda: (torch, tokenizer, fast_model)
    )

    with pytest.raises(module.ModelSpikeIdentityError) as captured:
        module._load_model(request, network_authorized=False)

    assert f"loaded {mismatched_component} revision differs from the request" in str(captured.value)
    assert request[f"{mismatched_component}_revision"] in str(captured.value)
    assert different_revision in str(captured.value)
    assert len(calls) == 1, "Identity failures must not trigger an automatic retry"


def test_absent_tokenizer_commit_hash_remains_explicitly_unobserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()
    request = _request()
    torch, auto_tokenizer, fast_model, _ = _fake_runtime(request)
    original_loader = fast_model.from_pretrained

    def without_tokenizer_revision(**values: object) -> tuple[object, object]:
        model, tokenizer = original_loader(**values)
        tokenizer.init_kwargs = {}
        return model, tokenizer

    fast_model.from_pretrained = without_tokenizer_revision
    monkeypatch.setattr(
        module, "_load_runtime_dependencies", lambda: (torch, auto_tokenizer, fast_model)
    )
    _, _, _, evidence = module._load_model(request, network_authorized=False)
    assert evidence["observed_tokenizer_revision"] is None
    assert evidence["tokenizer_revision_observation"] == "REQUEST_PIN_ONLY"


def test_runtime_v2_and_loader_policy_are_bound_to_the_configuration_digest() -> None:
    module = _runner()
    request = _request()
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidates[0]

    identity = module._model_identity(request, candidate)

    assert identity.runtime_id == "unsloth-direct-inference-v2"
    expected = {
        "runtime": "unsloth-direct-inference-v2",
        "loader_policy": module._loader_policy(),
        "candidate_matrix_sha256": module.FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        "candidate_matrix_content_hash": module.FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        "chat_template_control": candidate.chat_template_control.to_snapshot(),
        "generation": request["generation"],
        "model_card_sha256": request["model_card_sha256"],
        "license_evidence_sha256": request["license_evidence_sha256"],
    }
    assert identity.configuration_sha256 == snapshot_content_hash(expected)
    changed = {
        **expected,
        "loader_policy": {**module._loader_policy(), "use_exact_model_name": False},
    }
    assert identity.configuration_sha256 != snapshot_content_hash(changed)
