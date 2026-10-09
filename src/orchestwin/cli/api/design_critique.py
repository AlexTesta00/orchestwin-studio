from __future__ import annotations

import json
import secrets
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api.design import design_path
from orchestwin.cli.client import payload
from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

IMAGE: Final = "IMAGE"
WEB_PAGE: Final = "WEB_PAGE"
KINDS: Final = (IMAGE, WEB_PAGE)
SHOTS_FIELD: Final = "shots"
RECORDED: Final = "DESIGN_CRITIQUE_RECORDED"
CRITIQUE_TIMEOUT: Final = 1800.0

type Shot = tuple[str, str, bytes, int | None]


def critiques_path(project_id: str) -> str:
    return f"{design_path(project_id)}/critiques"


def sources_path(project_id: str) -> str:
    return f"{critiques_path(project_id)}/sources"


def shot_path(project_id: str, source_id: str, code: str) -> str:
    return f"{sources_path(project_id)}/{source_id}/shots/{code}"


def source_form(
    *,
    kind: str,
    title: str | None,
    url: str | None,
    page: Mapping[str, object] | None,
    shots: Sequence[Shot],
) -> tuple[str, bytes]:
    fields = {"kind": kind}
    if title is not None:
        fields["title"] = title
    if url is not None:
        fields["url"] = url
    if page is not None:
        fields["page"] = json.dumps(page, ensure_ascii=False)
    widths = [width for _, _, _, width in shots]
    if any(width is not None for width in widths):
        fields["viewport_widths"] = json.dumps(widths)
    files = [(name, media_type, content) for name, media_type, content, _ in shots]
    return form(fields, files)


def form(fields: Mapping[str, str], files: Sequence[tuple[str, str, bytes]]) -> tuple[str, bytes]:
    contents = [value.encode("utf-8") for value in fields.values()]
    contents.extend(content for _, _, content in files)
    boundary = _boundary(contents)
    parts: list[bytes] = []
    for name, value in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{_quoted(name)}"\r\n\r\n'
        parts.append(head.encode("utf-8") + value.encode("utf-8") + b"\r\n")
    for file_name, media_type, content in files:
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{SHOTS_FIELD}"; '
            f'filename="{_quoted(file_name)}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        )
        parts.append(head.encode("utf-8") + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def upload_source(
    client: StudioClient,
    project_id: str,
    *,
    kind: str,
    title: str | None,
    url: str | None,
    page: Mapping[str, object] | None,
    shots: Sequence[Shot],
) -> Mapping[str, object]:
    body = source_form(kind=kind, title=title, url=url, page=page, shots=shots)
    reply = client.request("POST", sources_path(project_id), form=body)
    document = payload(reply)
    source = document.get("source") if isinstance(document, dict) else None
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return source


def run_critique(
    client: StudioClient, project_id: str, source_id: str, locale: str
) -> Mapping[str, object]:
    reply = client.request(
        "POST",
        critiques_path(project_id),
        body={"source_id": source_id, "locale": locale},
        timeout=CRITIQUE_TIMEOUT,
    )
    document = payload(reply)
    run = document.get("run") if isinstance(document, dict) else None
    if not isinstance(run, dict) or not isinstance(run.get("responses"), list):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return run


def critiques(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(critiques_path(project_id), optional=True))


def sources(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(sources_path(project_id), optional=True))


def _items(document: object) -> list[Mapping[str, object]]:
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _boundary(contents: Sequence[bytes]) -> str:
    while True:
        boundary = f"orchestwin-{secrets.token_hex(16)}"
        marker = boundary.encode("ascii")
        if not any(marker in content for content in contents):
            return boundary


def _quoted(value: str) -> str:
    return value.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
