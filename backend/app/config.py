"""
Application configuration module.

Loads settings from environment variables / .env file using pydantic-settings.
A single cached Settings instance is returned by get_settings() to avoid
re-reading the file on every call.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables.

    All fields can be overridden via the .env file located in the working
    directory or via real environment variables.
    """

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str
    """Async-compatible PostgreSQL URL, e.g. postgresql+asyncpg://..."""

    # ------------------------------------------------------------------ #
    # External APIs
    # ------------------------------------------------------------------ #
    gemini_api_key: str = ""
    """Google Gemini API key.  Leave empty to disable AI parsing."""

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    app_name: str = "PivotMoney Ingestion Engine"
    debug: bool = False

    # ------------------------------------------------------------------ #
    # File handling
    # ------------------------------------------------------------------ #
    upload_dir: str = "./uploads"
    """Directory where uploaded PDF files are persisted."""

    max_file_size_mb: int = 50
    """Maximum allowed upload size in megabytes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def max_file_size_bytes(self) -> int:
        """Return :attr:`max_file_size_mb` converted to bytes."""
        return self.max_file_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Using :func:`functools.lru_cache` ensures the .env file is parsed only
    once per process lifetime.
    """
    return Settings()
