"""Training isolation, loss masking, checkpoint integrity and cloud cost controls."""

import importlib
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    directory = Path(__file__).resolve().parents[4] / "environments/training"
    monkeypatch.syspath_prepend(str(directory))
    return tuple(
        importlib.import_module(name)
        for name in (
            "complete_training_data",
            "complete_training_runtime",
            "run_cloud_training_job",
        )
    )


class Tokenizer:
    eos_token_id = 9

    def apply_chat_template(self, messages, **options):
        assert options["return_dict"] is False
        return [1, 2] if len(messages) == 2 else [1, 2, 3, 4, 9, 5]


def dataset_source(tmp_path, data_module):
    source = tmp_path / "source"
    source.mkdir()
    rows = [
        dict(
            group_id=f"group-{group}",
            split="train",
            judgement=state,
            locale=locale,
            component="complete_interface",
            service_family=group % 2,
            structure_family=0,
            messages=[
                dict(role=role, content="example") for role in ("system", "user", "assistant")
            ],
        )
        for group in range(6)
        for state in ("PRESENT", "MISSING", "PARTIAL", "INSUFFICIENT")
        for locale in ("en", "it")
    ]
    (source / "train.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    data_module.save(
        source / "manifest.json",
        dict(
            curriculum_id=data_module.CURRICULUM,
            files={
                "train.jsonl": dict(
                    rows=len(rows), sha256=data_module.digest(source / "train.jsonl")
                )
            },
        ),
    )
    return source


@pytest.mark.parametrize(
    "curriculum",
    [
        "grounded-evaluator-complete-interface-v3",
        "grounded-evaluator-scoped-interface-v4",
        "grounded-evaluator-balanced-scope-v5",
    ],
)
def test_prepare_never_needs_validation_or_test_and_keeps_whole_groups(
    modules, tmp_path, curriculum
):
    data, _, _ = modules
    source = dataset_source(tmp_path, data)
    manifest = json.loads((source / "manifest.json").read_bytes())
    manifest["curriculum_id"] = curriculum
    data.save(source / "manifest.json", manifest)
    selected = data.selected_groups(source, 3)
    assert selected == data.selected_groups(source, 3)
    assert len(selected) == 3
    output = tmp_path / "cache"
    report = data.prepare_cache(
        source, output, data.digest(source / "manifest.json"), Tokenizer(), group_limit=3
    )
    assert report["rows"] == 24
    assert report["curriculum_id"] == curriculum
    assert set(report["selected_groups"]) == selected
    assert report["states"] == dict.fromkeys(("PRESENT", "MISSING", "PARTIAL", "INSUFFICIENT"), 6)
    dataset = data.TokenDataset(output)
    try:
        assert len(dataset) == 24
        assert dataset[23]["labels"] == [-100, -100, 3, 4, 9, 5]
        with pytest.raises(IndexError):
            dataset[24]
    finally:
        dataset.close()
    with (output / "train.sqlite").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="digest"):
        data.TokenDataset(output)


def test_source_hash_and_split_are_enforced(modules, tmp_path):
    data, _, _ = modules
    source = dataset_source(tmp_path, data)
    with pytest.raises(ValueError, match="manifest"):
        data.prepare_cache(source, tmp_path / "cache", "0" * 64, Tokenizer())
    with (source / "train.jsonl").open("a") as stream:
        stream.write(json.dumps(dict(split="test")) + "\n")
    with pytest.raises(ValueError, match="digest"):
        data.prepare_cache(
            source, tmp_path / "cache", data.digest(source / "manifest.json"), Tokenizer()
        )
    with pytest.raises(ValueError, match="non-training"):
        list(data.iter_train(source))


def test_padding_masks_only_prompt_and_padding_including_real_pad_token(modules):
    data, _, _ = modules
    result = data.padded_rows(
        [
            dict(input_ids=[1, 0, 9], labels=[-100, 0, 9]),
            dict(input_ids=[1, 2, 3, 9], labels=[-100, -100, 3, 9]),
        ],
        pad_token_id=0,
    )
    assert result["labels"] == [[-100, 0, 9, -100], [-100, -100, 3, 9]]
    assert result["attention_mask"] == [[1, 1, 1, 0], [1, 1, 1, 1]]


