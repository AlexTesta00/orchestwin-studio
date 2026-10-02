from __future__ import annotations

import contextlib
import io
import traceback
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from orchestwin import __version__
from orchestwin.cli.console import Console
from orchestwin.cli.context import CommandContext
from orchestwin.cli.environment import is_terminal
from orchestwin.cli.errors import CliError
from orchestwin.cli.mcp import knowledge, protocol
from orchestwin.cli.mcp.protocol import Request, RpcError
from orchestwin.cli.mcp.tools import Tools, project_language
from orchestwin.cli.messages import text
from orchestwin.cli.project import ProjectFolder

if TYPE_CHECKING:
    from orchestwin.cli.project import ProjectLink

INITIALIZE: Final = "initialize"
PING: Final = "ping"
TOOLS_LIST: Final = "tools/list"
TOOLS_CALL: Final = "tools/call"
RESOURCES_LIST: Final = "resources/list"
RESOURCES_READ: Final = "resources/read"
ENCODING_METHOD: Final = "encode"


class Server:
    def __init__(self, context: CommandContext, tools: Tools, *, spend: bool) -> None:
        self._context = context
        self._tools = tools
        self._spend = spend
        self.initialized = False
        self.version: str | None = None

    def handle(self, line: str) -> str | None:
        if not line.strip().removeprefix(protocol.BYTE_ORDER_MARK).strip():
            return None
        try:
            document = protocol.decode(line)
        except RpcError as error:
            return self._encoded(self._failure(error, None))
        if isinstance(document, list):
            if not document:
                return self._encoded(self._failure(protocol.invalid_request(), None))
            answers = [answer for item in document if (answer := self.answer(item)) is not None]
            return self._encoded(answers) if answers else None
        answer = self.answer(document)
        return None if answer is None else self._encoded(answer)

    def answer(self, document: object) -> dict[str, object] | None:
        try:
            request = protocol.request_from(document)
        except RpcError as error:
            return self._failure(error, error.identifier)
        if request is None or request.notification:
            return None
        try:
            result = self._dispatch(request)
        except RpcError as error:
            return self._failure(error, request.identifier)
        except Exception as failure:
            self._report(request.method, failure)
            error = protocol.internal_error(type(failure).__name__)
            return self._failure(error, request.identifier)
        return protocol.success(request.identifier, result)

    def _dispatch(self, request: Request) -> object:
        method = request.method
        if method == INITIALIZE:
            return self._initialize(_params(request))
        if method == PING:
            return {}
        if not self.initialized:
            raise protocol.not_initialized()
        if method == TOOLS_LIST:
            _params(request)
            return {"tools": self._tools.definitions()}
        if method == TOOLS_CALL:
            params = _params(request)
            name = params.get("name")
            if not isinstance(name, str):
                raise protocol.param_missing(method, "name")
            return self._tools.call(name, params.get("arguments"))
        if method == RESOURCES_LIST:
            _params(request)
            root = self._knowledge_root()
            paths = [] if root is None else knowledge.markdown_files(root)
            return {"resources": protocol.resource_entries(paths)}
        if method == RESOURCES_READ:
            return self._read(_params(request))
        raise protocol.method_not_found(method)

    def _initialize(self, params: Mapping[str, object]) -> dict[str, object]:
        self.version = protocol.negotiate(params.get("protocolVersion"))
        self.initialized = True
        client = params.get("clientInfo")
        name = client.get("name") if isinstance(client, Mapping) else None
        if isinstance(name, str) and name.split():
            release = client.get("version")
            label = " ".join(name.split())
            if isinstance(release, str) and release.split():
                label = f"{label} {' '.join(release.split())}"
            self._context.console.say("mcp.client", client=label, version=self.version)
        return protocol.initialize_result(self.version, __version__, self._instructions())

    def _instructions(self) -> str:
        link = self._link()
        project = None if link is None else ProjectFolder.find(self._context.directory)
        language = project_language(project, self._context.language)
        name = "-" if link is None else link.project_name
        if self._spend:
            return text("mcp.instructions_spend", language, project=name)
        return text("mcp.instructions_free", language, project=name)

    def _read(self, params: Mapping[str, object]) -> dict[str, object]:
        uri = params.get("uri")
        if not isinstance(uri, str):
            raise protocol.param_missing(RESOURCES_READ, "uri")
        root = self._knowledge_root()
        relative = protocol.resource_path(uri)
        content = (
            None if root is None or relative is None else knowledge.markdown_text(root, relative)
        )
        if content is None:
            raise protocol.resource_not_found(uri)
        return protocol.resource_contents(uri, content)

    def _link(self) -> ProjectLink | None:
        project = ProjectFolder.find(self._context.directory)
        if project is None:
            return None
        try:
            return project.link()
        except CliError:
            return None

    def _knowledge_root(self) -> Path | None:
        project = ProjectFolder.find(self._context.directory)
        link = self._link()
        if project is None or link is None:
            return None
        return project.root / link.knowledge_folder

    def _failure(self, error: RpcError, identifier: str | int | None) -> dict[str, object]:
        message = self._context.text(error.key, **error.values)
        return protocol.failure(identifier, error.code, message, error.word)

    def _encoded(self, message: object) -> str:
        try:
            return protocol.encode(message)
        except (TypeError, ValueError) as failure:
            self._report(ENCODING_METHOD, failure)
            identifier = message.get("id") if isinstance(message, dict) else None
            error = protocol.internal_error(type(failure).__name__)
            return protocol.encode(self._failure(error, identifier))

    def _report(self, method: str, failure: BaseException) -> None:
        console = self._context.console
        console.say(
            "mcp.internal_error",
            method=method,
            kind=type(failure).__name__,
            detail=_safe_text(failure),
        )
        if self._context.debug:
            console.write("".join(traceback.format_exception(failure)).rstrip())


def serve(context: CommandContext, project: ProjectFolder, *, spend: bool) -> int:
    environment = context.environment
    quiet = quiet_context(context)
    server = Server(quiet, Tools(quiet, spend=spend), spend=spend)
    link = project.link()
    output = environment.stdout
    prepare_output(output)
    console = quiet.console
    console.say(
        "mcp.started",
        project=link.project_name,
        folder=str(project.root),
        paid=quiet.text("mcp.paid_on") if spend else quiet.text("mcp.paid_off"),
    )
    try:
        while True:
            line = environment.stdin.readline()
            if not line:
                break
            answer = server.handle(line)
            if answer is not None and not send(output, answer):
                break
    except KeyboardInterrupt:
        console.say("mcp.interrupted")
        return 0
    console.say("mcp.stopped")
    return 0


def quiet_context(context: CommandContext) -> CommandContext:
    environment = replace(
        context.environment,
        stdin=io.StringIO(),
        stdout=context.environment.stderr,
        interactive=False,
    )
    console = Console(environment, language=context.language, color=False)
    return CommandContext(
        environment,
        console,
        language=context.language,
        assume_yes=False,
        debug=context.debug,
        directory=context.directory,
        sessions=context.sessions,
    )


def prepare_output(stream: TextIO) -> None:
    if is_terminal(stream):
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    with contextlib.suppress(OSError, ValueError, io.UnsupportedOperation):
        reconfigure(newline="\n")


def send(stream: TextIO, line: str) -> bool:
    try:
        stream.write(f"{line}\n")
        stream.flush()
    except (OSError, ValueError):
        return False
    return True


def _params(request: Request) -> Mapping[str, object]:
    if request.params is None:
        return {}
    if isinstance(request.params, dict):
        return request.params
    raise protocol.params_not_object(request.method)


def _safe_text(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return type(value).__name__
