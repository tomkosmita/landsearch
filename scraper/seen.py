import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SEEN_FILE = Path("data/seen_ids.json")

Snapshot = Dict[str, Any]  # {price, area}


def load_seen() -> Dict[str, Snapshot]:
    if not SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_FILE.read_text())
        if isinstance(data, list):
            # migrate from old format (plain list of IDs)
            return {id_: {} for id_ in data}
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def save_seen(seen: Dict[str, Snapshot]) -> None:
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2))


def make_snapshot(listing) -> Snapshot:
    return {"price": listing.price, "area": listing.area}


def get_changes(old: Snapshot, new: Snapshot) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """Return {field: (old_value, new_value)} for fields that changed."""
    changes = {}
    for key in ("price", "area"):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val and not (old_val is None and old == {}):
            changes[key] = (old_val, new_val)
    return changes
