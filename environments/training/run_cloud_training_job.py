#!/usr/bin/env python3
"""Pod-local supervisor: finite compute lease, checkpoint grace, SMTP updates, Pod stop.

Secrets arrive through environment variables, never command-line arguments or reports.
This must supervise setup as well as training. It is not a provider-enforced spending
cap: host failure or control-plane outage still needs an independent external monitor.
Persistent storage is billed after the Pod stops and needs a separate retention budget.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from complete_training_data import save

API = "https://api.runpod.io/v2"


@dataclass(frozen=True)
class ComputeLease:
    pod_id: str
    pod_name: str
    created_unix: float
    hourly_ceiling_usd: float
    allowance_usd: float
    campaign_remaining_usd: float
    storage_reserve_usd: float = 20
    checkpoint_grace_seconds: int = 180

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.pod_id) or not self.pod_name:
            raise ValueError("invalid Pod identity")
        for value in (
            self.created_unix,
            self.hourly_ceiling_usd,
            self.allowance_usd,
            self.campaign_remaining_usd,
            self.storage_reserve_usd,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("positive finite lease values required")
        if not self.allowance_usd <= self.campaign_remaining_usd - self.storage_reserve_usd:
            raise ValueError("compute allowance consumes the storage reserve")
        if self.campaign_remaining_usd > 200:
            raise ValueError("campaign exceeds the authorized USD 200 ceiling")
        if (
            type(self.checkpoint_grace_seconds) is not int
            or not 30 <= self.checkpoint_grace_seconds <= 600
        ):
            raise ValueError("invalid checkpoint grace interval")
        if self.duration_seconds <= self.checkpoint_grace_seconds + 60:
            raise ValueError("lease is too short for checkpoint grace and API stop margin")

    @property
    def duration_seconds(self):
        return self.allowance_usd / self.hourly_ceiling_usd * 3600

    @property
    def deadline_unix(self):
        # Leave one minute inside the allowance for the first stop request/retry.
        return self.created_unix + self.duration_seconds - 60


def pod_request(pod_id, token, *, stop=False):
    path = f"{API}/pods/{pod_id}" + ("/action" if stop else "")
    request = urllib.request.Request(
        path,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Runpod's HTTP edge rejects urllib's default agent with error 1010.
            "User-Agent": "OrchesTwin-Training-Guard/1.0",
        },
        data=b'{"action":"stop"}' if stop else None,
        method="POST" if stop else "GET",
    )

    # Reject redirects rather than forwarding an authorization header to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def verify_pod(pod, lease):
    if pod["id"] != lease.pod_id or pod["name"] != lease.pod_name:
        raise ValueError("lease is not bound to this Pod")
    if pod["locked"] or "stop" not in pod["actions"]:
        raise ValueError("Pod cannot be stopped")
    cost = float(pod["cost"])
    if not math.isfinite(cost) or not 0 < cost <= lease.hourly_ceiling_usd:
        raise ValueError("live Pod rate exceeds the lease ceiling")
    # A lease may start conservatively before creation, never after the actual billed start.
    from datetime import datetime

    created = datetime.fromisoformat(pod["createdAt"].replace("Z", "+00:00")).timestamp()
    if lease.created_unix > created:
        raise ValueError("lease omits part of the Pod lifetime")


def notification_body(progress, lease, now):
    estimate = max(0, now - lease.created_unix) / 3600 * lease.hourly_ceiling_usd
    eta = progress.get("eta_seconds")
    return (
        f"OrchesTwin — {progress.get('stage', 'SETUP')}\n"
        f"Passi: {progress.get('global_step', 0)}/{progress.get('max_steps', 'non disponibili')}\n"
        f"Tempo rimanente stimato: {round(eta / 3600, 2) if eta is not None else 'non ancora misurabile'} ore\n"
        f"Costo del Pod stimato al massimo orario: USD {estimate:.2f}; "
        f"allocazione di questa esecuzione USD {lease.allowance_usd:.2f}.\n"
        "La stima non è il saldo Runpod e non include lo storage dopo l'arresto.\n"
        "Il risultato rimane un candidato sperimentale da validare."
    )


def send_email(subject, body, credentials):
    message = EmailMessage()
    message["From"] = credentials["ORCHESTWIN_SMTP_USER"]
    message["To"] = credentials["ORCHESTWIN_NOTIFY_TO"]
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, timeout=20, context=ssl.create_default_context()
    ) as client:
        client.login(credentials["ORCHESTWIN_SMTP_USER"], credentials["ORCHESTWIN_SMTP_PASSWORD"])
        client.send_message(message)


def stop_with_retry(lease, token, status_path, *, request=pod_request, sleep=time.sleep):
    # Continue attempting shutdown after transient failures. Never report a stopped Pod
    # solely because the training child exited or because a request was submitted.
    for attempt in range(1, 7):
        try:
            result = request(lease.pod_id, token, stop=False)
            if result["status"] not in ("EXITED", "ERROR"):
                result = request(lease.pod_id, token, stop=True)
            if result["status"] in ("EXITED", "ERROR"):
                with suppress(OSError):
                    save(
                        status_path,
                        dict(
                            stage="POD_STOP_CONFIRMED",
                            pod_id=lease.pod_id,
                            updated_unix=time.time(),
                            attempt=attempt,
                        ),
                    )
                return True
        except (OSError, ValueError, KeyError):
            pass
        with suppress(OSError):
            save(
                status_path,
                dict(
                    stage="POD_STOP_UNCONFIRMED",
                    pod_id=lease.pod_id,
                    updated_unix=time.time(),
                    attempt=attempt,
                ),
            )
        sleep(min(attempt * 5, 20))
    return False


def supervise(args):
    if os.name != "posix":
        raise ValueError("cloud supervisor requires a Linux Pod")
    lease = ComputeLease(**json.loads(args.lease.read_bytes()))
    if lease.pod_id != os.environ.get("RUNPOD_POD_ID"):
        raise ValueError("lease does not belong to the current Pod")
    token = os.environ["ORCHESTWIN_RUNPOD_API_KEY"]
    credentials = {
        key: os.environ[key]
        for key in ("ORCHESTWIN_SMTP_USER", "ORCHESTWIN_SMTP_PASSWORD", "ORCHESTWIN_NOTIFY_TO")
    }
    child_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in credentials and key != "ORCHESTWIN_RUNPOD_API_KEY"
    }
    args.state.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL prevents a second supervisor for the same lease. Keep the lock as evidence;
    # a restart requires a new lease/state path and an explicit prior-process check.
    with args.state.with_suffix(".lock").open("x") as lock:
        lock.write(str(os.getpid()))
    child = None
    reason = "SUPERVISOR_FAILURE"
    deadline = time.monotonic() + max(0, lease.deadline_unix - time.time())
    next_notification = time.monotonic() + 5 * 3600

    def publish(stage, **extra):
        save(
            args.state,
            dict(
                stage=stage,
                pod_id=lease.pod_id,
                run_directory=str(args.run_directory.resolve()),
                updated_unix=time.time(),
                deadline_unix=lease.deadline_unix,
                **extra,
            ),
        )

    try:
        verify_pod(pod_request(lease.pod_id, token), lease)
        # Authenticate the independent cloud mail path before starting any training/setup.
        send_email(
            "OrchesTwin: pilot cloud avviato",
            notification_body(dict(stage="SETUP"), lease, time.time()),
            credentials,
        )
        if time.monotonic() >= deadline - lease.checkpoint_grace_seconds:
            raise ValueError("insufficient remaining compute lease")
        publish("ARMED")
        child = subprocess.Popen(
            args.command, env=child_environment, start_new_session=True, stdin=subprocess.DEVNULL
        )
        while child.poll() is None:
            now = time.monotonic()
            if now >= deadline - lease.checkpoint_grace_seconds:
                reason = "COMPUTE_LEASE_EXPIRED"
                if args.run_directory.is_dir():
                    (args.run_directory / "STOP_REQUESTED").touch()
                publish("CHECKPOINT_GRACE")
            else:
                publish("ARMED")
            if now >= deadline:
                break
            if now >= next_notification:
                try:
                    progress = json.loads((args.run_directory / "progress.json").read_bytes())
                except (OSError, ValueError):
                    progress = dict(stage="SETUP_OR_PROGRESS_UNAVAILABLE")
                try:
                    send_email(
                        "OrchesTwin: aggiornamento training (5 ore)",
                        notification_body(progress, lease, time.time()),
                        credentials,
                    )
                    save(args.state.with_suffix(".email.json"), dict(sent_unix=time.time()))
                except (OSError, smtplib.SMTPException):
                    save(args.state.with_suffix(".email.json"), dict(status="SEND_FAILED"))
                next_notification = now + 5 * 3600
            time.sleep(min(30, max(0, deadline - time.monotonic())))
        if child.poll() is not None and reason != "COMPUTE_LEASE_EXPIRED":
            reason = "CHILD_COMPLETED" if child.returncode == 0 else "CHILD_FAILED"
    finally:
        try:
            if child is not None and child.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=10)
            with suppress(OSError):
                publish("POD_STOP_REQUESTED", reason=reason)
            # A stopped Pod cannot send email; do not claim confirmed shutdown here.
            progress = dict(stage=reason)
            with suppress(OSError, ValueError):
                progress.update(
                    json.loads((args.run_directory / "training-result.json").read_bytes())
                )
                progress["stage"] = progress.get("status", reason)
            with suppress(OSError, smtplib.SMTPException):
                send_email(
                    "OrchesTwin: esecuzione conclusa, arresto Pod richiesto",
                    notification_body(progress, lease, time.time()),
                    credentials,
                )
        finally:
            # Keep retrying while alive; external monitor must handle host/control-plane outages.
            while not stop_with_retry(lease, token, args.state):
                time.sleep(30)
    return 0 if reason == "CHILD_COMPLETED" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("lease", "state", "run-directory"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        raise ValueError("a child setup/training command is required")
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
