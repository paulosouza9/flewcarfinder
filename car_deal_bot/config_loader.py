from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from car_deal_bot.models import SearchParams
from car_deal_bot.settings import config_file_path


class ScheduleConfig(BaseModel):
    hour: int = 7
    minute: int = 0
    timezone: str = "Europe/Berlin"


class MobileDeSourceConfig(BaseModel):
    enabled: bool = True
    max_pages: int = 5


class AutoscoutSourceConfig(BaseModel):
    enabled: bool = True
    max_pages: int = 5
    country_code: str = "D"


class SourcesConfig(BaseModel):
    mobile_de: MobileDeSourceConfig = Field(default_factory=MobileDeSourceConfig)
    autoscout: AutoscoutSourceConfig = Field(default_factory=AutoscoutSourceConfig)


class RankingConfig(BaseModel):
    top_n: int = 15
    strategy: str = "best_deal"
    min_deal_score: float | None = None
    exclude_keywords: list[str] = []  # extra title keywords to filter out


class TelegramNotifConfig(BaseModel):
    enabled: bool = True


class NotificationConfig(BaseModel):
    telegram: TelegramNotifConfig = Field(default_factory=TelegramNotifConfig)


class AppConfig(BaseModel):
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    search: SearchParams
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Copy config.example.yaml to config.yaml in the project root."
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping at the top level.")
    return data


def load_app_config() -> AppConfig:
    raw = _read_yaml(config_file_path())
    return AppConfig.model_validate(raw)
