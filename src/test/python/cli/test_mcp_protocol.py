from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orchestwin.cli.mcp import protocol
from orchestwin.cli.mcp import tools as tools_module
from orchestwin.cli.mcp.protocol import Request, RpcError
from orchestwin.cli.mcp.server import Server, quiet_context
from orchestwin.cli.mcp.tools import TOOLS, Tools
from orchestwin.cli.messages import MESSAGES, known

from .support.terminal import Terminal, command_context, link_folder, terminal
from .support.transports import NoNetwork

TOOL_NAMES = (
    "project_state, list_twins, get_twin, get_requirements, get_design, get_feedback, "
    "ask_twin, review_changes, get_test_results, run_tests, get_tasks, get_evidence, get_why"
)
RPC_KEYS = (
    "mcp.rpc_parse_error",
    "mcp.rpc_invalid_request",
    "mcp.rpc_not_initialized",
    "mcp.rpc_method_not_found",
    "mcp.rpc_params_object",
    "mcp.rpc_param_missing",
    "mcp.rpc_unknown_tool",
    "mcp.rpc_resource_not_found",
    "mcp.rpc_internal_error",
    "mcp.argument_object",
    "mcp.argument_unknown",
    "mcp.argument_missing",
    "mcp.describe_review_changes_plain",
    "mcp.errors.TWIN_ANSWER_FAILED",
)


def request(identifier: object, method: str, params: object = None) -> str:
    message: dict[str, object] = {"jsonrpc": "2.0", "id": identifier, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def notification(method: str, params: object = None) -> str:
    message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def initialize(identifier: object = 1, version: object = "2025-06-18") -> str:
    return request(
        identifier,
        "initialize",
        {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "test client", "version": "1.0"},
        },
    )


def call(identifier: object, name: str, arguments: object = None) -> str:
    params: dict[str, object] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return request(identifier, "tools/call", params)


def error(identifier: object, code: int, message: str, data: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": code, "message": message, "data": data},
    }


def build(
    tmp_path: Path, *, spend: bool = False, language: str = "en", debug: bool = False
) -> tuple[Server, Terminal]:
    bundle = terminal(tmp_path, transport=NoNetwork())
    link_folder(tmp_path / "project", language="it")
    context = quiet_context(command_context(bundle.environment, language=language, debug=debug))
    return Server(context, Tools(context, spend=spend), spend=spend), bundle


def answer(server: Server, line: str) -> object:
    found = server.handle(line)
    return None if found is None else json.loads(found)


def ready(tmp_path: Path, **options: object) -> tuple[Server, Terminal]:
    server, bundle = build(tmp_path, **options)
    started = answer(server, initialize())
    assert isinstance(started, dict)
    assert "result" in started
    return server, bundle


def test_a_line_is_decoded_as_one_json_value() -> None:
    assert protocol.decode(' {"a": 1} \r\n') == {"a": 1}
    assert protocol.decode('﻿{"a": [1, 2]}\n') == {"a": [1, 2]}


@pytest.mark.parametrize("content", ["{", "not json", '{"a": NaN}', "[1, Infinity]", "'x'"])
def test_a_line_that_is_not_json_is_a_parse_error(content: str) -> None:
    with pytest.raises(RpcError) as refused:
        protocol.decode(content)

    assert (refused.value.code, refused.value.word) == (-32700, "PARSE_ERROR")


def test_requests_notifications_and_answers_of_the_client_are_told_apart() -> None:
    assert protocol.request_from({"jsonrpc": "2.0", "id": 7, "method": "ping"}) == Request(
        7, "ping", None, False
    )
    assert protocol.request_from(
        {"jsonrpc": "2.0", "id": "a", "method": "tools/list", "params": {"cursor": "x"}}
    ) == Request("a", "tools/list", {"cursor": "x"}, False)
    assert protocol.request_from(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) == Request(None, "notifications/initialized", None, True)
    assert protocol.request_from({"jsonrpc": "2.0", "id": 3, "result": {}}) is None
    assert protocol.request_from({"jsonrpc": "2.0", "id": 3, "error": {"code": 1}}) is None
    assert protocol.request_from({"jsonrpc": "2.0", "id": 4, "method": "ping", "params": None}) == (
        Request(4, "ping", None, False)
    )