@pytest.mark.parametrize("failure", ["boundary", "eos", "context", "completion"])
def test_no_truncation_or_misaligned_completion(modules, failure):
    data, _, _ = modules

    class InvalidTokenizer(Tokenizer):
        def apply_chat_template(self, messages, **options):
            if len(messages) == 2:
                return [1] * 5000 if failure == "context" else [1, 2]
            return {
                "boundary": [1, 3, 9],
                "eos": [1, 2, 3],
                "context": [1] * 5000 + [9],
                "completion": [1, 2] + [3] * 2048 + [9],
            }[failure]

    with pytest.raises(ValueError):
        data.encode(InvalidTokenizer(), [dict(role=r) for r in ("system", "user", "assistant")])


def sealed_checkpoint(tmp_path, data, runtime):
    checkpoint = tmp_path / "checkpoint-2"
    checkpoint.mkdir()
    for name in (
        "adapter_model.safetensors",
        "adapter_config.json",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    ):
        (checkpoint / name).write_bytes(b"owned experiment fixture")
    data.save(checkpoint / "trainer_state.json", dict(global_step=2))
    data.save(
        checkpoint / "seal.json",
        dict(
            contract_sha256="contract",
            global_step=2,
            active_seconds=42,
            files=runtime.file_inventory(checkpoint),
        ),
    )
    return checkpoint


@pytest.mark.parametrize("change", ["contract", "optimizer", "weights", "extra", "step"])
def test_resume_rejects_changed_contract_or_incomplete_checkpoint(modules, tmp_path, change):
    data, runtime, _ = modules
    checkpoint = sealed_checkpoint(tmp_path, data, runtime)
    assert runtime.check_checkpoint(checkpoint, "contract")["global_step"] == 2
    if change == "optimizer":
        (checkpoint / "optimizer.pt").unlink()
    elif change == "weights":
        (checkpoint / "adapter_model.safetensors").write_bytes(b"different")
    elif change == "extra":
        (checkpoint / "untracked-file").write_text("unexpected")
    elif change == "step":
        data.save(checkpoint / "trainer_state.json", dict(global_step=1))
    with pytest.raises(ValueError):
        runtime.check_checkpoint(checkpoint, "another" if change == "contract" else "contract")


def lease_fixture(cloud):
    return cloud.ComputeLease(
        pod_id="owned-pilot",
        pod_name="orchestwin-pilot",
        created_unix=1000,
        hourly_ceiling_usd=1.7,
        allowance_usd=10,
        campaign_remaining_usd=200,
    )


def test_lease_counts_setup_time_and_protects_campaign_reserve(modules):
    _, _, cloud = modules
    lease = lease_fixture(cloud)
    assert lease.deadline_unix == pytest.approx(1000 + 10 / 1.7 * 3600 - 60)
    for changes in (
        dict(allowance_usd=181),
        dict(hourly_ceiling_usd=float("nan")),
        dict(campaign_remaining_usd=201),
        dict(pod_id="../other"),
    ):
        with pytest.raises(ValueError):
            replace(lease, **changes)
    pod = dict(
        id=lease.pod_id,
        name=lease.pod_name,
        locked=False,
        actions=["stop"],
        cost=1.59,
        createdAt="1970-01-01T00:16:40Z",
    )
    cloud.verify_pod(pod, lease)
    with pytest.raises(ValueError, match="rate"):
        cloud.verify_pod(dict(pod, cost=1.8), lease)
    with pytest.raises(ValueError, match="lifetime"):
        cloud.verify_pod(pod, replace(lease, created_unix=1001))


def test_resumed_allocation_requires_exact_start_and_covers_setup(modules):
    _, _, cloud = modules
    lease = replace(lease_fixture(cloud), created_unix=1990, pod_started_unix=2000)
    pod = dict(
        id=lease.pod_id,
        name=lease.pod_name,
        locked=False,
        actions=["stop"],
        cost=1.59,
        createdAt="1970-01-01T00:16:40Z",
        startedAt="1970-01-01T00:33:20Z",
    )
    cloud.verify_pod(pod, lease)
    with pytest.raises(ValueError, match="allocation"):
        cloud.verify_pod(dict(pod, startedAt="1970-01-01T00:33:21Z"), lease)
    for change in (
        dict(pod_started_unix=float("nan")),
        dict(created_unix=2001),
        dict(pod_started_unix=True),
    ):
        with pytest.raises(ValueError, match="start"):
            replace(lease, **change)


