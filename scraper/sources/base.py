from abc import ABC, abstractmethod
from typing import List

from scraper.models import Listing


class BaseSource(ABC):
    @abstractmethod
    def fetch_listings(self) -> List[Listing]:
        ...
