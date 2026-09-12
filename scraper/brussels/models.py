from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class KotListing:
    """A student room / studio / flat offer in Brussels.

    Deliberately not scraper.models.Listing: that one carries plot-specific
    fields (area, utilities, property_type="dzialka") that mean nothing here.
    """

    id: str  # portal-prefixed, e.g. "brukot:12345" — the plot monitor's flat
    #        namespace is a latent collision bug we do not repeat across 13 portals
    portal: str
    title: str
    url: str
    commune: str = ""  # commune / district, "" when unknown
    rent: Optional[int] = None  # EUR/month, excluding charges
    charges: Optional[int] = None  # EUR/month
    price: Optional[int] = None  # rent + charges, or rent alone when charges unknown
    surface: Optional[int] = None  # m²
    available_from: Optional[date] = None
    kind: str = "unknown"  # "kot" | "studio" | "apartment" | "unknown"

    def dup_key(self) -> Optional[str]:
        """Conservative cross-portal duplicate key.

        Only meaningful when price, commune and surface are all known — a
        partial key would merge genuinely different offers.
        """
        if self.price is None or not self.commune or self.surface is None:
            return None
        return f"{self.price}|{self.commune.strip().lower()}|{self.surface}"
