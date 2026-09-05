"""The bounded smoke runner must refuse unapproved work and preserve exact controls."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_qlora_smoke_collation import FakeCollator, verified
from test_qlora_smoke_tokenization import FakeTokenizer

ROOT = Path(__file__).resolve().parents[4]


def runner():
    path = ROOT / "environments/training/run_qlora_smoke.py"
    spec = importlib.util.spec_from_file_location("smoke_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("missing", ["gate", "owner", "fixtures", "license", "training"])
def test_no_training_without_all_explicit_approvals(tmp_path, missing):
    module = runner()
    values = {
        "owner_id": "owner",
        "approve_fixtures": True,
        "approve_model_license": True,
        "approve_local_training": True,
    }
    env = {"ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING": "1"}
    key = {
        "owner": "owner_id",
        "fixtures": "approve_fixtures",
        "license": "approve_model_license",
        "training": "approve_local_training",
    }
    if missing == "gate":
        env.clear()
    else:
        values[key[missing]] = "" if missing == "owner" else False
    with pytest.raises(ValueError):
        module.authorize(SimpleNamespace(**values), env)


def test_loader_options_pin_original_repository_and_disable_network(tmp_path):
    module = runner()
    data = verified(tmp_path)
    config = data.prepared.configuration
    kwargs = module.model_loading_kwargs(config, "bf16", object(), "/tmp/cache")
    assert kwargs["revision"] == config["base_model_revision"]
    assert kwargs["model_name"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert kwargs["use_exact_model_name"] is True
    assert kwargs["trust_remote_code"] is False
    assert kwargs["local_files_only"] is True
    assert kwargs["fast_inference"] is False


def test_sft_uses_pretokenized_data_without_aliases_or_mask_column_pruning(tmp_path):
    module = runner()
    data = verified(tmp_path)
    values = module.sft_kwargs(data.prepared.configuration, tmp_path / "outputs")
    assert values["max_steps"] == 8
    assert values["max_length"] == 1536
    assert "max_seq_length" not in values
    assert values["warmup_steps"] == 0
    assert "warmup_ratio" not in values
    assert "save_safetensors" not in values
    assert values["dataset_kwargs"] == {"skip_prepare_dataset": True}
    assert values["remove_unused_columns"] is False
    assert values["packing"] is False
    assert values["completion_only_loss"] is True
    assert values["save_steps"] == values["eval_steps"] == 4
    assert values["per_device_eval_batch_size"] == 1
    assert values["push_to_hub"] is False


def test_incompatible_loader_never_drops_required_arguments():
    module = runner()

    def limited(model_name):
        pytest.fail("must not be called")

    with pytest.raises(ValueError):
        module.strict_call(limited, {"model_name": "a", "revision": "b"})


def test_only_lora_parameters_may_be_trainable():
    module = runner()
    model = SimpleNamespace(
        named_parameters=lambda: [
            ("base.weight", SimpleNamespace(requires_grad=True, numel=lambda: 100)),
        ]
    )
    with pytest.raises(ValueError, match="non-LoRA"):
        module.verify_trainable_parameters(model)


def test_lazy_import_order_does_not_load_gpu_packages_for_help():
    import ast

    module = runner()
    tree = ast.parse((ROOT / "environments/training/run_qlora_smoke.py").read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_dependencies"
    )
    imports = [
        node.module.split(".")[0] if isinstance(node, ast.ImportFrom) else node.names[0].name
        for node in function.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imports.index("unsloth") < imports.index("transformers") < imports.index("trl")
    assert module.TRAINING_GATE == "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"


def fake_dependencies(data, *, revision=None, fail=False):
    training_config = data.prepared.configuration

    class Model:
        config = SimpleNamespace(
            _commit_hash=revision or training_config["base_model_revision"],
            quantization_config={
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_use_double_quant": True,
            },
        )
        is_loaded_in_4bit = True

        def named_parameters(self):
            return [
                ("lora_A.weight", SimpleNamespace(requires_grad=True, numel=lambda: 10)),
                ("base.weight", SimpleNamespace(requires_grad=False, numel=lambda: 100)),
            ]

        def save_pretrained(self, path, **kwargs):
            path = Path(path)
            path.mkdir(exist_ok=True)
            (path / "adapter_config.json").write_text("{}")
            (path / "adapter_model.safetensors").write_bytes(b"synthetic-test-not-weights")

    class Tokenizer(FakeTokenizer):
        def save_pretrained(self, path):
            (Path(path) / "tokenizer.json").write_text("{}")

    tokenizer = Tokenizer()
    model = Model()

    class Trainer:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.state = SimpleNamespace(global_step=0, log_history=[])

        def train(self):
            if fail:
                raise RuntimeError("simulated out of memory")
            self.state.global_step = 8
            self.state.log_history = [
                {"step": 4, "loss": 1.0, "eval_loss": 1.1},
                {"step": 8, "loss": 0.9, "eval_loss": 1.0},
            ]
            for step in (4, 8):
                path = Path(self.args.output_dir) / f"checkpoint-{step}"
                path.mkdir(parents=True)
                (path / "trainer_state.json").write_text("{}")
                (path / "adapter_config.json").write_text("{}")
                (path / "adapter_model.safetensors").write_bytes(b"synthetic-test-not-weights")

    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        is_bf16_supported=lambda: True,
        empty_cache=lambda: None,
        reset_peak_memory_stats=lambda: None,
        synchronize=lambda: None,
        manual_seed_all=lambda _: None,
        max_memory_reserved=lambda: 123 * 1024 * 1024,
    )
    return SimpleNamespace(
        torch=SimpleNamespace(
            cuda=cuda, bfloat16="bf16", float16="fp16", manual_seed=lambda _: None
        ),
        FastLanguageModel=SimpleNamespace(
            from_pretrained=lambda **_: (model, tokenizer), get_peft_model=lambda m, **_: m
        ),
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: tokenizer),
        BitsAndBytesConfig=lambda **kwargs: kwargs,
        Dataset=SimpleNamespace(from_list=lambda rows: rows),
        SFTConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        SFTTrainer=Trainer,
        TrainerCallback=object,
        DataCollator=lambda **k: FakeCollator(k["pad_token_id"]),
    )


def test_fake_journey_exports_without_claiming_reload_or_quality(tmp_path):
    import json

    module = runner()
    data = verified(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    deps = fake_dependencies(data)
    report = module.perform_training(data, deps, output, timeout_seconds=1800)
    assert report["global_step"] == 8
    assert report["adapter_exported"] is True
    assert report["adapter_reload_status"] == "NOT_RUN"
    assert report["checkpoint_restore_status"] == "NOT_RUN"
    assert report["quality_improvement_measured"] is False
    assert (output / "adapter/adapter_model.safetensors").is_file()
    assert [checkpoint["step"] for checkpoint in report["checkpoints"]] == [4, 8]
    assert all(
        any(item["path"] == "adapter_model.safetensors" for item in checkpoint["files"])
        for checkpoint in report["checkpoints"]
    )
    json.dumps(report)


def test_model_revision_mismatch_stops_before_training(tmp_path):
    module = runner()
    data = verified(tmp_path)
    with pytest.raises(ValueError, match="revision"):
        module.perform_training(
            data, fake_dependencies(data, revision="f" * 40), tmp_path / "run", timeout_seconds=1800
        )


def test_training_failure_does_not_export_adapter(tmp_path):
    module = runner()
    data = verified(tmp_path)
    with pytest.raises(RuntimeError, match="out of memory"):
        module.perform_training(
            data, fake_dependencies(data, fail=True), tmp_path / "run", timeout_seconds=1800
        )
    assert not (tmp_path / "run/adapter").exists()


def test_checkpoint_contract_rejects_unsafe_or_missing_adapter_weights(tmp_path):
    module = runner()
    checkpoint = tmp_path / "checkpoint-4"
    checkpoint.mkdir()
    (checkpoint / "trainer_state.json").write_text("{}")
    (checkpoint / "adapter_config.json").write_text("{}")
    (checkpoint / "adapter_model.bin").write_bytes(b"unsafe-test-placeholder")

    with pytest.raises(ValueError, match="safetensors"):
        module.verified_checkpoint_inventory(checkpoint, 4)

    (checkpoint / "adapter_model.bin").unlink()
    (checkpoint / "adapter_model.safetensors").write_bytes(b"safe-test-placeholder")
    assert module.verified_checkpoint_inventory(checkpoint, 4)


def test_cli_refuses_before_importing_gpu_libraries(monkeypatch, tmp_path):
    module = runner()
    monkeypatch.delenv(module.TRAINING_GATE, raising=False)
    monkeypatch.setattr(module, "load_dependencies", lambda: pytest.fail("must remain lazy"))
    args = []
    for name in ("prepared", "tokenized", "source-evidence", "collator-report", "output-root"):
        args.extend([f"--{name}", str(tmp_path / name)])
    assert module.main(args) == 22
    assert not (tmp_path / "output-root").exists()


def test_step_boundary_watchdog_enforces_time_and_step_limits():
    module = runner()
    callback = module.watchdog(object, -1)
    with pytest.raises(TimeoutError):
        callback.on_step_begin(None, SimpleNamespace(global_step=0), None)
    callback = module.watchdog(object, float("inf"))
    with pytest.raises(ValueError, match="beyond eight"):
        callback.on_step_begin(None, SimpleNamespace(global_step=8), None)


def test_error_progress_does_not_claim_a_completed_training(tmp_path):
    module = runner()
    data = verified(tmp_path)
    progress = {}
    with pytest.raises(RuntimeError):
        module.perform_training(
            data,
            fake_dependencies(data, fail=True),
            tmp_path / "run",
            timeout_seconds=1800,
            progress=progress,
        )
    assert progress["model_weights_loaded"] is True
    assert progress["training_call_attempted"] is True
    assert progress["optimizer_steps_completed"] == 0
    assert progress["training_executed"] is False
    assert progress["partial_metrics"] == []
