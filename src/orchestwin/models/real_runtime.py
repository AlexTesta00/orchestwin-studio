"""Explicit local real-model composition, identity checks and readiness.

This policy configures proposal inference and the separately trained S67 evaluator.
It does not execute cases, start servers, retry calls, or qualify semantic quality.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.client
from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
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
from orchestwin.models.architecture_runtime import ArchitectureRuntime, ArchitectureRuntimeMode
from orchestwin.models.design_runtime import DesignRuntime, DesignRuntimeMode
from orchestwin.models.model_proposals import (
    ModelArchitectureAdapter,
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    ModelTeamProposalAdapter,
    ModelUserModelingAdapter,
)
from orchestwin.models.proposal_generation import (
    ProposalModelConfiguration,
    build_proposal_generator,
)
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.requirements_runtime import RequirementsRuntime, RequirementsRuntimeMode
from orchestwin.models.schema_decoding import POLICY as SCHEMA_DECODING_POLICY
from orchestwin.models.serialized_generation import SerializedGenerationPort
from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.user_modeling_runtime import UserModelingRuntime, UserModelingRuntimeMode

DATABASE_READINESS_TIMEOUT_SECONDS = 10


class RealModelRuntimeError(RuntimeError):
    """Fixed diagnostic codes; credentials and configuration inputs stay private."""


class RealModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    proposal_config_file: Path
    final_evaluator_ready_file: Path

    @model_validator(mode="after")
    def absolute_paths(self):
        if any(
            not path.is_absolute() or ".." in path.parts
            for path in (self.proposal_config_file, self.final_evaluator_ready_file)
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
    architecture_mode: str | None = None
    proposal_model_config_file: Path | None = None
    team_proposal_model_config_file: Path | None = None
    user_modeling_model_config_file: Path | None = None
    requirements_model_config_file: Path | None = None
    design_model_config_file: Path | None = None
    architecture_model_config_file: Path | None = None
    final_evaluator_enabled: bool | None = None
    final_evaluator_ready_file: Path | None = None

    def validate_against(self, config):
        for field_name, value in self:
            if value is None:
                continue
            if field_name == "final_evaluator_enabled":
                valid = value is True
            elif field_name == "final_evaluator_ready_file":
                valid = value == config.final_evaluator_ready_file
            elif field_name.endswith("config_file"):
                valid = value == config.proposal_config_file
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


def _proposal_health(config, token):
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
            and health.get("supported_tasks") == sorted(TASKS)
            and health.get("schema_decoding") == SCHEMA_DECODING_POLICY
            and health.get("schema_decoder_version") == "1.8.0"
            and type(health.get("max_output_tokens")) is int
            and health["max_output_tokens"] >= config.max_output_tokens
            and type(health.get("max_sequence_length")) is int
            and health["max_sequence_length"] > config.max_output_tokens
            and type(health.get("completed_generation_count")) is int
            and health["completed_generation_count"] >= 0
            and health.get("adapter_loaded") is False
            and health.get("training_executed") is False
            and health.get("fallback_policy") == "FAIL_CLOSED_NO_FAKE_FALLBACK"
        ):
            raise RealModelRuntimeError("PROPOSAL_HEALTH_IDENTITY_OR_CAPABILITY_MISMATCH")
        return health
    except (OSError, http.client.HTTPException, ValueError, TypeError):
        raise RealModelRuntimeError("PROPOSAL_HEALTH_UNAVAILABLE") from None
    finally:
        connection.close()


@dataclass(frozen=True)
class RealModelRuntime:
    proposal_configuration: ProposalModelConfiguration
    final_evaluator: FinalEvaluatorRuntime
    team: ModelTeamProposalAdapter
    user_modeling: UserModelingRuntime
    requirements: RequirementsRuntime
    design: DesignRuntime
    architecture: ArchitectureRuntime
    sources: ModelSourceProposalAdapter
    _files: tuple[tuple[Path, str], ...] = field(repr=False)
    _token: str = field(repr=False)

    def _assert_unchanged(self):
        try:
            for path, digest in self._files:
                if hashlib.sha256(_read(path)).hexdigest() != digest:
                    raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_CHANGED")
        except OSError:
            raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_UNAVAILABLE") from None

    async def check_readiness(self, session_factory):
        """Fresh authenticated health and schema checks, without model inference."""
        self._assert_unchanged()
        checks = await asyncio.gather(
            asyncio.to_thread(_proposal_health, self.proposal_configuration, self._token),
            self.final_evaluator.check_health(),
            _check_schema(session_factory),
            return_exceptions=True,
        )
        components = {}
        for name, value in zip(("proposals", "evaluator", "database"), checks, strict=True):
            if isinstance(value, BaseException):
                components[name] = {
                    "ready": False,
                    "code": str(value)
                    if isinstance(value, RealModelRuntimeError)
                    else "MODEL_DEPENDENCY_UNAVAILABLE",
                }
            else:
                components[name] = {"ready": True, "observation": value}
        return {
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


def build_real_model_runtime(path: Path | None):
    try:
        if path is None:
            raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_REQUIRED")
        raw = _read(path)
        config = RealModelConfiguration.model_validate(strict_json_object(raw))
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
        final = build_final_evaluator_runtime(
            FinalEvaluatorSettings(
                enabled=True, ready_file=config.final_evaluator_ready_file, _env_file=None
            )
        )
        if (
            proposal.identity.to_snapshot() == final.session.identity
            or proposal.base_url == final.session.base_url
        ):
            raise RealModelRuntimeError("SEPARATE_PROPOSAL_AND_EVALUATOR_IDENTITIES_REQUIRED")
        generation_lock = asyncio.Lock()
        generator.port = SerializedGenerationPort(generator.port, generation_lock)
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
            ArchitectureRuntime(
                ArchitectureRuntimeMode.MODEL_ADAPTER, ModelArchitectureAdapter(generator)
            ),
            ModelSourceProposalAdapter(generator),
            tuple(
                (p, hashlib.sha256(content).hexdigest())
                for p, content in (
                    (path, raw),
                    (config.proposal_config_file, proposal_raw),
                    (proposal.token_file, token_raw),
                )
            ),
            token_raw.decode("ascii"),
        )
    except RealModelRuntimeError:
        raise
    except Exception:
        raise RealModelRuntimeError("REAL_MODEL_CONFIGURATION_INVALID") from None
