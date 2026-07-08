# Environment and config management
"""
Application configuration loaded from environment variables.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized settings for the application, loaded from a .env file
    or the process environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    GEMINI_API_KEY: str = Field(
        default=...,
        description="API key used to authenticate with Google's Gemini API.",
    )
    BROWSER_HEADLESS: bool = Field(
        default=False,
        description="Whether browser-automation tools should run headless.",
    )


# Singleton instance — import this rather than instantiating Settings() elsewhere.
settings = Settings()