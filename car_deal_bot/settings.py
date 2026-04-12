from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the project root (where this package lives),
# not the working directory — so it works no matter where you run from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config_path: Path = Field(default=Path("config.yaml"))
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")


@lru_cache
def get_env() -> EnvSettings:
    return EnvSettings()


def config_file_path() -> Path:
    p = get_env().config_path
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p
