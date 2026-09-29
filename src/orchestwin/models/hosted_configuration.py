from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    create_model,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationProviderKind,
)
from orchestwin.projects.requirements_primitives import canonical_json

PROVIDERS_CONFIGURATION_MAX_BYTES: Final = 32_768
ANTHROPIC_PROVIDER_ID: Final = "anthropic"
ANTHROPIC_RUNTIME_ID: Final = "anthropic-messages"
OPENAI_COMPATIBLE_RUNTIME_ID: Final = "openai-chat-completions"
HOSTED_RUNTIME_IDS: Final = frozenset({ANTHROPIC_RUNTIME_ID, OPENAI_COMPATIBLE_RUNTIME_ID})
PROVIDER_MANAGED_TOKENIZER: Final = "provider-managed"
HOSTED_TEMPERATURE: Final = 1.0
DEFAULT_COMPLETION_PATH: Final = "/v1/chat/completions"
HOSTED_PROVIDER_KINDS: Final = frozenset(
    {
        StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
        StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED,
    }
)
MICROUSD_PER_USD: Final = Decimal(1_000_000)
_IDENTIFIER: Final = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_API_KEY_ENV: Final = r"^ORCHESTWIN_[A-Z0-9_]{1,48}_API_KEY$"
_MODEL: Final = r"^[A-Za-z0-9._:/-]{1,128}$"
_PRICE: Final = r"^[0-9]{1,6}(\.[0-9]{1,4})?$"
_AMOUNT: Final = r"^[0-9]{1,7}(\.[0-9]{1,6})?$"
_PURPOSE: Final = r"^[A-Z][A-Z0-9_]{0,63}$"
_ISO_DATE: Final = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_MAX_API_KEY_LENGTH: Final = 4_096


class HostedConfigurationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProviderKeySource(StrEnum):
    PROCESS = "PROCESS"
    DOTENV = "DOTENV"


@dataclass(frozen=True, slots=True)
class ProviderKey:
    value: str = field(repr=False)
    source: ProviderKeySource
    env_name: str


class _ProviderKeySettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        env_ignore_empty=False,
    )


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class AnthropicProviderEntry(_Entry):
    id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["ANTHROPIC_HOSTED"]
    api_key_env: str = Field(pattern=_API_KEY_ENV)

    @property
    def provider_kind(self) -> StructuredGenerationProviderKind:
        return StructuredGenerationProviderKind.ANTHROPIC_HOSTED


