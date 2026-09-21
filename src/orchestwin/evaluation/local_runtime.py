"""Explicit, replaceable evaluator configuration for interactive development."""

import asyncio
import hashlib
import http.client
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from orchestwin.evaluation.artifact_content import (
    CONTENT_PROMPT_VERSION,
    artifact_content_instruction,
)
from orchestwin.evaluation.evaluator import UserTwinEvaluatorConfiguration
from orchestwin.evaluation.field_scope_prompt import (
    FIELD_SCOPE_PROMPT_VERSION,
    field_scope_instruction,
)
from orchestwin.evaluation.model_evaluator import (
    ModelGatewayUserTwinEvaluator,
    _output_schema_payload,
    _system_instruction,
)
from orchestwin.models.openai_compatible import (
    OpenAICompatibleLocalConfig,
    OpenAICompatibleLocalStructuredAdapter,
)
from orchestwin.models.proposal_generation import (
    DirectProposalTransport,
    ProposalModelConfiguration,
)
from orchestwin.models.schema_decoding import POLICY as SCHEMA_DECODING_POLICY
from orchestwin.models.serialized_generation import SerializedGenerationPort
from orchestwin.models.strict_evaluator_json import strict_json_object


def _read_configuration(path: Path, maximum: int = 32768) -> bytes:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(part.is_symlink() or part.is_junction() for part in (path, *path.parents))
    ):
        raise ValueError("EVALUATOR_CONFIGURATION_PATH_INVALID")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("EVALUATOR_CONFIGURATION_TOO_LARGE")
    return raw


@dataclass(frozen=True)
class LocalEvaluatorRuntime:
    configuration: ProposalModelConfiguration
    config_file: Path
    config_hash: str
    token: str = field(repr=False)
    generation_lock: asyncio.Lock | None = field(default=None, repr=False, compare=False)

    @property
    def identity(self):
        return self.configuration.identity.to_snapshot()

    @property
    def base_url(self):
        return self.configuration.base_url

    def _verify(self):
        if hashlib.sha256(_read_configuration(self.config_file)).hexdigest() != self.config_hash:
            raise ValueError("EVALUATOR_CONFIGURATION_CHANGED")
        if _read_configuration(self.configuration.token_file, 4096).decode("ascii") != self.token:
            raise ValueError("EVALUATOR_CREDENTIAL_CHANGED")

    def create_evaluator(
        self, *, verified_content=None, generation_port=None, request_id_factory=uuid4, clock=None
    ):
        self._verify()
        config = self.configuration
        port = generation_port or OpenAICompatibleLocalStructuredAdapter(
            config=OpenAICompatibleLocalConfig(
                base_url=config.base_url,
                model_name=config.model_name,
                expected_identity=config.identity,
            ),
            transport=DirectProposalTransport(),
            bearer_token=self.token,
        )
        if self.generation_lock is not None:
            port = SerializedGenerationPort(port, self.generation_lock)
        schema = _output_schema_payload(require_finding_id_pattern=verified_content is not None)
        instruction = field_scope_instruction(_system_instruction(), schema)
        if verified_content is not None:
            instruction = artifact_content_instruction(instruction)
        return ModelGatewayUserTwinEvaluator(
            configuration=UserTwinEvaluatorConfiguration(
                evaluator_id=config.identity.adapter_id,
                evaluator_version="interactive-1",
                model_config_ref=config.identity.content_hash,
                prompt_version_ref=CONTENT_PROMPT_VERSION
                if verified_content
                else FIELD_SCOPE_PROMPT_VERSION,
            ),
            model_identity=config.identity,
            generation_port=port,
            max_output_tokens=config.max_output_tokens,
            timeout_seconds=config.timeout_seconds,
            system_instruction=instruction,
            output_schema_version=2 if verified_content else 1,
            verified_content=verified_content,
            request_id_factory=request_id_factory,
            clock=clock if clock is not None else lambda: datetime.now(UTC),
        )

    async def check_health(self):
        return await asyncio.to_thread(self._health)

    def _health(self):
        self._verify()
        endpoint = urlsplit(self.base_url)
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=10)
        try:
            connection.request("GET", "/health", headers={"Authorization": "Bearer " + self.token})
            response = connection.getresponse()
            raw = response.read(32769)
            if (
                response.status != 200
                or len(raw) > 32768
                or response.getheader("Content-Type", "").split(";", 1)[0] != "application/json"
            ):
                raise ValueError("EVALUATOR_UNAVAILABLE")
            health = strict_json_object(raw)
            if not (
                health.get("status") == "READY"
                and health.get("health_contract_version") == 2
                and health.get("model_name") == self.configuration.model_name
                and health.get("model_identity") == self.identity
                and health.get("adapter_loaded") is True
                and health.get("adapter_active") is True
                and health.get("supported_tasks") == ["user-twin-evaluation"]
                and health.get("schema_decoding") == SCHEMA_DECODING_POLICY
                and type(health.get("max_output_tokens")) is int
                and health["max_output_tokens"] >= self.configuration.max_output_tokens
                and health.get("training_executed") is False
                and health.get("fallback_policy") == "FAIL_CLOSED_NO_FAKE_FALLBACK"
            ):
                raise ValueError("EVALUATOR_IDENTITY_MISMATCH")
            return health
        finally:
            connection.close()


def build_local_evaluator_runtime(path: Path):
    raw = _read_configuration(path)
    config = ProposalModelConfiguration.model_validate(strict_json_object(raw))
    if config.identity.adapter_id is None or config.temperature != 0:
        raise ValueError("EXPLICIT_TRAINED_EVALUATOR_REQUIRED")
    token = _read_configuration(config.token_file, 4096).decode("ascii")
    if not 32 <= len(token) <= 4096 or any(character.isspace() for character in token):
        raise ValueError("EVALUATOR_CREDENTIAL_INVALID")
    return LocalEvaluatorRuntime(config, path, hashlib.sha256(raw).hexdigest(), token)
