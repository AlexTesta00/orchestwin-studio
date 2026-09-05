"""Final thesis QLoRA runner must preserve the proven smoke-training controls."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


def runner():
    path = ROOT / "environments/training/run_thesis_qlora.py"
    name = "final_thesis_qlora_runner_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "missing",
    ["gate", "owner", "dataset", "license", "training"],
)
def test_authorization_requires_every_explicit_final_training_declaration(missing):
    module = runner()
    args = SimpleNamespace(
        owner_id="owner",
        approve_synthetic_dataset=True,
        approve_model_license=True,
        approve_final_training=True,
    )
    environment = {"ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING": "1"}

    if missing == "gate":
        environment.clear()
    elif missing == "owner":
        args.owner_id = ""
    elif missing == "dataset":
        args.approve_synthetic_dataset = False
    elif missing == "license":
        args.approve_model_license = False
    else:
        args.approve_final_training = False

    with pytest.raises(ValueError):
        module.authorize(args, environment)


def frozen_policy():
    return {
        "policy_id": "qwen3-4b-thesis-qlora-v1",
        "base_model_repository": "Qwen/Qwen3-4B-Instruct-2507",
        "base_model_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "tokenizer_repository": "Qwen/Qwen3-4B-Instruct-2507",
        "tokenizer_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "quantization": {
            "load_in_4bit": True,
            "quantization_type": "nf4",
            "double_quantization": True,
            "compute_dtype": "bfloat16",
        },
        "lora": {
            "rank": 16,
            "alpha": 32,
            "dropout": 0.0,
            "target_modules": [
                "down_proj",
                "gate_proj",
                "k_proj",
                "o_proj",
                "q_proj",
                "up_proj",
                "v_proj",
            ],
            "bias": "none",
            "use_rslora": False,
        },
        "optimization": {
            "max_sequence_length": 1536,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "learning_rate": 0.0001,
            "weight_decay": 0.01,
            "warmup_ratio": 0.03,
            "num_train_epochs": 1.0,
            "optimizer": "adamw_8bit",
            "scheduler": "linear",
            "precision": "bf16",
            "gradient_checkpointing": True,
            "gradient_clip_norm": 1.0,
            "logging_steps": 10,
        },
        "checkpoints": {
            "save_steps": 1000,
            "evaluation_steps": 1000,
            "save_total_limit": 3,
            "load_best_model_at_end": True,
            "metric_for_best_model": "eval_loss",
            "greater_is_better": False,
        },
        "seed": 20260905,
        "authorization_required_before_training": True,
    }


def test_loader_is_exact_revision_local_only_and_never_uses_remote_code(tmp_path):
    module = runner()
    values = module.model_loading_kwargs(
        frozen_policy(),
        "bf16",
        object(),
        tmp_path / "cache",
    )
    assert values["model_name"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert values["revision"] == "abcc171021d4f320b2e7f47c6f0deca67ded870c"
    assert values["max_seq_length"] == 1536
    assert values["load_in_4bit"] is True
    assert values["trust_remote_code"] is False
    assert values["use_exact_model_name"] is True
    assert values["fast_inference"] is False
    assert values["local_files_only"] is True


def test_authenticated_hf_json_accepts_hash_bound_snapshot_symlink(tmp_path):
    module = runner()
    blobs = tmp_path / "blobs"
    snapshot = tmp_path / "snapshots" / "revision"
    blobs.mkdir()
    snapshot.mkdir(parents=True)
    raw = b'{"chat_template":"verified"}'
    target = blobs / "content-addressed-tokenizer-config"
    target.write_bytes(raw)
    link = snapshot / "tokenizer_config.json"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("filesystem does not permit symlink creation in this test environment")

    assert link.is_symlink()
    assert module.read_authenticated_json_object(
        link,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        label="cached tokenizer_config.json",
    ) == {"chat_template": "verified"}


def test_authenticated_hf_json_rejects_content_that_does_not_match_frozen_hash(tmp_path):
    module = runner()
    path = tmp_path / "tokenizer_config.json"
    path.write_text('{"chat_template":"tampered"}', encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 changed"):
        module.read_authenticated_json_object(
            path,
            expected_sha256="0" * 64,
            label="cached tokenizer_config.json",
        )


def test_final_sft_policy_uses_completion_only_pretokenized_rows(tmp_path):
    module = runner()
    values = module.sft_kwargs(frozen_policy(), tmp_path / "checkpoints")
    assert values["max_length"] == 1536
    assert values["num_train_epochs"] == 1.0
    assert values["per_device_train_batch_size"] == 1
    assert values["per_device_eval_batch_size"] == 1
    assert values["gradient_accumulation_steps"] == 4
    assert values["warmup_ratio"] == 0.03
    assert values["eval_steps"] == 1000
    assert values["save_steps"] == 1000
    assert values["save_total_limit"] == 3
    assert values["load_best_model_at_end"] is True
    assert values["metric_for_best_model"] == "eval_loss"
    assert values["dataset_kwargs"] == {"skip_prepare_dataset": True}
    assert values["completion_only_loss"] is True
    assert values["assistant_only_loss"] is False
    assert values["remove_unused_columns"] is False
    assert values["packing"] is False
    assert values["push_to_hub"] is False
    assert "dataset_text_field" not in values
    assert "max_seq_length" not in values


class FakeTokenizer:
    eos_token = "<eos>"
    eos_token_id = 99
    pad_token_id = 0

    def apply_chat_template(
        self,
        messages,
        *,
        tokenize,
        add_generation_prompt,
    ):
        prompt = "SYS\nUSER\nASSISTANT:"
        text = prompt if len(messages) == 2 else prompt + messages[2]["content"] + "<eos>\n"
        if not tokenize:
            return text
        return {"input_ids": self(text)["input_ids"]}

    def __call__(
        self,
        text,
        *,
        add_special_tokens=False,
        truncation=False,
        padding=False,
    ):
        prompt = "SYS\nUSER\nASSISTANT:"
        if text == prompt:
            return {"input_ids": [1, 2, 3]}
        if text.startswith(prompt) and text.endswith("<eos>\n"):
            return {"input_ids": [1, 2, 3, 10, 11, 99, 12]}
        raise AssertionError(text)

    def decode(self, values, *, skip_special_tokens=False):
        return "\n" if values == [12] else ""


def test_completion_features_mask_only_prompt_and_accept_qwen_style_whitespace_after_eos():
    module = runner()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
        {"role": "assistant", "content": '{"ok":true}'},
    ]
    row = module._completion_features(
        messages,
        tokenizer=FakeTokenizer(),
        max_length=1536,
        label="fixture",
    )
    assert row["input_ids"] == [1, 2, 3, 10, 11, 99, 12]
    assert row["attention_mask"] == [1] * 7
    assert row["completion_mask"] == [0, 0, 0, 1, 1, 1, 1]


def test_completion_features_refuse_real_text_after_eos():
    module = runner()

    class BadTokenizer(FakeTokenizer):
        def apply_chat_template(
            self,
            messages,
            *,
            tokenize,
            add_generation_prompt,
        ):
            prompt = "SYS\nUSER\nASSISTANT:"
            if len(messages) == 2:
                text = prompt
                token_ids = [1, 2, 3]
            else:
                text = prompt + messages[2]["content"] + "<eos>BAD"
                token_ids = [1, 2, 3, 10, 11, 99, 55]
            if not tokenize:
                return text
            return {"input_ids": token_ids}

    with pytest.raises(ValueError, match="non-whitespace"):
        module._completion_features(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
                {"role": "assistant", "content": '{"ok":true}'},
            ],
            tokenizer=BadTokenizer(),
            max_length=1536,
            label="fixture",
        )


def test_only_lora_parameters_may_be_trainable():
    module = runner()
    model = SimpleNamespace(
        named_parameters=lambda: [
            ("base.weight", SimpleNamespace(requires_grad=True, numel=lambda: 100)),
        ]
    )
    with pytest.raises(ValueError, match="non-LoRA"):
        module.verify_trainable_parameters(model)


def test_resume_checkpoint_must_belong_to_same_run_and_be_resumable(tmp_path):
    module = runner()
    output = tmp_path / "run"
    checkpoint = output / "checkpoints/checkpoint-1000"
    checkpoint.mkdir(parents=True)
    for name in (
        "trainer_state.json",
        "adapter_config.json",
        "adapter_model.safetensors",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    ):
        (checkpoint / name).write_bytes(b"test")

    assert (
        module.verified_resume_checkpoint(
            checkpoint,
            output_root=output,
        )
        == checkpoint.absolute()
    )

    outside = tmp_path / "outside/checkpoint-1000"
    outside.mkdir(parents=True)
    with pytest.raises(ValueError, match="belong"):
        module.verified_resume_checkpoint(outside, output_root=output)


def test_collator_audit_rejects_unmasked_prompt():
    module = runner()
    row = {
        "input_ids": [1, 2, 3, 10, 99],
        "attention_mask": [1, 1, 1, 1, 1],
        "completion_mask": [0, 0, 0, 1, 1],
    }

    class BadCollator:
        def __call__(self, rows):
            return {"labels": [[1, 2, 3, 10, 99]]}

    with pytest.raises(ValueError, match="prompt tokens"):
        module.verify_collator_labels(BadCollator(), row)


def test_lazy_import_order_keeps_gpu_runtime_out_of_module_import():
    module = runner()
    path = ROOT / "environments/training/run_thesis_qlora.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_dependencies"
    )
    imports = []
    for node in function.body:
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imports.append(node.names[0].name.split(".")[0])
    assert imports.index("unsloth") < imports.index("transformers") < imports.index("trl")
    assert module.TRAINING_GATE == "ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING"


def test_generic_legacy_runner_is_not_the_final_completion_only_path():
    legacy = (ROOT / "environments/training/run_qlora.py").read_text(encoding="utf-8")
    final = (ROOT / "environments/training/run_thesis_qlora.py").read_text(encoding="utf-8")
    assert '"dataset_text_field": "text"' in legacy
    assert "completion_only_loss" not in legacy
    assert '"completion_only_loss": True' in final
    assert '"skip_prepare_dataset": True' in final


def test_main_refuses_before_loading_gpu_dependencies(monkeypatch, tmp_path):
    module = runner()
    monkeypatch.delenv(module.TRAINING_GATE, raising=False)
    monkeypatch.setattr(
        module,
        "load_dependencies",
        lambda: pytest.fail("GPU dependencies must remain lazy"),
    )
    code = module.main(
        [
            "--dataset-root",
            str(tmp_path / "dataset"),
            "--preflight-root",
            str(tmp_path / "preflight"),
            "--output-root",
            str(tmp_path / "output"),
            "--owner-id",
            "owner",
            "--approve-synthetic-dataset",
            "--approve-model-license",
            "--approve-final-training",
        ]
    )
    assert code == 22
    assert not (tmp_path / "output").exists()
