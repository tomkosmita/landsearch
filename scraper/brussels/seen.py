"""Persistence for the Brussels monitor.

Reuses scraper.seen (same JSON-dict format, same migration guard) but points
at its own file, so the two monitors can never corrupt each other's state.
"""

from typing import Any, Dict, Optional

from scraper.brussels.config import SEEN_FILE
from scraper.brussels.models import KotListing
from scraper.seen import get_changes as _get_changes
from scraper.seen import load_seen as _load_seen
from scraper.seen import save_seen as _save_seen

Snapshot = Dict[str, Any]

# Availability moves as often as price on student housing, and area does not
# move at all — so this monitor diffs a different pair than the plot one.
TRACKED_FIELDS = ("price", "available")


def load() -> Dict[str, Snapshot]:
    return _load_seen(SEEN_FILE)


def save(seen: Dict[str, Snapshot]) -> None:
    _save_seen(seen, SEEN_FILE)


def make_snapshot(listing: KotListing) -> Snapshot:
    return {
        "price": listing.price,
        "available": listing.available_from.isoformat() if listing.available_from else None,
        "kind": listing.kind,
        "dup": listing.dup_key(),
    }


def get_changes(old: Snapshot, new: Snapshot) -> Dict[str, Any]:
    return _get_changes(old, new, fields=TRACKED_FIELDS)


def known_dup_keys(seen: Dict[str, Snapshot]) -> set:
    """Duplicate keys already notified, for cross-portal de-duplication."""
    return {snap.get("dup") for snap in seen.values() if snap.get("dup")}
