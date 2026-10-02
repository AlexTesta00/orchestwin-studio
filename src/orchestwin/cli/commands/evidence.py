from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import research_evidence as api
from orchestwin.cli.errors import SIGN_IN_STATUS, USAGE_STATUS, CliError
from orchestwin.cli.project import read_json

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "evidence"
NESTED_OPTIONS: Final = {"color": False} if sys.version_info >= (3, 14) else {}


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="evidence.option_all")
    parser.add_argument("--json", action="store_true", help="evidence.option_json")
    actions = parser.add_subparsers(dest="action", metavar="ACTION")
    for name in ("add", "revise"):
        child = actions.add_parser(name, help=f"evidence.help_{name}", **NESTED_OPTIONS)
        if name == "revise":
            child.add_argument("code", metavar="CODE")
        child.add_argument("file", metavar="FILE")
        child.add_argument("--title")
        child.add_argument("--source-kind", choices=api.SOURCE_KINDS, default="OWNER_INPUT")
        child.add_argument("--source-ref", default="")
        child.add_argument("--context", default="")
        child.add_argument("--method", default="")
        child.add_argument("--limitations", default="")
        child.add_argument("--collected-at")
        child.add_argument("--empirical", action="store_true")
    show = actions.add_parser("show", help="evidence.help_show", **NESTED_OPTIONS)
    show.add_argument("code", metavar="CODE")
    show.add_argument("--text", action="store_true", help="evidence.option_text")
    show.add_argument("--json", action="store_true", help="evidence.option_json")
    retire = actions.add_parser("retire", help="evidence.help_retire", **NESTED_OPTIONS)
    retire.add_argument("code", metavar="CODE")
    retire.add_argument("--reason", required=True)
    deleted = actions.add_parser("delete-text", help="evidence.help_delete-text", **NESTED_OPTIONS)
    deleted.add_argument("code", metavar="CODE")
    associated = actions.add_parser(
        "reassociate", help="evidence.help_reassociate", **NESTED_OPTIONS
    )
    associated.add_argument("code", metavar="CODE")
    associated.add_argument("file", metavar="FILE")
    associated.add_argument("--version", type=int)


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project()
    link = project.link()
    client = context.client()
    action = arguments.action
    if action == "reassociate":
        text = file_text(context.directory / arguments.file)
        found = api.selected(api.overview(client, link.project_id, every=True), arguments.code)
        version = arguments.version or found["version"]
        route = api.path(link.project_id, str(found["id"]))
        found = api.request(client, "GET", route, query={"version": str(version)})
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != found["content_hash"]:
            raise CliError("EVIDENCE_CONTEXT_CHANGED", status=USAGE_STATUS)
        context.console.say("evidence.privacy")
        if not context.assume_yes and not context.console.confirm(
            "evidence.confirm_add", default=False
        ):
            return 0
        result = api.request(
            client,
            "PUT",
            f"{route}/text",
            body={"version": version, "text": text, "acknowledged": True},
        )
        show_result(context, result.get("evidence", {}))
        return 0
    if action in ("add", "revise"):
        text = file_text(context.directory / arguments.file)
        context.console.say("evidence.privacy")
        if not context.assume_yes and not context.console.confirm(
            "evidence.confirm_add", default=False
        ):
            return 0
        route = api.path(link.project_id)
        if action == "revise":
            found = api.selected(api.overview(client, link.project_id, every=True), arguments.code)
            route = f"{api.path(link.project_id, str(found['id']))}/versions"
        body = {
            "title": arguments.title or Path(arguments.file).stem,
            "source_kind": arguments.source_kind,
            "source_ref": arguments.source_ref,
            "context": arguments.context,
            "method": arguments.method,
            "collected_at": arguments.collected_at,
            "limitations": arguments.limitations,
            "empirical": arguments.empirical,
            "text": text,
            "acknowledged": True,
        }
        result = api.request(client, "POST", route, body=body)
        show_result(context, result.get("evidence", {}))
        return 0
    offline = False
    try:
        document = api.overview(client, link.project_id, every=arguments.all or action is not None)
    except CliError as error:
        if action not in (None, "show") or getattr(arguments, "text", False):
            raise
        if (
            error.code not in {"STUDIO_UNREACHABLE", "NOT_SIGNED_IN", "SESSION_EXPIRED"}
            and error.status != SIGN_IN_STATUS
        ):
            raise
        document = read_json(project.knowledge / api.DOCUMENT)
        if not isinstance(document, Mapping):
            raise
        offline = True
        context.console.error("evidence.offline")
    if action is None:
        if arguments.json:
            context.console.write(json.dumps(document, ensure_ascii=False, indent=2))
        else:
            context.console.heading(context.text("evidence.heading"))
            values = api.entries(document)
            if not arguments.all:
                values = [item for item in values if item.get("status") == "ACTIVE"]
            if not values:
                context.console.say("evidence.none")
            for item in values:
                show_result(context, item)
        return 0
    found = api.selected(document, arguments.code)
    route = api.path(link.project_id, str(found["id"]))
    if action == "show":
        if offline:
            found = {
                **found,
                "citations": [
                    item
                    for item in document.get("citations", ())
                    if item.get("citation", {}).get("source_id") == found.get("id")
                ],
            }
        else:
            found = api.request(
                client, "GET", route, query={"text": "true"} if arguments.text else None
            )
        if arguments.json:
            context.console.write(json.dumps(found, ensure_ascii=False, indent=2))
        else:
            show_result(context, found)
            for key in ("source_ref", "context", "method", "limitations", "content_hash"):
                context.console.write(f"{context.text('evidence.' + key)}: {found.get(key) or '-'}")
            if arguments.text:
                context.console.write(str(found.get("text", "")))
            for citation in found.get("citations", ()):
                context.console.write(json.dumps(citation, ensure_ascii=False))
        return 0
    if action == "retire":
        context.console.say("evidence.retire_warning")
        if not context.assume_yes and not context.console.confirm(
            "evidence.confirm_retire", default=False
        ):
            return 0
        result = api.request(client, "POST", f"{route}/retire", body={"reason": arguments.reason})
        context.console.say("evidence.retired", code=found["code"])
        if result.get("review_required"):
            context.console.say("evidence.review_required")
        return 0
    context.console.say("evidence.delete_warning")
    if not context.assume_yes and not context.console.confirm(
        "evidence.confirm_delete", default=False
    ):
        return 0
    api.request(client, "DELETE", f"{route}/text", body={"acknowledged": True})
    context.console.say("evidence.deleted", code=found["code"])
    return 0


def file_text(path: Path) -> str:
    if path.suffix.lower() not in {".txt", ".md"}:
        raise CliError("EVIDENCE_INVALID_TEXT", status=USAGE_STATUS)
    try:
        with path.open("rb") as document:
            data = document.read(65537)
        if len(data) > 65536:
            raise CliError("EVIDENCE_LIMIT", status=USAGE_STATUS)
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise CliError("EVIDENCE_INVALID_TEXT", status=USAGE_STATUS) from None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) > api.MAX_CHARACTERS or len(normalized.encode("utf-8")) > api.MAX_BYTES:
        raise CliError("EVIDENCE_LIMIT", status=USAGE_STATUS)
    if "\x00" in text or not text.strip():
        raise CliError("EVIDENCE_INVALID_TEXT", status=USAGE_STATUS)
    return text


def show_result(context: CommandContext, item: Mapping) -> None:
    nature = context.text(
        "evidence.empirical" if item.get("empirical") else "evidence.non_empirical"
    )
    context.console.write(
        f"{item.get('code', '-')} v{item.get('version', '-')} — {item.get('title', '-')} — {item.get('status', '-')} — {nature}"
    )
