"""Opt-in application evaluator factory; no model import or inference during construction."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.evaluation.evaluator import UserTwinEvaluatorConfiguration
from orchestwin.evaluation.field_scope_prompt import (
    FIELD_SCOPE_PROMPT_VERSION,
    field_scope_instruction,
)
from orchestwin.evaluation.model_evaluator import ModelGatewayUserTwinEvaluator
from orchestwin.models.final_evaluator_gateway import FinalEvaluatorGenerationPort
from orchestwin.models.final_evaluator_session import (
    FinalEvaluatorSession,
    check_final_health,
    load_final_session,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity


class FinalEvaluatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_FINAL_EVALUATOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )
    enabled: bool = False
    ready_file: Path | None = None

    @model_validator(mode="after")
    def require_ready_file(self):
        if self.enabled and (self.ready_file is None or not self.ready_file.is_absolute()):
            raise ValueError("enabled final evaluator requires one absolute ready-file path")
        return self


@dataclass(frozen=True, slots=True)
class FinalEvaluatorRuntime:
    session: FinalEvaluatorSession

    def create_evaluator(self, *, generation_port=None, request_id_factory=uuid4, clock=None):
        """New evaluator per invocation avoids shared current request and accumulated trace state.

        generation_port injection is for trusted tests/replay, never accepted by an HTTP body.
        """
        from orchestwin.evaluation.model_evaluator import (
            _output_schema_payload,
            _system_instruction,
        )

        identity = ModelRuntimeIdentity(**self.session.identity)
        port = (
            generation_port
            if generation_port is not None
            else FinalEvaluatorGenerationPort(self.session)
        )
        return ModelGatewayUserTwinEvaluator(
            configuration=UserTwinEvaluatorConfiguration(
                evaluator_id="s67-final-user-twin-evaluator",
                evaluator_version="1.0.0",
                model_config_ref=identity.content_hash,
                prompt_version_ref=FIELD_SCOPE_PROMPT_VERSION,
            ),
            model_identity=identity,
            generation_port=port,
            request_id_factory=request_id_factory,
            clock=clock if clock is not None else (lambda: datetime.now(UTC)),
            max_output_tokens=1024,
            timeout_seconds=90,
            system_instruction=field_scope_instruction(
                _system_instruction(), _output_schema_payload()
            ),
        )

    async def check_health(self):
        return await asyncio.to_thread(check_final_health, self.session)


def build_final_evaluator_runtime(configuration: FinalEvaluatorSettings | None = None):
    config = configuration if configuration is not None else FinalEvaluatorSettings()
    if not config.enabled:
        return None
    return FinalEvaluatorRuntime(load_final_session(config.ready_file))
