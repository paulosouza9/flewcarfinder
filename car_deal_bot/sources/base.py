from __future__ import annotations

from abc import ABC, abstractmethod

from car_deal_bot.config_loader import AppConfig
from car_deal_bot.models import SearchParams, VehicleListing


class ListingSource(ABC):
    name: str

    @abstractmethod
    def fetch(self, params: SearchParams, app: AppConfig) -> list[VehicleListing]:
        raise NotImplementedError