def test_stop_retries_and_only_reports_confirmed_state(modules, tmp_path):
    _, _, cloud = modules
    calls = []

    def request(pod_id, token, *, stop):
        calls.append((pod_id, stop))
        if len(calls) == 1:
            raise OSError("temporary failure")
        return dict(status="EXITED" if stop else "RUNNING")

    path = tmp_path / "status.json"
    assert cloud.stop_with_retry(
        lease_fixture(cloud), "not-a-secret", path, request=request, sleep=lambda _: None
    )
    assert calls == [("owned-pilot", False), ("owned-pilot", False), ("owned-pilot", True)]
    assert json.loads(path.read_bytes())["stage"] == "POD_STOP_CONFIRMED"
    assert not cloud.stop_with_retry(
        lease_fixture(cloud),
        "not-a-secret",
        path,
        request=lambda *a, **kw: dict(status="RUNNING"),
        sleep=lambda _: None,
    )
    assert json.loads(path.read_bytes())["stage"] == "POD_STOP_UNCONFIRMED"


def test_training_policy_is_bounded_and_rejects_invalid_optimizer_values(modules):
    _, runtime, _ = modules
    policy = runtime.TrainingPolicy()
    assert policy.max_steps == 40
    for changes in (
        dict(max_steps=0),
        dict(batch_size=True),
        dict(learning_rate=float("nan")),
        dict(save_steps=41),
        dict(max_active_seconds=-1),
    ):
        with pytest.raises(ValueError):
            replace(policy, **changes)


def test_transfer_contains_only_pinned_operators_and_training_cache(modules, tmp_path):
    data, _, _ = modules
    bundle_module = importlib.import_module("prepare_cloud_training_bundle")
    bootstrap = importlib.import_module("bootstrap_complete_training")
    source = dataset_source(tmp_path, data)
    cache = tmp_path / "cache"
    data.prepare_cache(source, cache, data.digest(source / "manifest.json"), Tokenizer())
    # Even adjacent secrets and final cases must not enter the explicit transfer allowlist.
    (cache / "password.env").write_text("should not transfer")
    (cache / "test.jsonl").write_text("reserved final cases")
    receipt = bundle_module.prepare(cache, tmp_path / "bundle")
    extracted = tmp_path / "extracted"
    with tarfile.open(tmp_path / "bundle/pilot.tar.gz") as archive:
        names = archive.getnames()
        assert not any("test.jsonl" in name or "password" in name for name in names)
        archive.extractall(extracted, filter="data")
    manifest = bootstrap.verify_bundle(extracted, receipt["manifest_sha256"])
    assert manifest["training_rows"] == 48
    assert not manifest["final_cases_included"]
    (extracted / "cache/train.sqlite").write_bytes(b"corrupt transfer")
    with pytest.raises(ValueError, match="changed"):
        bootstrap.verify_bundle(extracted, receipt["manifest_sha256"])


def test_transfer_manifest_rejects_parent_traversal(modules, tmp_path):
    data, _, _ = modules
    bootstrap = importlib.import_module("bootstrap_complete_training")
    data.save(tmp_path / "bundle.json", dict(files={"../outside": dict(bytes=1, sha256="x")}))
    with pytest.raises(ValueError, match="escapes"):
        bootstrap.verify_bundle(tmp_path, data.digest(tmp_path / "bundle.json"))


def test_pod_stop_still_succeeds_when_status_disk_is_unwritable(modules, tmp_path, monkeypatch):
    _, _, cloud = modules

    def failed_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cloud, "save", failed_save)
    assert cloud.stop_with_retry(
        lease_fixture(cloud),
        "not-a-secret",
        tmp_path / "status.json",
        request=lambda *a, **kw: dict(status="EXITED"),
        sleep=lambda _: None,
    )


@pytest.mark.parametrize("stop", [False, True])
def test_runpod_http_requests_identify_guard_and_never_redirect_credentials(
    modules, monkeypatch, stop
):
    _, _, cloud = modules
    requests = []

    class Opener:
        def open(self, request, *, timeout):
            requests.append(request)
            assert timeout == 20
            # Regression for the real HTTP 403/1010 returned for Python-urllib's default agent.
            assert request.get_header("User-agent") == "OrchesTwin-Training-Guard/1.0"
            assert request.get_header("Accept") == "application/json"
            assert request.get_header("Authorization") == "Bearer fixture-token"
            return io.StringIO('{"status":"EXITED"}')

    def opener_factory(handler):
        assert (
            handler().redirect_request(
                None, None, 302, "redirect", {}, "https://other.example.test/"
            )
            is None
        )
        return Opener()

    monkeypatch.setattr(cloud.urllib.request, "build_opener", opener_factory)
    assert cloud.pod_request("owned-pilot", "fixture-token", stop=stop)["status"] == "EXITED"
    request = requests[0]
    assert request.full_url == "https://api.runpod.io/v2/pods/owned-pilot" + (
        "/action" if stop else ""
    )
    assert request.get_method() == ("POST" if stop else "GET")
    assert request.data == (b'{"action":"stop"}' if stop else None)