class OpenAICompatibleHostedProviderEntry(_Entry):
    id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["OPENAI_COMPATIBLE_HOSTED"]
    api_key_env: str = Field(pattern=_API_KEY_ENV)
    base_url: str = Field(min_length=9, max_length=512)
    completion_path: str = Field(default=DEFAULT_COMPLETION_PATH, min_length=1, max_length=256)

    @property
    def provider_kind(self) -> StructuredGenerationProviderKind:
        return StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED

    @field_validator("base_url")
    @classmethod
    def secure_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or value.endswith("/")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("hosted base URL must be an HTTPS origin without credentials")
        return value

    @field_validator("completion_path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(character in value for character in "?#")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("completion path must be an absolute path")
        return value

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def completion_url(self) -> str:
        return f"{self.base_url}{self.completion_path}"


class LocalProviderEntry(_Entry):
    id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["OPENAI_COMPATIBLE_LOCAL"]
    config_file: Path

    @property
    def provider_kind(self) -> StructuredGenerationProviderKind:
        return StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL

    @field_validator("config_file")
    @classmethod
    def absolute_file(cls, value: Path) -> Path:
        if not value.is_absolute() or ".." in value.parts:
            raise ValueError("local provider configuration must be an absolute path")
        return value


ProviderEntry = Annotated[
    AnthropicProviderEntry | OpenAICompatibleHostedProviderEntry | LocalProviderEntry,
    Field(discriminator="kind"),
]
HostedProviderEntry = AnthropicProviderEntry | OpenAICompatibleHostedProviderEntry


class ModelPrices(_Entry):
    input: str = Field(pattern=_PRICE)
    output: str = Field(pattern=_PRICE)
    cache_read: str = Field(pattern=_PRICE)
    cache_write: str = Field(pattern=_PRICE)

    @property
    def input_per_million(self) -> Decimal:
        return Decimal(self.input)

    @property
    def output_per_million(self) -> Decimal:
        return Decimal(self.output)

    @property
    def cache_read_per_million(self) -> Decimal:
        return Decimal(self.cache_read)

    @property
    def cache_write_per_million(self) -> Decimal:
        return Decimal(self.cache_write)


class HostedModelEntry(_Entry):
    id: str = Field(pattern=_IDENTIFIER)
    provider: str = Field(pattern=_IDENTIFIER)
    model: str = Field(pattern=_MODEL)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    context_window_tokens: int = Field(ge=1024, le=2_000_000, strict=True)
    max_output_tokens: int = Field(ge=128, le=128_000, strict=True)
    reasoning_allowance_tokens: int = Field(ge=0, le=64_000, strict=True)
    timeout_seconds: int = Field(ge=1, le=1800, strict=True)
    characters_per_token: float = Field(ge=1.0, le=8.0, allow_inf_nan=False, strict=True)
    prices: ModelPrices


class LocalModelEntry(_Entry):
    id: str = Field(pattern=_IDENTIFIER)
    provider: str = Field(pattern=_IDENTIFIER)


class ModelRoutes(_Entry):
    default: str = Field(pattern=_IDENTIFIER)
    tasks: dict[str, str] = Field(default_factory=dict)
    purposes: dict[str, str] = Field(default_factory=dict)

    @field_validator("tasks")
    @classmethod
    def known_tasks(cls, value: dict[str, str]) -> dict[str, str]:
        if not set(value) <= TASKS:
            raise ValueError("routes name an unknown task")
        return value

    @field_validator("purposes")
    @classmethod
    def named_purposes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(re.fullmatch(_PURPOSE, key) is None for key in value):
            raise ValueError("routes name an invalid purpose")
        return value

    def targets(self) -> frozenset[str]:
        return frozenset({self.default, *self.tasks.values(), *self.purposes.values()})

    def resolve(self, task: str, purpose: str | None = None) -> str:
        if purpose is not None and purpose in self.purposes:
            return self.purposes[purpose]
        return self.tasks.get(task, self.default)


class BudgetSettings(_Entry):
    per_generation_usd: str = Field(pattern=_AMOUNT)
    per_project_usd: str = Field(pattern=_AMOUNT)
    total_usd: str = Field(pattern=_AMOUNT)
    period_start: date | None = None

    @field_validator("period_start", mode="before")
    @classmethod
    def iso_date(cls, value: object) -> object:
        if value is not None and (not isinstance(value, str) or not re.fullmatch(_ISO_DATE, value)):
            raise ValueError("period start must be an ISO date")
        return value

    @model_validator(mode="after")
    def ordered_ceilings(self) -> BudgetSettings:
        if not (
            Decimal(0)
            < Decimal(self.per_generation_usd)
            <= Decimal(self.per_project_usd)
            <= Decimal(self.total_usd)
        ):
            raise ValueError("budget ceilings must be positive and ordered")
        return self

    @property
    def per_generation_microusd(self) -> int:
        return usd_to_microusd(self.per_generation_usd)

    @property
    def per_project_microusd(self) -> int:
        return usd_to_microusd(self.per_project_usd)

    @property
    def total_microusd(self) -> int:
        return usd_to_microusd(self.total_usd)


class ProvidersConfiguration(_Entry):
    schema_version: int = Field(ge=1, le=1, strict=True)
    providers: tuple[ProviderEntry, ...] = Field(min_length=1, max_length=16)
    models: tuple[HostedModelEntry | LocalModelEntry, ...] = Field(min_length=1, max_length=64)
    routes: ModelRoutes
    budget: BudgetSettings

    @model_validator(mode="after")
    def consistent_references(self) -> ProvidersConfiguration:
        provider_ids = [item.id for item in self.providers]
        model_ids = [item.id for item in self.models]
        if len(set(provider_ids)) != len(provider_ids) or len(set(model_ids)) != len(model_ids):
            raise ValueError("identifiers must be unique")
        providers = {item.id: item for item in self.providers}
        for entry in self.models:
            provider = providers.get(entry.provider)
            if provider is None:
                raise ValueError("model entry names an unknown provider")
            local = isinstance(provider, LocalProviderEntry)
            if local != isinstance(entry, LocalModelEntry):
                raise ValueError("model entry does not match the kind of its provider")
        if {entry.provider for entry in self.models} != set(provider_ids):
            raise ValueError("every provider must serve at least one model entry")
        if not self.routes.targets() <= set(model_ids):
            raise ValueError("routes name an unknown model entry")
        for entry in self.models:
            if isinstance(entry, HostedModelEntry):
                hosted_identity(providers[entry.provider], entry)
        return self

    def provider(self, provider_id: str) -> ProviderEntry:
        for item in self.providers:
            if item.id == provider_id:
                return item
        raise HostedConfigurationError("HOSTED_PROVIDER_UNKNOWN")

    def model(self, entry_id: str) -> HostedModelEntry | LocalModelEntry:
        for item in self.models:
            if item.id == entry_id:
                return item
        raise HostedConfigurationError("HOSTED_MODEL_ENTRY_UNKNOWN")

    def hosted_providers(self) -> tuple[HostedProviderEntry, ...]:
        return tuple(item for item in self.providers if not isinstance(item, LocalProviderEntry))

    def hosted_model(self, entry_id: str) -> HostedModelConfiguration:
        entry = self.model(entry_id)
        if not isinstance(entry, HostedModelEntry):
            raise HostedConfigurationError("HOSTED_MODEL_ENTRY_REQUIRED")
        provider = self.provider(entry.provider)
        return HostedModelConfiguration(
            provider=provider, entry=entry, identity=hosted_identity(provider, entry)
        )

    def route(self, task: str, purpose: str | None = None) -> str:
        return self.routes.resolve(task, purpose)


@dataclass(frozen=True, slots=True)
class HostedModelConfiguration:
    provider: HostedProviderEntry
    entry: HostedModelEntry
    identity: ModelRuntimeIdentity

    @property
    def provider_kind(self) -> StructuredGenerationProviderKind:
        return self.provider.provider_kind

    @property
    def model(self) -> str:
        return self.entry.model

    @property
    def effort(self) -> str | None:
        return self.entry.effort

    @property
    def temperature(self) -> float:
        return HOSTED_TEMPERATURE

    @property
    def max_output_tokens(self) -> int:
        return self.entry.max_output_tokens

    @property
    def context_window_tokens(self) -> int:
        return self.entry.context_window_tokens

    @property
    def timeout_seconds(self) -> int:
        return self.entry.timeout_seconds

    @property
    def reasoning_allowance_tokens(self) -> int:
        return self.entry.reasoning_allowance_tokens

    @property
    def characters_per_token(self) -> float:
        return self.entry.characters_per_token

    @property
    def prices(self) -> ModelPrices:
        return self.entry.prices

    def max_tokens(self, requested_output_tokens: int) -> int:
        return (
            min(requested_output_tokens, self.entry.max_output_tokens)
            + self.entry.reasoning_allowance_tokens
        )

    def estimated_prompt_tokens(self, characters: int) -> int:
        estimate = Decimal(characters) / Decimal(str(self.entry.characters_per_token))
        return int(estimate.to_integral_value(rounding=ROUND_CEILING))


def usd_to_microusd(value: str | Decimal) -> int:
    amount = Decimal(value) * MICROUSD_PER_USD
    return int(amount.to_integral_value(rounding=ROUND_HALF_UP))


def hosted_identity(provider: ProviderEntry, entry: HostedModelEntry) -> ModelRuntimeIdentity:
    if isinstance(provider, AnthropicProviderEntry):
        provider_id, runtime_id = ANTHROPIC_PROVIDER_ID, ANTHROPIC_RUNTIME_ID
    elif isinstance(provider, OpenAICompatibleHostedProviderEntry):
        provider_id, runtime_id = provider.host, OPENAI_COMPATIBLE_RUNTIME_ID
    else:
        raise HostedConfigurationError("HOSTED_PROVIDER_REQUIRED")
    digest = hashlib.sha256(
        canonical_json(
            {"provider": provider.model_dump(mode="json"), "model": entry.model_dump(mode="json")}
        ).encode("utf-8")
    ).hexdigest()
    return ModelRuntimeIdentity(
        provider_id=provider_id,
        runtime_id=runtime_id,
        base_model_repository=f"{provider_id}/{entry.model}",
        base_model_revision=entry.model,
        tokenizer_revision=PROVIDER_MANAGED_TOKENIZER,
        configuration_sha256=digest,
    )


def served_model_matches(configured: str, served: object) -> bool:
    return isinstance(served, str) and (served == configured or served.startswith(configured + "-"))


def parse_providers_configuration(raw: bytes) -> ProvidersConfiguration:
    if not isinstance(raw, bytes) or not raw or len(raw) > PROVIDERS_CONFIGURATION_MAX_BYTES:
        raise HostedConfigurationError("HOSTED_PROVIDERS_CONFIGURATION_INVALID")
    try:
        return ProvidersConfiguration.model_validate(strict_json_object(raw))
    except (ValueError, TypeError):
        raise HostedConfigurationError("HOSTED_PROVIDERS_CONFIGURATION_INVALID") from None


def load_providers_configuration(path: Path) -> tuple[ProvidersConfiguration, bytes]:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise HostedConfigurationError("HOSTED_PROVIDERS_CONFIGURATION_PATH_INVALID")
    try:
        with path.open("rb") as stream:
            raw = stream.read(PROVIDERS_CONFIGURATION_MAX_BYTES + 1)
    except OSError:
        raise HostedConfigurationError("HOSTED_PROVIDERS_CONFIGURATION_UNAVAILABLE") from None
    return parse_providers_configuration(raw), raw


def read_provider_keys(
    configuration: ProvidersConfiguration, *, env_file: str | Path | None = ".env"
) -> dict[str, ProviderKey]:
    providers = configuration.hosted_providers()
    if not providers:
        return {}
    names = sorted({provider.api_key_env for provider in providers})
    settings_type = create_model(
        "_HostedProviderKeys",
        __base__=_ProviderKeySettings,
        **{name.lower(): (SecretStr | None, Field(default=None, repr=False)) for name in names},
    )
    try:
        loaded = settings_type(_env_file=env_file)
    except (OSError, UnicodeError, ValidationError, SettingsError):
        raise HostedConfigurationError("HOSTED_PROVIDER_API_KEY_UNREADABLE") from None
    keys: dict[str, ProviderKey] = {}
    for provider in providers:
        secret = getattr(loaded, provider.api_key_env.lower())
        value = "" if secret is None else secret.get_secret_value().strip()
        if not value or len(value) > _MAX_API_KEY_LENGTH or any(c.isspace() for c in value):
            raise HostedConfigurationError("HOSTED_PROVIDER_API_KEY_MISSING")
        source = (
            ProviderKeySource.PROCESS
            if provider.api_key_env in os.environ
            else ProviderKeySource.DOTENV
        )
        keys[provider.id] = ProviderKey(value=value, source=source, env_name=provider.api_key_env)
    return keys


def declared_limits_problem(
    configuration: HostedModelConfiguration,
    *,
    context_window_tokens: object,
    max_output_tokens: object,
) -> str | None:
    if (
        isinstance(context_window_tokens, int)
        and not isinstance(context_window_tokens, bool)
        and context_window_tokens < configuration.context_window_tokens
    ):
        return "HOSTED_MODEL_WINDOW_TOO_SMALL"
    if (
        isinstance(max_output_tokens, int)
        and not isinstance(max_output_tokens, bool)
        and max_output_tokens < configuration.max_tokens(configuration.max_output_tokens)
    ):
        return "HOSTED_MODEL_OUTPUT_TOO_SMALL"
    return None


__all__ = [
    "ANTHROPIC_PROVIDER_ID",
    "ANTHROPIC_RUNTIME_ID",
    "DEFAULT_COMPLETION_PATH",
    "HOSTED_PROVIDER_KINDS",
    "HOSTED_RUNTIME_IDS",
    "HOSTED_TEMPERATURE",
    "OPENAI_COMPATIBLE_RUNTIME_ID",
    "PROVIDERS_CONFIGURATION_MAX_BYTES",
    "PROVIDER_MANAGED_TOKENIZER",
    "AnthropicProviderEntry",
    "BudgetSettings",
    "HostedConfigurationError",
    "HostedModelConfiguration",
    "HostedModelEntry",
    "HostedProviderEntry",
    "LocalModelEntry",
    "LocalProviderEntry",
    "ModelPrices",
    "ModelRoutes",
    "OpenAICompatibleHostedProviderEntry",
    "ProviderKey",
    "ProviderKeySource",
    "ProvidersConfiguration",
    "declared_limits_problem",
    "hosted_identity",
    "load_providers_configuration",
    "parse_providers_configuration",
    "read_provider_keys",
    "served_model_matches",
    "usd_to_microusd",
]
