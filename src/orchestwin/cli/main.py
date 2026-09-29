from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Final, TextIO

from orchestwin import __version__
from orchestwin.cli.commands import COMMANDS
from orchestwin.cli.console import Console, plain, stream_encoding, terminal_width
from orchestwin.cli.context import CommandContext
from orchestwin.cli.environment import Environment, real_environment
from orchestwin.cli.errors import INTERRUPTED_STATUS, USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.messages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    known,
    resolve_language,
    template,
    text,
)

PROGRAM: Final = "ut"
LANGUAGE_OPTION: Final = "--lang"
NO_COLOR_OPTION: Final = "--no-color"
DEBUG_OPTION: Final = "--debug"
END_OF_OPTIONS: Final = "--"
MINIMUM_HELP_WIDTH: Final = 40
UNEXPECTED_KEY: Final = "errors.UNEXPECTED"
INTERRUPTED_KEY: Final = "common.interrupted"
BARE_UNEXPECTED: Final = "{kind}: {detail}"
PARSER_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}


class ParserExit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def main(argv: Sequence[str] | None = None, *, environment: Environment | None = None) -> int:
    stream: object = sys.stderr if environment is None else environment.stderr
    language = DEFAULT_LANGUAGE
    debug = False
    try:
        arguments = [str(argument) for argument in (sys.argv[1:] if argv is None else argv)]
        debug = has_flag(arguments, DEBUG_OPTION)
        environment = real_environment() if environment is None else environment
        stream = environment.stderr
        language = resolve_language(option_value(arguments, LANGUAGE_OPTION), environment)
        return _main(arguments, environment, language)
    except KeyboardInterrupt:
        write_plainly(stream, f"{template(INTERRUPTED_KEY, language) or INTERRUPTED_KEY}\n")
        return INTERRUPTED_STATUS
    except Exception as failure:
        report_unexpected(stream, language, failure, debug=debug)
        return 1


def _main(arguments: list[str], environment: Environment, language: str) -> int:
    parser = build_parser(environment, language, terminal_width(environment))
    try:
        namespace = parser.parse_args(arguments)
    except ParserExit as exit_request:
        return exit_request.status
    language = resolve_language(namespace.lang, environment)
    console = Console(environment, language=language, color=not namespace.no_color)
    if namespace.command is None:
        parser.print_help()
        console.error("common.missing_command")
        return USAGE_STATUS
    context = CommandContext(
        environment,
        console,
        language=language,
        assume_yes=namespace.yes,
        debug=namespace.debug,
        directory=project_directory(environment, namespace.project_dir),
    )
    module = next(module for module in COMMANDS if namespace.command == module.NAME)
    return execute(module, context, namespace)


def execute(module: ModuleType, context: CommandContext, namespace: argparse.Namespace) -> int:
    stream = context.environment.stderr
    try:
        return int(module.run(context, namespace))
    except CliError as error:
        try:
            report_error(context.console, error, module.NAME)
        except Exception as failure:
            report_unexpected(stream, context.language, failure, debug=context.debug)
        return error.status
    except KeyboardInterrupt:
        try:
            context.console.error(INTERRUPTED_KEY)
        except Exception:
            interrupted = template(INTERRUPTED_KEY, context.language) or INTERRUPTED_KEY
            write_plainly(stream, f"{interrupted}\n")
        return INTERRUPTED_STATUS
    except SystemExit as exit_request:
        return exit_status(exit_request, stream)
    except Exception as failure:
        report_unexpected(stream, context.language, failure, debug=context.debug)
        return 1


def report_error(console: Console, error: CliError, command: str) -> None:
    key = error_key(error, command)
    if key is not None:
        console.error(key, **error.values)
    elif isinstance(error, ApiFailure):
        console.error(
            "errors.API_FAILURE",
            **{**error.values, "code": error.code, "http_status": error.http_status},
        )
    else:
        console.error("errors.UNKNOWN", **{**error.values, "code": error.code})


def error_key(error: CliError, command: str) -> str | None:
    reason = error.values.get("reason")
    candidates: list[str] = []
    if isinstance(reason, str) and reason:
        candidates.extend(
            (f"{command}.errors.{error.code}.{reason}", f"errors.{error.code}.{reason}")
        )
    candidates.extend((f"{command}.errors.{error.code}", f"errors.{error.code}"))
    return next((key for key in candidates if known(key)), None)


