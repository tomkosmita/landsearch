from abc import ABC, abstractmethod
from typing import List

from scraper.brussels.models import KotListing


class KotSource(ABC):
    """Contract for a Brussels housing source.

    Unlike scraper.sources.base.BaseSource, this ABC declares everything the
    orchestrator actually uses — there is no undeclared second method the
    caller relies on.
    """

    name: str
    label: str

    @abstractmethod
    def fetch_listings(self) -> List[KotListing]:
        """Return every listing found. Must not raise for a portal-side failure."""