@pytest.mark.parametrize(
    ("document", "identifier"),
    [
        (1, None),
        ([], None),
        ("text", None),
        ({"id": 1, "method": "ping"}, 1),
        ({"jsonrpc": "1.0", "id": "a", "method": "ping"}, "a"),
        ({"jsonrpc": "2.0", "id": 2}, 2),
        ({"jsonrpc": "2.0", "id": 2, "method": 5}, 2),
        ({"jsonrpc": "2.0", "id": 2, "method": ""}, 2),
        ({"jsonrpc": "2.0", "id": 1.5, "method": "ping"}, None),
        ({"jsonrpc": "2.0", "id": True, "method": "ping"}, None),
        ({"jsonrpc": "2.0", "id": None, "method": "ping"}, None),
        ({"jsonrpc": "2.0", "id": {"a": 1}, "method": "ping"}, None),
        ({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": "x"}, 3),
        ({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": 4}, 3),
    ],
)
def test_a_message_that_is_not_a_valid_request_is_an_invalid_request(
    document: object, identifier: object
) -> None:
    with pytest.raises(RpcError) as refused:
        protocol.request_from(document)

    assert (refused.value.code, refused.value.word, refused.value.identifier) == (
        -32600,
        "INVALID_REQUEST",
        identifier,
    )


@pytest.mark.parametrize(
    ("requested", "answered"),
    [
        ("2025-06-18", "2025-06-18"),
        ("2025-03-26", "2025-03-26"),
        ("2024-11-05", "2024-11-05"),
        ("2099-01-01", "2025-06-18"),
        (None, "2025-06-18"),
        (20250618, "2025-06-18"),
    ],
)
def test_the_version_of_the_client_is_kept_when_it_is_known(
    requested: object, answered: str
) -> None:
    assert protocol.negotiate(requested) == answered


def test_a_message_is_written_on_one_ascii_line() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "result": {"text": "riga uno\nriga due è"}}

    encoded = protocol.encode(message)

    assert "\n" not in encoded
    assert encoded.isascii()
    assert json.loads(encoded) == message
    with pytest.raises(ValueError):
        protocol.encode({"value": float("nan")})


def test_resource_addresses_carry_the_path_of_the_file() -> None:
    assert protocol.resource_uri("state/state.md") == "orchestwin://state/state.md"
    assert protocol.resource_uri("a b/è.md") == "orchestwin://a%20b/%C3%A8.md"
    assert protocol.resource_path("orchestwin://a%20b/%C3%A8.md") == "a b/è.md"
    assert protocol.resource_path("file:///state.md") is None


def test_a_tool_error_carries_its_code_and_its_sentence() -> None:
    assert protocol.tool_failure("SPEND_REQUIRED", "No.") == {
        "content": [{"type": "text", "text": "No."}],
        "structuredContent": {"code": "SPEND_REQUIRED", "message": "No."},
        "isError": True,
    }
    assert protocol.tool_result({"a": "è"}) == {
        "content": [{"type": "text", "text": '{"a": "è"}'}],
        "structuredContent": {"a": "è"},
        "isError": False,
    }


def test_a_line_that_is_not_json_answers_a_parse_error(tmp_path: Path) -> None:
    server, _ = build(tmp_path)

    assert answer(server, "{") == error(
        None, -32700, "The message is not valid JSON.", "PARSE_ERROR"
    )


def test_the_messages_of_the_protocol_speak_the_language_of_the_command(tmp_path: Path) -> None:
    server, _ = build(tmp_path, language="it")

    assert answer(server, "{") == error(
        None, -32700, "Il messaggio non è JSON valido.", "PARSE_ERROR"
    )
    assert answer(server, request(1, "tools/list")) == error(
        1,
        -32600,
        "Il server non è ancora inizializzato: manda prima initialize.",
        "NOT_INITIALIZED",
    )


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    server, bundle = build(tmp_path)

    assert server.handle("\n") is None
    assert server.handle("   \r\n") is None
    assert server.handle("﻿\n") is None
    assert bundle.output == ""


def test_requests_before_initialize_are_refused_except_ping(tmp_path: Path) -> None:
    server, _ = build(tmp_path)
    refused = error(
        1, -32600, "The server is not initialized yet: send initialize first.", "NOT_INITIALIZED"
    )

    assert answer(server, request(1, "tools/list")) == refused
    assert answer(server, request(1, "no/such/method")) == refused
    assert answer(server, request(2, "ping")) == {"jsonrpc": "2.0", "id": 2, "result": {}}
    started = answer(server, initialize(3))
    assert isinstance(started, dict)
    assert started["result"]["protocolVersion"] == "2025-06-18"
    listed = answer(server, request(4, "tools/list"))
    assert isinstance(listed, dict)
    assert [tool["name"] for tool in listed["result"]["tools"]] == TOOL_NAMES.split(", ")
    assert len(listed["result"]["tools"]) == 13


def test_initialize_can_be_sent_again_and_negotiates_again(tmp_path: Path) -> None:
    server, bundle = ready(tmp_path)

    again = answer(server, initialize(2, "2024-11-05"))

    assert isinstance(again, dict)
    assert again["result"]["protocolVersion"] == "2024-11-05"
    assert server.version == "2024-11-05"
    assert bundle.errors.count("Connected to test client 1.0") == 2


def test_an_unknown_method_is_not_found(tmp_path: Path) -> None:
    server, _ = ready(tmp_path)

    assert answer(server, request(2, "prompts/list")) == error(
        2, -32601, "Unknown method: prompts/list.", "METHOD_NOT_FOUND"
    )


def test_notifications_and_answers_of_the_client_are_never_answered(tmp_path: Path) -> None:
    server, bundle = build(tmp_path)

    assert server.handle(notification("notifications/initialized")) is None
    assert server.handle(notification("notifications/cancelled", {"requestId": 1})) is None
    assert server.handle(notification("tools/list")) is None
    assert server.handle('{"jsonrpc": "2.0", "id": 5, "result": {}}') is None
    assert bundle.output == ""
    assert bundle.errors == ""
    assert server.initialized is False


def test_a_batch_gets_an_array_of_answers(tmp_path: Path) -> None:
    server, _ = build(tmp_path)
    batch = [
        json.loads(initialize(1)),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        json.loads(request(2, "ping")),
        1,
        json.loads(request("three", "tools/list")),
    ]

    answered = answer(server, json.dumps(batch))

    assert isinstance(answered, list)
    assert [item["id"] for item in answered] == [1, 2, None, "three"]
    assert answered[1]["result"] == {}
    assert answered[2] == error(
        None, -32600, "The message is not a valid JSON-RPC 2.0 request.", "INVALID_REQUEST"
    )
    assert [tool["name"] for tool in answered[3]["result"]["tools"]] == TOOL_NAMES.split(", ")
    assert len(answered[3]["result"]["tools"]) == 13


def test_an_empty_batch_is_an_invalid_request(tmp_path: Path) -> None:
    server, _ = build(tmp_path)

    assert answer(server, "[]") == error(
        None, -32600, "The message is not a valid JSON-RPC 2.0 request.", "INVALID_REQUEST"
    )


def test_a_batch_of_notifications_gets_no_answer(tmp_path: Path) -> None:
    server, _ = build(tmp_path)
    batch = [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ]

    assert server.handle(json.dumps(batch)) is None


def test_an_invalid_request_with_a_valid_identifier_is_answered_with_it(tmp_path: Path) -> None:
    server, _ = build(tmp_path)

    assert answer(server, '{"id": 9, "method": "ping"}') == error(
        9, -32600, "The message is not a valid JSON-RPC 2.0 request.", "INVALID_REQUEST"
    )
    assert answer(server, '{"jsonrpc": "2.0", "id": null, "method": "ping"}') == error(
        None, -32600, "The message is not a valid JSON-RPC 2.0 request.", "INVALID_REQUEST"
    )


@pytest.mark.parametrize("method", ["initialize", "tools/list", "resources/list"])
def test_parameters_that_are_not_an_object_are_invalid_params(tmp_path: Path, method: str) -> None:
    server, _ = build(tmp_path) if method == "initialize" else ready(tmp_path)

    assert answer(server, request(5, method, [1])) == error(
        5, -32602, f"The parameters of {method} must be a JSON object.", "INVALID_PARAMS"
    )


def test_tools_call_needs_the_name_of_a_known_tool(tmp_path: Path) -> None:
    server, _ = ready(tmp_path)

    assert answer(server, request(2, "tools/call", {})) == error(
        2,
        -32602,
        "The parameter name of tools/call is missing; it must be a text.",
        "INVALID_PARAMS",
    )
    assert answer(server, request(3, "tools/call", {"name": 4})) == error(
        3,
        -32602,
        "The parameter name of tools/call is missing; it must be a text.",
        "INVALID_PARAMS",
    )
    assert answer(server, call(4, "delete_everything")) == error(
        4,
        -32602,
        f"Unknown tool: delete_everything. Available tools: {TOOL_NAMES}.",
        "UNKNOWN_TOOL",
    )


def test_resources_read_needs_an_address(tmp_path: Path) -> None:
    server, _ = ready(tmp_path)

    assert answer(server, request(2, "resources/read", {})) == error(
        2,
        -32602,
        "The parameter uri of resources/read is missing; it must be a text.",
        "INVALID_PARAMS",
    )


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("project_state", [1], "The arguments of project_state must be a JSON object."),
        ("project_state", {"extra": 1}, "project_state has no argument extra."),
        ("get_twin", {}, "The argument twin of get_twin is missing."),
        (
            "get_twin",
            {"twin": " "},
            "The argument twin of get_twin must be the number of the twin or the beginning of "
            "its name, at most 200 characters.",
        ),
        (
            "get_twin",
            {"twin": True},
            "The argument twin of get_twin must be the number of the twin or the beginning of "
            "its name, at most 200 characters.",
        ),
        (
            "get_twin",
            {"twin": ["1"]},
            "The argument twin of get_twin must be the number of the twin or the beginning of "
            "its name, at most 200 characters.",
        ),
        (
            "get_requirements",
            {"codes": "REQ-001"},
            "The argument codes of get_requirements must be a list of at most 50 codes, each of "
            "at most 20 characters, for example REQ-003.",
        ),
        (
            "get_requirements",
            {"codes": [""]},
            "The argument codes of get_requirements must be a list of at most 50 codes, each of "
            "at most 20 characters, for example REQ-003.",
        ),
        (
            "get_requirements",
            {"codes": ["R" * 21]},
            "The argument codes of get_requirements must be a list of at most 50 codes, each of "
            "at most 20 characters, for example REQ-003.",
        ),
        (
            "get_requirements",
            {"codes": ["REQ-001"] * 51},
            "The argument codes of get_requirements must be a list of at most 50 codes, each of "
            "at most 20 characters, for example REQ-003.",
        ),
        (
            "get_design",
            {"screen": "S" * 21},
            "The argument screen of get_design must be a text of 1-20 characters.",
        ),
        (
            "get_feedback",
            {"limit": 0},
            "The argument limit of get_feedback must be a whole number from 1 to 20.",
        ),
        (
            "get_feedback",
            {"limit": 21},
            "The argument limit of get_feedback must be a whole number from 1 to 20.",
        ),
        (
            "get_feedback",
            {"limit": "3"},
            "The argument limit of get_feedback must be a whole number from 1 to 20.",
        ),
        (
            "get_feedback",
            {"limit": 2.5},
            "The argument limit of get_feedback must be a whole number from 1 to 20.",
        ),
        (
            "get_feedback",
            {"limit": True},
            "The argument limit of get_feedback must be a whole number from 1 to 20.",
        ),
        (
            "get_feedback",
            {"commit": "xyz1234"},
            "The argument commit of get_feedback must be the hash of a commit, 7 to 64 "
            "hexadecimal characters.",
        ),
        (
            "get_feedback",
            {"commit": "abc12"},
            "The argument commit of get_feedback must be the hash of a commit, 7 to 64 "
            "hexadecimal characters.",
        ),
        (
            "get_feedback",
            {"commit": "HEAD"},
            "The argument commit of get_feedback must be the hash of a commit, 7 to 64 "
            "hexadecimal characters.",
        ),
        ("ask_twin", {"twin": "1"}, "The argument question of ask_twin is missing."),
        (
            "ask_twin",
            {"twin": "1", "question": "   "},
            "The argument question of ask_twin must be a text of 1-1000 characters.",
        ),
        (
            "ask_twin",
            {"twin": "1", "question": "a" * 1001},
            "The argument question of ask_twin must be a text of 1-1000 characters.",
        ),
        (
            "review_changes",
            {"commit": "--all"},
            "The argument commit of review_changes must be the hash of a commit, 7 to 64 "
            "hexadecimal characters, or HEAD.",
        ),
    ],
)
def test_arguments_that_do_not_match_the_schema_are_invalid_params(
    tmp_path: Path, name: str, arguments: object, message: str
) -> None:
    server, bundle = ready(tmp_path)

    assert answer(server, call(2, name, arguments)) == error(
        2, -32602, message, "INVALID_ARGUMENTS"
    )
    assert "Unexpected error" not in bundle.errors


def test_an_unexpected_failure_answers_an_internal_error_and_the_server_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(session: object, values: object) -> dict[str, object]:
        raise RuntimeError("boom")

    tools = dict(tools_module.TOOLS_BY_NAME)
    tools["project_state"] = replace(tools["project_state"], run=broken)
    monkeypatch.setattr(tools_module, "TOOLS_BY_NAME", MappingProxyType(tools))
    server, bundle = ready(tmp_path)

    failed = answer(server, call(2, "project_state"))
    pinged = answer(server, request(3, "ping"))

    assert failed == error(
        2, -32603, "Internal error of the server (RuntimeError).", "INTERNAL_ERROR"
    )
    assert pinged == {"jsonrpc": "2.0", "id": 3, "result": {}}
    assert (
        "Unexpected error during tools/call: RuntimeError: boom. The server goes on; --debug "
        "shows the details.\n"
    ) in bundle.errors
    assert "Traceback" not in bundle.errors


def test_debug_shows_the_traceback_of_an_unexpected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(session: object, values: object) -> dict[str, object]:
        raise RuntimeError("boom")

    tools = dict(tools_module.TOOLS_BY_NAME)
    tools["list_twins"] = replace(tools["list_twins"], run=broken)
    monkeypatch.setattr(tools_module, "TOOLS_BY_NAME", MappingProxyType(tools))
    server, bundle = ready(tmp_path, debug=True)

    answer(server, call(2, "list_twins"))

    assert "Traceback (most recent call last)" in bundle.errors
    assert bundle.errors.rstrip().endswith("RuntimeError: boom")
    assert bundle.output == ""


def test_a_document_that_cannot_be_written_as_json_answers_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(session: object, values: object) -> dict[str, object]:
        return {"value": float("nan")}

    tools = dict(tools_module.TOOLS_BY_NAME)
    tools["project_state"] = replace(tools["project_state"], run=invalid)
    monkeypatch.setattr(tools_module, "TOOLS_BY_NAME", MappingProxyType(tools))
    server, bundle = ready(tmp_path)

    assert answer(server, call(2, "project_state")) == error(
        2, -32603, "Internal error of the server (ValueError).", "INTERNAL_ERROR"
    )
    assert "Unexpected error during encode: ValueError: " in bundle.errors


def test_every_sentence_named_by_the_protocol_and_the_tools_exists() -> None:
    keys = [
        *RPC_KEYS,
        *tools_module.INVALID_KEYS.values(),
        *(key for tool in TOOLS for key in (tool.title, tool.description)),
        *(parameter.description for tool in TOOLS for parameter in tool.parameters),
    ]

    assert [key for key in keys if not known(key)] == []
    assert all(set(MESSAGES[key]) == {"it", "en"} for key in keys)
