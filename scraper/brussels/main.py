"""Brussels student-housing monitor: fetch -> filter -> dedup -> diff -> notify.

Separate from scraper.main on purpose: its own state file, its own Telegram
channel and its own sources, so a failure on one side cannot touch the other.
"""

import logging
import os
import sys
from typing import Dict, List, Tuple

from scraper.brussels import seen as state
from scraper.brussels.config import (AVAILABLE_FROM, AVAILABLE_TO, MAX_PRICE_EUR,
                                     NOTIFY_CAP_PER_RUN, enabled_sources)
from scraper.brussels.models import KotListing
from scraper.brussels.notify import send_listing, send_scan_summary
from scraper.brussels.sources.html_source import HtmlSource
from scraper.brussels.sources.json_source import JsonSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_SOURCE_CLASSES = {"html": HtmlSource, "json": JsonSource}


def build_sources() -> list:
    sources = []
    for name, cfg in enabled_sources().items():
        cls = _SOURCE_CLASSES.get(cfg.get("kind", "html"))
        if cls is None:
            logger.warning("Unknown source kind %r for %s", cfg.get("kind"), name)
            continue
        sources.append(cls(name, cfg))
    return sources


def passes_filters(listing: KotListing) -> bool:
    """Missing data never rejects a listing — better one alert too many."""
    if listing.price is not None and listing.price > MAX_PRICE_EUR:
        return False
    if listing.available_from is not None and not (
        AVAILABLE_FROM <= listing.available_from <= AVAILABLE_TO
    ):
        return False
    return True


def collect() -> Tuple[List[KotListing], Dict[str, int], List[str]]:
    """Fetch every enabled source. One broken portal never fails the run."""
    listings: List[KotListing] = []
    counts: Dict[str, int] = {}
    failed: List[str] = []

    for source in build_sources():
        logger.info("Fetching from %s", source.label)
        try:
            found = source.fetch_listings()
        except Exception as e:
            logger.error("Error fetching from %s: %s", source.label, e)
            counts[source.label] = 0
            failed.append(source.label)
            continue
        logger.info("%s: fetched %d listings", source.label, len(found))
        counts[source.label] = len(found)
        listings.extend(found)

    return listings, counts, failed


def main() -> None:
    token = os.environ.get("TELEGRAM_BRUSSELS_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_BRUSSELS_CHAT_ID", "")
    dry_run = os.environ.get("BRUSSELS_DRY_RUN", "").lower() in ("1", "true", "yes")

    if not dry_run and (not token or not chat_id):
        logger.error(
            "TELEGRAM_BRUSSELS_BOT_TOKEN and TELEGRAM_BRUSSELS_CHAT_ID must be set"
        )
        sys.exit(1)

    seen = state.load()
    seeding = not seen
    logger.info("Loaded %d seen listings%s", len(seen), " (seeding run)" if seeding else "")

    listings, counts, failed = collect()
    logger.info("Fetched %d listings from %d portals", len(listings), len(counts))

    kept = [l for l in listings if passes_filters(l)]
    logger.info("After filters (<= %d EUR, %s..%s): %d",
                MAX_PRICE_EUR, AVAILABLE_FROM, AVAILABLE_TO, len(kept))

    dup_keys = state.known_dup_keys(seen)
    sent_count = 0
    deferred = 0

    for listing in kept:
        snapshot = state.make_snapshot(listing)

        if listing.id in seen:
            changes = state.get_changes(seen[listing.id], snapshot)
            if not changes:
                continue
            seen[listing.id] = snapshot
            if seeding or dry_run:
                continue
            if sent_count >= NOTIFY_CAP_PER_RUN:
                deferred += 1
                continue
            if send_listing(listing, token, chat_id, changes=changes):
                sent_count += 1
                logger.info("Sent changed listing %s (%s)", listing.id, changes)
            else:
                logger.warning("Failed to send changed listing %s", listing.id)
            continue

        # New listing. The same room is often posted on several portals at once,
        # so skip anything whose conservative duplicate key we already alerted on.
        key = listing.dup_key()
        if key and key in dup_keys:
            logger.info("Skipping cross-portal duplicate %s (%s)", listing.id, key)
            seen[listing.id] = snapshot
            continue

        if seeding or dry_run:
            if not dry_run:
                seen[listing.id] = snapshot
            if key:
                dup_keys.add(key)
            continue

        # Over the cap: deliberately NOT marked seen, so it returns next run
        # instead of being silently dropped.
        if sent_count >= NOTIFY_CAP_PER_RUN:
            deferred += 1
            continue

        seen[listing.id] = snapshot
        if key:
            dup_keys.add(key)
        if send_listing(listing, token, chat_id):
            sent_count += 1
            logger.info("Sent new listing %s: %s", listing.id, listing.title)
        else:
            logger.warning("Failed to send new listing %s", listing.id)

    if dry_run:
        logger.info("DRY RUN — state not saved, nothing sent. "
                    "kept=%d, would-notify<=%d, failed=%s", len(kept),
                    min(len(kept), NOTIFY_CAP_PER_RUN), failed or "none")
        return

    state.save(seen)
    logger.info("Done. Sent %d, deferred %d. Total seen: %d",
                sent_count, deferred, len(seen))

    send_scan_summary(counts, len(kept), sent_count, token, chat_id,
                      seeded=seeding, deferred=deferred, failed=failed)


if __name__ == "__main__":
    main()
