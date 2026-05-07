from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from adfoundry.models import RunMode


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_model: str = Field(
        default="gpt-5.5",
        validation_alias=AliasChoices(
            "ADFOUNDRY_MODEL",
            "OPENAI_MODEL",
            "adfoundry_model",
            "openai_model",
        ),
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENAI_BASE_URL",
            "openai_base_url",
            "OPEAI_BASE_URL",
            "opeai_base_url",
        ),
    )
    openai_timeout_seconds: float = Field(
        default=45.0,
        validation_alias=AliasChoices(
            "OPENAI_TIMEOUT_SECONDS",
            "openai_timeout_seconds",
        ),
    )
    default_run_mode: RunMode = Field(
        default="hybrid",
        validation_alias=AliasChoices("ADFOUNDRY_RUN_MODE", "default_run_mode"),
    )
    output_root: Path = Field(
        default=Path("outputs"),
        validation_alias=AliasChoices("ADFOUNDRY_OUTPUT_ROOT", "output_root"),
    )
    browser_timeout_ms: int = Field(
        default=12000,
        validation_alias=AliasChoices("ADFOUNDRY_BROWSER_TIMEOUT_MS", "browser_timeout_ms"),
    )
    playwright_chromium_executable_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
            "playwright_chromium_executable_path",
        ),
    )

    @field_validator("playwright_chromium_executable_path")
    @classmethod
    def expand_chromium_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return value.expanduser()


@lru_cache
def get_settings() -> Settings:
    return Settings()
