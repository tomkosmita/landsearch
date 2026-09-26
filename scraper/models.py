from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    id: str
    title: str
    url: str
    location: str
    source: str
    price: Optional[int] = None
    area: Optional[int] = None
    utilities: dict = field(default_factory=dict)
    property_type: str = "dzialka"  # "dzialka" | "dom"