@pytest.mark.parametrize("failure", [None, "mail_auth", "child_cleanup", "completed"])
def test_supervisor_enforces_deadline_and_stops_even_after_failures(
    modules, tmp_path, monkeypatch, failure
):
    data, _, cloud = modules
    lease = lease_fixture(cloud)
    from dataclasses import asdict

    data.save(tmp_path / "lease.json", asdict(lease))
    run = tmp_path / "run"
    run.mkdir()
    args = SimpleNamespace(
        lease=tmp_path / "lease.json",
        state=tmp_path / "guard.json",
        run_directory=run,
        command=["authorized-pilot-command"],
    )
    elapsed = [0]
    emails, stopped, signals, states, child_env = [], [], [], [], []
    environment = dict(
        RUNPOD_POD_ID=lease.pod_id,
        ORCHESTWIN_RUNPOD_API_KEY="key-fixture",
        ORCHESTWIN_SMTP_USER="sender@example.test",
        ORCHESTWIN_SMTP_PASSWORD="fixture",
        ORCHESTWIN_NOTIFY_TO="owner@example.test",
        KEEP="public-runtime-value",
    )
    monkeypatch.setattr(
        cloud,
        "os",
        SimpleNamespace(
            name="posix",
            environ=environment,
            getpid=lambda: 42,
            killpg=lambda pid, sig: signals.append((pid, sig)),
        ),
    )
    monkeypatch.setattr(
        cloud,
        "time",
        SimpleNamespace(
            monotonic=lambda: elapsed[0],
            time=lambda: lease.created_unix + elapsed[0],
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
        ),
    )
    monkeypatch.setattr(cloud, "save", lambda path, value: states.append(value))
    monkeypatch.setattr(
        cloud,
        "pod_request",
        lambda *a, **kw: dict(
            id=lease.pod_id,
            name=lease.pod_name,
            locked=False,
            actions=["stop"],
            cost=1.59,
            createdAt="1970-01-01T00:16:40Z",
        ),
    )
    monkeypatch.setattr(cloud, "stop_with_retry", lambda *a: stopped.append(elapsed[0]) or True)

    def email(subject, body, credentials):
        if failure == "mail_auth":
            raise cloud.smtplib.SMTPAuthenticationError(535, b"fixture rejected")
        emails.append((elapsed[0], subject))

    monkeypatch.setattr(cloud, "send_email", email)

    class Child:
        pid, returncode = 73, None

        def poll(self):
            if failure == "completed" and elapsed[0] >= 5 * 3600 + 60:
                self.returncode = 0
                return 0
            return None

        def wait(self, timeout):
            if failure == "child_cleanup":
                raise RuntimeError("fixture cleanup failure")
            return -15

    def launch(command, **options):
        assert command == args.command
        child_env.append(options["env"])
        return Child()

    monkeypatch.setattr(cloud.subprocess, "Popen", launch)
    if failure in ("mail_auth", "child_cleanup"):
        with pytest.raises((cloud.smtplib.SMTPAuthenticationError, RuntimeError)):
            cloud.supervise(args)
    elif failure == "completed":
        assert cloud.supervise(args) == 0
        assert states[-1]["reason"] == "CHILD_COMPLETED"
        assert not (run / "STOP_REQUESTED").exists()
        assert not signals
    else:
        assert cloud.supervise(args) == 1
        assert (run / "STOP_REQUESTED").exists()
        assert states[-1]["reason"] == "COMPUTE_LEASE_EXPIRED"
        assert signals[0][0] == 73
        assert any(stage.get("stage") == "CHECKPOINT_GRACE" for stage in states)
        assert child_env == [dict(RUNPOD_POD_ID=lease.pod_id, KEEP="public-runtime-value")]
        assert lease.created_unix + stopped[0] == pytest.approx(lease.deadline_unix)
    if failure in (None, "completed"):
        assert len(emails) == 2
        assert emails[0][0] == 0 and "avviato" in emails[0][1]
        assert emails[1][0] == stopped[0] > 5 * 3600
        assert "conclusa" in emails[1][1]
    assert len(stopped) == 1