def report_unexpected(
    stream: object, language: str, failure: BaseException, *, debug: bool
) -> None:
    write_plainly(stream, f"{unexpected_text(language, failure)}\n")
    if debug:
        write_plainly(stream, f"{traceback_text(failure)}\n")


def unexpected_text(language: str, failure: BaseException) -> str:
    sentence = template(UNEXPECTED_KEY, language) or BARE_UNEXPECTED
    return sentence.replace("{kind}", type(failure).__name__).replace(
        "{detail}", safe_text(failure)
    )


def traceback_text(failure: BaseException) -> str:
    try:
        return "".join(traceback.format_exception(failure)).rstrip()
    except Exception:
        return type(failure).__name__


def safe_text(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return type(value).__name__


def write_plainly(stream: object, text: str) -> None:
    try:
        line = plain(text, stream_encoding(stream))
    except Exception:
        line = text.encode("ascii", "backslashreplace").decode("ascii")
    try:
        stream.write(line)
        stream.flush()
    except Exception:
        return


def exit_status(request: SystemExit, stream: object) -> int:
    code = request.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    write_plainly(stream, f"{safe_text(code)}\n")
    return 1


def build_parser(environment: Environment, language: str, width: int) -> argparse.ArgumentParser:
    parser_class = _parser_class(environment)
    formatter = _formatter_class(language, max(width - 2, MINIMUM_HELP_WIDTH))
    parser = parser_class(
        prog=PROGRAM,
        description=text("common.description", language),
        formatter_class=formatter,
        add_help=False,
        allow_abbrev=False,
        **PARSER_OPTIONS,
    )
    parser.add_argument("-h", "--help", action="help", help="common.option_help")
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM} {__version__}",
        help="common.option_version",
    )
    parser.add_argument(LANGUAGE_OPTION, choices=LANGUAGES, help="common.option_lang")
    parser.add_argument(NO_COLOR_OPTION, action="store_true", help="common.option_no_color")
    parser.add_argument("--yes", action="store_true", help="common.option_yes")
    parser.add_argument("--project-dir", metavar="PATH", help="common.option_project_dir")
    parser.add_argument(DEBUG_OPTION, action="store_true", help="common.option_debug")
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", title=text("common.commands_title", language)
    )
    for module in COMMANDS:
        summary = text(command_help_key(module.NAME), language)
        subparser = commands.add_parser(
            module.NAME,
            help=summary.replace("%", "%%"),
            description=summary,
            formatter_class=formatter,
            add_help=False,
            allow_abbrev=False,
            **PARSER_OPTIONS,
        )
        subparser.add_argument("-h", "--help", action="help", help="common.option_help")
        module.configure(subparser)
    return parser


def command_help_key(name: str) -> str:
    key = f"{name}.help"
    return key if known(key) else "common.not_available"


def _parser_class(environment: Environment) -> type[argparse.ArgumentParser]:
    class Parser(argparse.ArgumentParser):
        def _print_message(self, message: str, file: TextIO | None = None) -> None:
            if not message:
                return
            stream = environment.stdout if file is sys.stdout else environment.stderr
            stream.write(plain(message, stream_encoding(stream)))
            stream.flush()

        def exit(self, status: int = 0, message: str | None = None) -> None:
            if message:
                self._print_message(message, sys.stderr)
            raise ParserExit(status)

    return Parser


def _formatter_class(language: str, width: int) -> type[argparse.HelpFormatter]:
    class Formatter(argparse.HelpFormatter):
        def __init__(self, prog: str, **options: object) -> None:
            options["width"] = width
            super().__init__(prog, **options)

        def _get_help_string(self, action: argparse.Action) -> str | None:
            help_text = action.help
            if isinstance(help_text, str) and known(help_text):
                return text(help_text, language).replace("%", "%%")
            return help_text

    return Formatter


def option_value(arguments: Sequence[str], name: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == END_OF_OPTIONS:
            return None
        if argument == name:
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if argument.startswith(f"{name}="):
            return argument[len(name) + 1 :]
    return None


def has_flag(arguments: Sequence[str], name: str) -> bool:
    for argument in arguments:
        if argument == END_OF_OPTIONS:
            return False
        if argument == name:
            return True
    return False


def project_directory(environment: Environment, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else environment.working_directory / path
