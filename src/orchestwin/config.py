"""Typed application configuration for the OrchesTwin Studio backend."""

import re
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.sandbox.execution_policy import SandboxResourceLimits


class RuntimeEnvironment(StrEnum):
    """Supported backend runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Log levels accepted by the backend configuration boundary."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_MEBIBYTE = 1024 * 1024
_MAXIMUM_SOURCE_ARCHIVE_UPLOAD_BYTES = 25 * _MEBIBYTE
_IMAGE_REFERENCE_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_RUNNER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_NETWORK_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class ApplicationSettings(BaseSettings):
    """Immutable settings loaded from environment variables or a dotenv file."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    application_name: str = "OrchesTwin Studio API"
    environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    api_prefix: str = "/api/v1"
    cors_allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173",)
    cors_allow_credentials: bool = True

    source_archive_storage_root: Path = Path("var/artifacts/source-archives")
    brownfield_workspace_root: Path = Path("var/artifacts/workspaces")
    sandbox_evidence_storage_root: Path = Path("var/artifacts/sandbox-evidence")
    training_adapter_registry_root: Path = Path("var/artifacts/model-adapters")
    source_archive_maximum_upload_bytes: int = _MAXIMUM_SOURCE_ARCHIVE_UPLOAD_BYTES
    available_execution_runners: tuple[str, ...] = ()
    sandbox_runtime_enabled: bool = False
    sandbox_docker_executable: str = "docker"
    sandbox_approved_images: tuple[str, ...] = ()
    sandbox_controlled_network_name: str | None = None
    sandbox_cpu_count: float = 2.0
    sandbox_memory_mib: int = 4096
    sandbox_pids_limit: int = 256
    sandbox_writable_tmpfs_mib: int = 512

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Normalize and validate the versioned API prefix."""
        normalized = value.strip().rstrip("/")

        if not normalized or not normalized.startswith("/"):
            raise ValueError("api_prefix must be an absolute non-root path")

        return normalized

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Normalize and deduplicate explicit browser origins."""
        normalized = tuple(
            dict.fromkeys(origin.strip().rstrip("/") for origin in value if origin.strip())
        )

        if not normalized:
            raise ValueError("at least one CORS origin is required")

        return normalized

    @field_validator(
        "source_archive_storage_root",
        "brownfield_workspace_root",
        "sandbox_evidence_storage_root",
        "training_adapter_registry_root",
    )
    @classmethod
    def validate_storage_paths(cls, value: Path) -> Path:
        """Reject empty or parent-traversing runtime storage paths."""
        path = Path(value)
        if not str(path).strip() or ".." in path.parts:
            raise ValueError("runtime storage paths must not contain parent traversal")
        return path

    @field_validator("source_archive_maximum_upload_bytes")
    @classmethod
    def validate_source_archive_upload_limit(cls, value: int) -> int:
        """Keep the HTTP upload boundary within the approved ZIP policy."""
        if isinstance(value, bool) or not 1 <= value <= _MAXIMUM_SOURCE_ARCHIVE_UPLOAD_BYTES:
            raise ValueError("source archive upload limit must be from 1 byte to 25 MiB")
        return value

    @field_validator("available_execution_runners")
    @classmethod
    def validate_execution_runners(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require a canonical set of portable runner identifiers."""
        if value != tuple(sorted(set(value))):
            raise ValueError("execution runners must be canonical and unique")
        if any(_RUNNER_PATTERN.fullmatch(item) is None for item in value):
            raise ValueError("execution runner identifiers must be portable")
        return value

    @field_validator("sandbox_approved_images")
    @classmethod
    def validate_sandbox_images(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Accept only canonical digest-pinned container image references."""
        if value != tuple(sorted(set(value))):
            raise ValueError("sandbox approved images must be canonical and unique")
        if any(_IMAGE_REFERENCE_PATTERN.fullmatch(item) is None for item in value):
            raise ValueError("sandbox approved images must be pinned by SHA-256 digest")
        return value

    @field_validator("sandbox_docker_executable")
    @classmethod
    def validate_docker_executable(cls, value: str) -> str:
        """Keep the host executable explicit without accepting control characters."""
        normalized = value.strip()
        if not normalized or any(character in normalized for character in ("\x00", "\r", "\n")):
            raise ValueError("sandbox Docker executable must be normalized")
        return normalized

    @field_validator("sandbox_controlled_network_name")
    @classmethod
    def validate_controlled_network(cls, value: str | None) -> str | None:
        """Allow only an explicit custom Docker network name."""
        if value is None:
            return None
        normalized = value.strip()
        if _NETWORK_PATTERN.fullmatch(normalized) is None or normalized.casefold() in {
            "bridge",
            "host",
            "none",
        }:
            raise ValueError("controlled network must be an explicit custom name")
        return normalized

    @field_validator(
        "sandbox_memory_mib",
        "sandbox_pids_limit",
        "sandbox_writable_tmpfs_mib",
    )
    @classmethod
    def validate_sandbox_integer_limits(cls, value: int) -> int:
        """Require positive least-privilege integer limits."""
        if isinstance(value, bool) or value < 1:
            raise ValueError("sandbox integer limits must be positive")
        return value

    @field_validator("sandbox_cpu_count")
    @classmethod
    def validate_sandbox_cpu_count(cls, value: float) -> float:
        """Require a positive finite CPU limit."""
        if isinstance(value, bool) or value <= 0 or value != value or value == float("inf"):
            raise ValueError("sandbox CPU limit must be positive and finite")
        return value

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        """Reject unsafe production and CORS combinations."""
        if self.environment is RuntimeEnvironment.PRODUCTION and self.debug:
            raise ValueError("debug must be disabled in production")

        if self.cors_allow_credentials and "*" in self.cors_allowed_origins:
            raise ValueError("credentialed CORS must not use a wildcard origin")

        storage_paths = {
            self.source_archive_storage_root.absolute(),
            self.brownfield_workspace_root.absolute(),
            self.sandbox_evidence_storage_root.absolute(),
            self.training_adapter_registry_root.absolute(),
        }
        if len(storage_paths) != 4:
            raise ValueError("archive, workspace, evidence, and adapter roots must be distinct")

        return self

    @property
    def sandbox_resource_limits(self) -> SandboxResourceLimits:
        """Return the immutable runtime limits shared with classification policy."""
        return SandboxResourceLimits(
            cpu_count=self.sandbox_cpu_count,
            memory_mib=self.sandbox_memory_mib,
            pids_limit=self.sandbox_pids_limit,
            writable_tmpfs_mib=self.sandbox_writable_tmpfs_mib,
        )


def load_settings(
    *,
    env_file: str | Path | None = ".env",
) -> ApplicationSettings:
    """Load a fresh immutable settings object."""
    return ApplicationSettings(_env_file=env_file)
