from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.messages import (
    align,
    code,
    common,
    costs,
    design,
    errors,
    init,
    jobs,
    login,
    logout,
    mcp,
    package,
    sections,
    status,
    tasks,
    test,
    twins,
    watch,
)

if TYPE_CHECKING:
    from orchestwin.cli.environment import Environment

LANGUAGES: Final = ("it", "en")
DEFAULT_LANGUAGE: Final = "en"
LANGUAGE_VARIABLE: Final = "ORCHESTWIN_LANG"
FILES: Final[Mapping[str, Mapping[str, Mapping[str, str]]]] = MappingProxyType(
    {
        module.__name__.rsplit(".", 1)[1]: module.MESSAGES
        for module in (
            align,
            code,
            common,
            costs,
            design,
            errors,
            init,
            jobs,
            login,
            logout,
            mcp,
            package,
            sections,
            status,
            tasks,
            test,
            twins,
            watch,
        )
    }
)
MESSAGES: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {key: entry for catalogue in FILES.values() for key, entry in catalogue.items()}
)


class _Placeholders(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def known(key: str) -> bool:
    return key in MESSAGES


def template(key: str, language: str, /) -> str | None:
    entry = MESSAGES.get(key)
    if entry is None:
        return None
    sentence = entry.get(language) or entry.get(DEFAULT_LANGUAGE)
    return sentence if isinstance(sentence, str) and sentence else None


def text(key: str, language: str, /, **values: object) -> str:
    sentence = template(key, language)
    if sentence is None:
        return key
    try:
        return sentence.format_map(_Placeholders(values))
    except (AttributeError, IndexError, KeyError, ValueError):
        return sentence


def resolve_language(option: str | None, environment: Environment) -> str:
    candidates = (
        option,
        environment.variables.get(LANGUAGE_VARIABLE),
        environment.system_language,
    )
    for candidate in candidates:
        if candidate and candidate.strip():
            return "it" if candidate.strip().lower().startswith("it") else "en"
    return DEFAULT_LANGUAGE
