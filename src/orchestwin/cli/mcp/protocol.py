from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

JSONRPC: Final = "2.0"
SERVER_NAME: Final = "orchestwin-twins"
LATEST_PROTOCOL: Final = "2025-06-18"
PROTOCOL_VERSIONS: Final = (LATEST_PROTOCOL, "2025-03-26", "2024-11-05")
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603
BYTE_ORDER_MARK: Final = "﻿"
RESOURCE_SCHEME: Final = "orchestwin://"
MARKDOWN: Final = "text/markdown"
TEXT_CONTENT: Final = "text"


class RpcError(Exception):
    def __init__(
        self,
        code: int,
        word: str,
        key: str,
        *,
        identifier: str | int | None = None,
        values: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(word)
        self.code = code
        self.word = word
        self.key = key
        self.identifier = identifier
        self.values: Mapping[str, object] = MappingProxyType(dict(values or {}))


@dataclass(frozen=True, slots=True)
class Request:
    identifier: str | int | None
    method: str
    params: object
    notification: bool


def decode(line: str) -> object:
    content = line.strip().removeprefix(BYTE_ORDER_MARK).strip()
    try:
        return json.loads(content, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        raise parse_error() from None


def request_from(document: object) -> Request | None:
    if not isinstance(document, dict):
        raise invalid_request()
    if "method" not in document and ("result" in document or "error" in document):
        return None
    identified = "id" in document
    identifier = document.get("id")
    echoed = identifier if valid_identifier(identifier) else None
    if document.get("jsonrpc") != JSONRPC:
        raise invalid_request(echoed)
    method = document.get("method")
    if not isinstance(method, str) or not method:
        raise invalid_request(echoed)
    if identified and echoed is None:
        raise invalid_request()
    params = document.get("params")
    if params is not None and not isinstance(params, dict | list):
        raise invalid_request(echoed)
    return Request(identifier=echoed, method=method, params=params, notification=not identified)


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def negotiate(requested: object) -> str:
    if isinstance(requested, str) and requested in PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL


def success(identifier: str | int | None, result: object) -> dict[str, object]:
    return {"jsonrpc": JSONRPC, "id": identifier, "result": result}


def failure(identifier: str | int | None, code: int, message: str, word: str) -> dict[str, object]:
    return {
        "jsonrpc": JSONRPC,
        "id": identifier,
        "error": {"code": code, "message": message, "data": word},
    }


def encode(message: object) -> str:
    return json.dumps(message, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def capabilities() -> dict[str, object]:
    return {
        "tools": {"listChanged": False},
        "resources": {"subscribe": False, "listChanged": False},
    }


def initialize_result(version: str, server_version: str, instructions: str) -> dict[str, object]:
    return {
        "protocolVersion": version,
        "capabilities": capabilities(),
        "serverInfo": {"name": SERVER_NAME, "version": server_version},
        "instructions": instructions,
    }


def tool_result(document: Mapping[str, object]) -> dict[str, object]:
    return {
        "content": [
            {"type": TEXT_CONTENT, "text": json.dumps(document, ensure_ascii=False)},
        ],
        "structuredContent": document,
        "isError": False,
    }


def tool_failure(code: str, message: str) -> dict[str, object]:
    return {
        "content": [{"type": TEXT_CONTENT, "text": message}],
        "structuredContent": {"code": code, "message": message},
        "isError": True,
    }


def resource_uri(path: str) -> str:
    return f"{RESOURCE_SCHEME}{urllib.parse.quote(path, safe='/')}"


def resource_path(uri: str) -> str | None:
    if not uri.startswith(RESOURCE_SCHEME):
        return None
    return urllib.parse.unquote(uri[len(RESOURCE_SCHEME) :])


def resource_entries(paths: Sequence[str]) -> list[dict[str, object]]:
    return [{"uri": resource_uri(path), "name": path, "mimeType": MARKDOWN} for path in paths]


def resource_contents(uri: str, content: str) -> dict[str, object]:
    return {"contents": [{"uri": uri, "mimeType": MARKDOWN, "text": content}]}


def parse_error() -> RpcError:
    return RpcError(PARSE_ERROR, "PARSE_ERROR", "mcp.rpc_parse_error")


def invalid_request(identifier: str | int | None = None) -> RpcError:
    return RpcError(
        INVALID_REQUEST, "INVALID_REQUEST", "mcp.rpc_invalid_request", identifier=identifier
    )


def not_initialized() -> RpcError:
    return RpcError(INVALID_REQUEST, "NOT_INITIALIZED", "mcp.rpc_not_initialized")


def method_not_found(method: str) -> RpcError:
    return RpcError(
        METHOD_NOT_FOUND,
        "METHOD_NOT_FOUND",
        "mcp.rpc_method_not_found",
        values={"method": method},
    )


def params_not_object(method: str) -> RpcError:
    return RpcError(
        INVALID_PARAMS, "INVALID_PARAMS", "mcp.rpc_params_object", values={"method": method}
    )


def param_missing(method: str, name: str) -> RpcError:
    return RpcError(
        INVALID_PARAMS,
        "INVALID_PARAMS",
        "mcp.rpc_param_missing",
        values={"method": method, "name": name},
    )


def unknown_tool(name: object, names: Sequence[str]) -> RpcError:
    return RpcError(
        INVALID_PARAMS,
        "UNKNOWN_TOOL",
        "mcp.rpc_unknown_tool",
        values={"name": str(name), "tools": ", ".join(names)},
    )


def invalid_arguments(key: str, **values: object) -> RpcError:
    return RpcError(INVALID_PARAMS, "INVALID_ARGUMENTS", key, values=values)


def resource_not_found(uri: str) -> RpcError:
    return RpcError(
        INVALID_PARAMS, "RESOURCE_NOT_FOUND", "mcp.rpc_resource_not_found", values={"uri": uri}
    )


def internal_error(kind: str) -> RpcError:
    return RpcError(
        INTERNAL_ERROR, "INTERNAL_ERROR", "mcp.rpc_internal_error", values={"kind": kind}
    )


def _refuse_constant(value: str) -> object:
    raise ValueError(f"{value} is not JSON")
