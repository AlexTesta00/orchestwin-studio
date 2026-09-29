"""Explicit local real-model composition, identity checks and readiness.

This policy configures proposal inference and the separately trained S67 evaluator.
It does not execute cases, start servers, retry calls, or qualify semantic quality.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.client
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.evaluation.final_runtime import (
    FinalEvaluatorRuntime,
    FinalEvaluatorSettings,
    build_final_evaluator_runtime,
)
from orchestwin.evaluation.local_runtime import LocalEvaluatorRuntime, build_local_evaluator_runtime
from orchestwin.models.anthropic_hosted import (
    anthropic_model_readiness,
    build_anthropic_adapter,
    create_anthropic_client,
)
from orchestwin.models.design_runtime import DesignRuntime, DesignRuntimeMode
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import (
    AnthropicProviderEntry,
    HostedConfigurationError,
    HostedModelConfiguration,
    HostedModelEntry,
    LocalProviderEntry,
    ProviderKey,
    ProvidersConfiguration,
    parse_providers_configuration,
    read_provider_keys,
)
from orchestwin.models.hosted_schema import PromptedSchemas
from orchestwin.models.model_proposals import (
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    ModelTeamProposalAdapter,
    ModelUserModelingAdapter,
)
from orchestwin.models.openai_hosted import build_openai_hosted_adapter, openai_model_readiness
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import (
    ProposalGenerator,
    ProposalModelConfiguration,
    build_proposal_generator,
)
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.requirements_runtime import RequirementsRuntime, RequirementsRuntimeMode
from orchestwin.models.schema_decoding import POLICY as SCHEMA_DECODING_POLICY
from orchestwin.models.schema_decoding import VERSION as SCHEMA_DECODER_VERSION
from orchestwin.models.serialized_generation import SerializedGenerationPort
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.user_modeling_runtime import UserModelingRuntime, UserModelingRuntimeMode

DATABASE_READINESS_TIMEOUT_SECONDS = 10


class RealModelRuntimeError(RuntimeError):
    """Fixed diagnostic codes; credentials and configuration inputs stay private."""


class RealModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    proposal_config_file: Path
    final_evaluator_ready_file: Path | None = None
    final_evaluator_config_file: Path | None = None

    @model_validator(mode="after")
    def absolute_paths(self):
        if (self.final_evaluator_ready_file is None) == (self.final_evaluator_config_file is None):
            raise ValueError("select exactly one evaluator configuration")
        if any(
            path is not None and (not path.is_absolute() or ".." in path.parts)
            for path in (
                self.proposal_config_file,
                self.final_evaluator_ready_file,
                self.final_evaluator_config_file,
            )
        ):
            raise ValueError("absolute model configuration paths required")
        return self


class HostedRealModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: int = Field(ge=2, le=2, strict=True)
    providers_config_file: Path
    final_evaluator_config_file: Path | None = None

    @model_validator(mode="after")
    def absolute_paths(self):
        if any(
            path is not None and (not path.is_absolute() or ".." in path.parts)
            for path in (self.providers_config_file, self.final_evaluator_config_file)
        ):
            raise ValueError("absolute model configuration paths required")
        return self


class _Overrides(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    team_proposal_provider: str | None = None
    user_modeling_mode: str | None = None
    requirements_mode: str | None = None
    design_mode: str | None = None
    proposal_model_config_file: Path | None = None
    team_proposal_model_config_file: Path | None = None
    user_modeling_model_config_file: Path | None = None
    requirements_model_config_file: Path | None = None
    design_model_config_file: Path | None = None
    final_evaluator_enabled: bool | None = None
    final_evaluator_ready_file: Path | None = None

    def validate_against(self, config):
        hosted = isinstance(config, HostedRealModelConfiguration)
        for field_name, value in self:
            if value is None:
                continue
            if field_name == "final_evaluator_enabled":
                valid = value is True and (
                    not hosted or config.final_evaluator_config_file is not None
                )
            elif field_name == "final_evaluator_ready_file":
                valid = not hosted and value == config.final_evaluator_ready_file
            elif field_name.endswith("config_file"):
                valid = not hosted and value == config.proposal_config_file
            else:
                valid = value == "MODEL_ADAPTER"
            if not valid:
                raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CONFLICT")


def _read(path, maximum=32768):
    path = Path(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
    ):
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_PATH_INVALID")
    if not path.is_file():
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_FILE_REQUIRED")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_TOO_LARGE")
    return raw


def _compatible_schema_decoder(value):
    if not isinstance(value, str):
        return False
    pinned = SCHEMA_DECODER_VERSION.split(".")
    parts = value.split(".")
    return (
        len(parts) == 3
        and all(part.isdigit() for part in parts)
        and parts[0] == pinned[0]
        and int(parts[1]) >= int(pinned[1]) - 1
    )


def _proposal_health(config, token, supported_tasks=TASKS):
    endpoint = urlsplit(config.base_url)
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=10)
    try:
        connection.request(
            "GET", "/health", headers={"Authorization": "Bearer " + token, "Connection": "close"}
        )
        response = connection.getresponse()
        body = response.read(32769)
        if (
            response.status != 200
            or len(body) > 32768
            or response.getheader("Content-Type", "").split(";", 1)[0] != "application/json"
        ):
            raise RealModelRuntimeError("PROPOSAL_HEALTH_HTTP_REJECTED")
        health = strict_json_object(body)
        if not (
            health.get("health_contract_version") == 2
            and health.get("status") == "READY"
            and health.get("model_name") == config.model_name
            and health.get("model_identity") == config.identity.to_snapshot()
            and health.get("supported_tasks") == sorted(supported_tasks)
            and health.get("schema_decoding") == SCHEMA_DECODING_POLICY
            and _compatible_schema_decoder(health.get("schema_decoder_version"))
            and type(health.get("max_output_tokens")) is int
            and health["max_output_tokens"] >= config.max_output_tokens
            and type(health.get("max_sequence_length")) is int
            and health["max_sequence_length"] > config.max_output_tokens
            and health["max_sequence_length"] >= config.context_window_tokens
            and type(health.get("completed_generation_count")) is int
            and health["completed_generation_count"] >= 0
            and _proposal_adapter_matches(config, health)
            and health.get("training_executed") is False
            and health.get("fallback_policy") == "FAIL_CLOSED_NO_FAKE_FALLBACK"
        ):
            raise RealModelRuntimeError("PROPOSAL_HEALTH_IDENTITY_OR_CAPABILITY_MISMATCH")
        return health
    except (OSError, http.client.HTTPException, ValueError, TypeError):
        raise RealModelRuntimeError("PROPOSAL_HEALTH_UNAVAILABLE") from None
    finally:
        connection.close()


def _proposal_adapter_matches(config, health):
    """An adapted identity requires its own explicitly selected proposer adapter.

    A shared evaluator adapter can be resident for an unadapted proposer, but
    must be disabled on that endpoint. Neither role can impersonate the other.
    """
    adapted = config.identity.adapter_id is not None
    if adapted:
        return (
            config.identity.adapter_sha256 is not None
            and health.get("adapter_loaded") is True
            and health.get("adapter_active") is True
            and health.get("adapter_name") == "proposer"
            and health.get("adapter_role") == "proposal"
        )
    return (
        config.identity.adapter_sha256 is None
        and health.get("adapter_active") is False
        and type(health.get("adapter_loaded")) is bool
        and health.get("adapter_name") is None
        and health.get("adapter_role") is None
    )


def _assert_sealed_files(sealed_files):
    try:
        for path, digest in sealed_files:
            if hashlib.sha256(_read(path)).hexdigest() != digest:
                raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
    except OSError:
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_UNAVAILABLE") from None


class _ConfigurationSealedPort:
    """Recheck the selected files after taking the shared inference lock."""

    def __init__(self, port, sealed_files):
        self._port, self._files = port, sealed_files

    async def generate(self, request, **options):
        _assert_sealed_files(self._files)
        return await self._port.generate(request, **options)


@dataclass(frozen=True)
class HostedProviderCheck:
    provider_id: str
    kind: str
    key: ProviderKey = field(repr=False)
    models: tuple[tuple[str, HostedModelConfiguration], ...]
    probe: Callable[[HostedModelConfiguration], Awaitable[dict]] = field(repr=False)

    async def observe(self):
        observations = await asyncio.gather(
            *(self.probe(configuration) for _, configuration in self.models),
            return_exceptions=True,
        )
        models = {}
        for (entry_id, configuration), value in zip(self.models, observations, strict=True):
            models[entry_id] = (
                {
                    "model": configuration.model,
                    "ready": False,
                    "code": "HOSTED_PROVIDER_UNAVAILABLE",
                }
                if isinstance(value, BaseException)
                else value
            )
        return {
            "ready": all(item["ready"] for item in models.values()),
            "kind": self.kind,
            "api_key_env": self.key.env_name,
            "api_key_present": True,
            "api_key_source": self.key.source.value,
            "models": models,
        }


@dataclass(frozen=True)
class LocalProposalCheck:
    entry_id: str
    configuration: ProposalModelConfiguration
    token: str = field(repr=False)


@dataclass(frozen=True)
class RealModelRuntime:
    proposal_configuration: ProposalModelConfiguration | HostedModelConfiguration
    final_evaluator: FinalEvaluatorRuntime | LocalEvaluatorRuntime | None
    team: ModelTeamProposalAdapter
    user_modeling: UserModelingRuntime
    requirements: RequirementsRuntime
    design: DesignRuntime
    _files: tuple[tuple[Path, str], ...] = field(repr=False)
    _token: str | None = field(repr=False)
    schema_version: int = 1
    providers: ProvidersConfiguration | None = None
    budget: GenerationBudget | None = None
    _hosted_checks: tuple[HostedProviderCheck, ...] = field(default=(), repr=False)
    _local_checks: tuple[LocalProposalCheck, ...] = field(default=(), repr=False)
    _clients: tuple[Any, ...] = field(default=(), repr=False)

    def _assert_unchanged(self):
        _assert_sealed_files(self._files)

    async def close(self):
        for client in self._clients:
            closing = getattr(client, "close", None)
            if closing is not None:
                await closing()

    async def spent_total_microusd(self, session_factory):
        if self.budget is None or session_factory is None:
            return None
        from orchestwin.models.proposal_evidence_persistence import (
            SqlAlchemyProposalEvidenceStore,
        )

        try:
            async with asyncio.timeout(DATABASE_READINESS_TIMEOUT_SECONDS):
                return await SqlAlchemyProposalEvidenceStore(session_factory).spent_microusd(
                    since=self.budget.period_start
                )
        except (ProposalEvidenceError, sa.exc.SQLAlchemyError, OSError, TimeoutError):
            return None

    def routes_report(self):
        if self.providers is None:
            return None

        def served(entry_id):
            entry = self.providers.model(entry_id)
            provider = self.providers.provider(entry.provider)
            if isinstance(entry, HostedModelEntry):
                model = entry.model
            else:
                model = next(
                    item.configuration.model_name
                    for item in self._local_checks
                    if item.entry_id == entry_id
                )
            return {
                "model_entry": entry_id,
                "provider_kind": provider.provider_kind.value,
                "model": model,
            }

        routes = self.providers.routes
        return {
            "tasks": {task: served(routes.resolve(task)) for task in sorted(TASKS)},
            "purposes": {
                purpose: served(entry_id) for purpose, entry_id in sorted(routes.purposes.items())
            },
        }

    async def check_readiness(self, session_factory):
        """Fresh authenticated health and schema checks, without model inference."""
        self._assert_unchanged()
        if self.schema_version == 2:
            return await self._hosted_readiness(session_factory)
        operations = [
            asyncio.to_thread(_proposal_health, self.proposal_configuration, self._token),
            self.final_evaluator.check_health(),
            _check_schema(session_factory),
        ]
        names = ["proposals", "evaluator", "database"]
        checks = await asyncio.gather(*operations, return_exceptions=True)
        components = {}
        for name, value in zip(names, checks, strict=True):
            if isinstance(value, BaseException):
                components[name] = {
                    "ready": False,
                    "code": str(value)
                    if isinstance(value, RealModelRuntimeError)
                    else "MODEL_DEPENDENCY_UNAVAILABLE",
                }
            else:
                components[name] = {"ready": True, "observation": value}
        report = {
            "mode": "REAL_REQUIRED",
            "ready": all(c["ready"] for c in components.values()),
            "components": components,
            "proposal_tasks": sorted(TASKS),
            "proposal_temperature": self.proposal_configuration.temperature,
            "evaluator_temperature": 0.0,
            "inference_concurrency_per_api_process": 1,
            "generation_performed": False,
            "semantic_quality_qualified": False,
            "formal_campaign_ready": False,
        }
        return report

    async def _hosted_readiness(self, session_factory):
        names, operations = [], []
        for check in self._hosted_checks:
            names.append(f"provider:{check.provider_id}")
            operations.append(check.observe())
        for check in self._local_checks:
            names.append(f"local:{check.entry_id}")
            operations.append(asyncio.to_thread(_proposal_health, check.configuration, check.token))
        if self.final_evaluator is not None:
            names.append("evaluator")
            operations.append(self.final_evaluator.check_health())
        names.append("database")
        operations.append(_check_schema(session_factory))
        checks = await asyncio.gather(*operations, return_exceptions=True)
        components = {}
        for name, value in zip(names, checks, strict=True):
            if isinstance(value, BaseException):
                components[name] = {
                    "ready": False,
                    "code": str(value)
                    if isinstance(value, RealModelRuntimeError)
                    else "MODEL_DEPENDENCY_UNAVAILABLE",
                }
            elif name.startswith("provider:"):
                components[name] = value
            else:
                components[name] = {"ready": True, "observation": value}
        spent = await self.spent_total_microusd(session_factory)
        return {
            "mode": "REAL_REQUIRED",
            "manifest_schema_version": 2,
            "ready": all(item["ready"] for item in components.values()),
            "components": components,
            "proposal_tasks": sorted(TASKS),
            "routes": self.routes_report(),
            "budget": self.budget.report(spent),
            "evaluator_configured": self.final_evaluator is not None,
            "generation_performed": False,
            "semantic_quality_qualified": False,
            "formal_campaign_ready": False,
        }


async def _check_schema(session_factory):
    try:
        async with (
            asyncio.timeout(DATABASE_READINESS_TIMEOUT_SECONDS),
            session_factory() as session,
            session.begin(),
        ):
            await session.execute(sa.text("SET TRANSACTION READ ONLY"))
            revisions = tuple(
                await session.scalars(sa.text("SELECT version_num FROM alembic_version"))
            )
        config = Config()
        config.set_main_option("script_location", str(files("orchestwin.persistence.migrations")))
        scripts = ScriptDirectory.from_config(config)
        if len(revisions) != 1 or "0040_source_file_evidence" not in {
            r.revision for r in scripts.walk_revisions(base="base", head=revisions[0])
        }:
            raise RealModelRuntimeError("PROPOSAL_EVIDENCE_MIGRATION_REQUIRED")
        return {"revision": revisions[0], "proposal_evidence_schema_available": True}
    except RealModelRuntimeError:
        raise
    except Exception:
        raise RealModelRuntimeError("MODEL_DATABASE_SCHEMA_UNAVAILABLE") from None


def _sealed_hashes(sealed_files):
    return tuple((path, hashlib.sha256(content).hexdigest()) for path, content in sealed_files)


def _local_proposal_generator(provider, evaluator):
    proposal_raw = _read(provider.config_file)
    generator = build_proposal_generator(provider.config_file)
    proposal = generator.configuration
    if proposal.temperature <= 0 or proposal.identity.adapter_id is not None:
        raise RealModelRuntimeError("SAMPLED_BASE_PROPOSAL_MODEL_REQUIRED")
    token_raw = _read(proposal.token_file, 4096)
    if generator.port._bearer_token != token_raw.decode("ascii"):
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
    if _read(provider.config_file) != proposal_raw:
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
    if evaluator is not None and (
        proposal.identity.to_snapshot() == evaluator.identity
        or proposal.base_url == evaluator.base_url
    ):
        raise RealModelRuntimeError("SEPARATE_PROPOSAL_AND_EVALUATOR_IDENTITIES_REQUIRED")
    sealed = [(provider.config_file, proposal_raw), (proposal.token_file, token_raw)]
    return generator, sealed, token_raw.decode("ascii")


def _build_hosted_runtime(
    path, raw, config, *, env_file, anthropic_client_factory, openai_model_fetch
):
    providers_raw = _read(config.providers_config_file)
    providers = parse_providers_configuration(providers_raw)
    keys = read_provider_keys(providers, env_file=env_file)
    budget = GenerationBudget.from_settings(providers.budget)
    evaluator = (
        build_local_evaluator_runtime(config.final_evaluator_config_file)
        if config.final_evaluator_config_file is not None
        else None
    )
    manifest_files = [(path, raw), (config.providers_config_file, providers_raw)]
    prompted_schemas = PromptedSchemas()
    lock = asyncio.Lock()
    all_files = list(manifest_files)
    clients = {}
    generators = {}
    probes = {}
    local_checks = []
    for entry in providers.models:
        provider = providers.provider(entry.provider)
        if isinstance(provider, LocalProviderEntry):
            generator, local_files, token = _local_proposal_generator(provider, evaluator)
            generator.port = SerializedGenerationPort(
                _ConfigurationSealedPort(
                    generator.port, _sealed_hashes(manifest_files + local_files)
                ),
                lock,
            )
            all_files.extend(item for item in local_files if item not in all_files)
            local_checks.append(LocalProposalCheck(entry.id, generator.configuration, token))
            generators[entry.id] = generator
            continue
        configuration = providers.hosted_model(entry.id)
        key = keys[provider.id]
        if isinstance(provider, AnthropicProviderEntry):
            if provider.id not in clients:
                clients[provider.id] = anthropic_client_factory(key.value)
            client = clients[provider.id]
            port = build_anthropic_adapter(configuration, client=client, api_key=key.value)
            probe = _anthropic_probe(client)
        else:
            port = build_openai_hosted_adapter(configuration, api_key=key.value)
            probe = _openai_probe(key.value, openai_model_fetch)
        probes.setdefault(provider.id, (provider, key, probe, []))[3].append(
            (entry.id, configuration)
        )
        generators[entry.id] = ProposalGenerator(
            configuration,
            _ConfigurationSealedPort(port, _sealed_hashes(manifest_files)),
            budget,
            prompted_schemas,
        )
    routing = RoutingProposalGenerator(generators, providers.routes)
    if evaluator is not None:
        evaluator = replace(evaluator, generation_lock=lock)
    hosted_checks = tuple(
        HostedProviderCheck(
            provider_id=provider.id,
            kind=provider.provider_kind.value,
            key=key,
            models=tuple(models),
            probe=probe,
        )
        for provider, key, probe, models in probes.values()
    )
    return RealModelRuntime(
        routing.configuration,
        evaluator,
        ModelTeamProposalAdapter(routing),
        UserModelingRuntime(
            UserModelingRuntimeMode.MODEL_ADAPTER, ModelUserModelingAdapter(routing)
        ),
        RequirementsRuntime(
            RequirementsRuntimeMode.MODEL_ADAPTER, ModelRequirementsAdapter(routing)
        ),
        DesignRuntime(DesignRuntimeMode.MODEL_ADAPTER, ModelDesignAdapter(routing)),
        _sealed_hashes(all_files),
        None,
        schema_version=2,
        providers=providers,
        budget=budget,
        _hosted_checks=hosted_checks,
        _local_checks=tuple(local_checks),
        _clients=tuple(clients.values()),
    )


def _anthropic_probe(client):
    async def probe(configuration):
        return await anthropic_model_readiness(client, configuration)

    return probe


def _openai_probe(api_key, fetch):
    async def probe(configuration):
        return await openai_model_readiness(configuration, api_key=api_key, fetch=fetch)

    return probe


def build_real_model_runtime(
    path: Path | None,
    *,
    env_file: str | Path | None = ".env",
    anthropic_client_factory: Callable[[str], Any] = create_anthropic_client,
    openai_model_fetch: Callable[..., tuple[int, bytes]] | None = None,
):
    try:
        if path is None:
            raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_REQUIRED")
        raw = _read(path)
        document = strict_json_object(raw)
        if document.get("schema_version") == 2:
            hosted = HostedRealModelConfiguration.model_validate(document)
            _Overrides().validate_against(hosted)
            return _build_hosted_runtime(
                path,
                raw,
                hosted,
                env_file=env_file,
                anthropic_client_factory=anthropic_client_factory,
                openai_model_fetch=openai_model_fetch,
            )
        config = RealModelConfiguration.model_validate(document)
        _Overrides().validate_against(config)
        proposal_raw = _read(config.proposal_config_file)
        generator = build_proposal_generator(config.proposal_config_file)
        proposal = generator.configuration
        if proposal.temperature <= 0 or proposal.identity.adapter_id is not None:
            raise RealModelRuntimeError("SAMPLED_BASE_PROPOSAL_MODEL_REQUIRED")
        token_raw = _read(proposal.token_file, 4096)
        if generator.port._bearer_token != token_raw.decode("ascii"):
            raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
        if _read(config.proposal_config_file) != proposal_raw:
            raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
        sealed_files = [
            (path, raw),
            (config.proposal_config_file, proposal_raw),
            (proposal.token_file, token_raw),
        ]
        final = (
            build_local_evaluator_runtime(config.final_evaluator_config_file)
            if config.final_evaluator_config_file
            else build_final_evaluator_runtime(
                FinalEvaluatorSettings(
                    enabled=True, ready_file=config.final_evaluator_ready_file, _env_file=None
                )
            )
        )
        evaluator_identity = (
            final.identity if config.final_evaluator_config_file else final.session.identity
        )
        evaluator_url = (
            final.base_url if config.final_evaluator_config_file else final.session.base_url
        )
        if (
            proposal.identity.to_snapshot() == evaluator_identity
            or proposal.base_url == evaluator_url
        ):
            raise RealModelRuntimeError("SEPARATE_PROPOSAL_AND_EVALUATOR_IDENTITIES_REQUIRED")
        generation_lock = asyncio.Lock()
        sealed_hashes = tuple(
            (p, hashlib.sha256(content).hexdigest()) for p, content in sealed_files
        )
        generator.port = SerializedGenerationPort(
            _ConfigurationSealedPort(generator.port, sealed_hashes), generation_lock
        )
        final = replace(final, generation_lock=generation_lock)
        return RealModelRuntime(
            proposal,
            final,
            ModelTeamProposalAdapter(generator),
            UserModelingRuntime(
                UserModelingRuntimeMode.MODEL_ADAPTER, ModelUserModelingAdapter(generator)
            ),
            RequirementsRuntime(
                RequirementsRuntimeMode.MODEL_ADAPTER, ModelRequirementsAdapter(generator)
            ),
            DesignRuntime(DesignRuntimeMode.MODEL_ADAPTER, ModelDesignAdapter(generator)),
            sealed_hashes,
            token_raw.decode("ascii"),
        )
    except RealModelRuntimeError:
        raise
    except HostedConfigurationError as error:
        raise RealModelRuntimeError(error.code) from None
    except Exception:
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_INVALID") from None
