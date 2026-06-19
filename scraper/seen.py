import json
from pathlib import Path
from typing import Set

SEEN_FILE = Path("data/seen_ids.json")


def load_seen() -> Set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except (json.JSONDecodeError, ValueError):
        return set()


def save_seen(ids: Set[str]) -> None:
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=2))
