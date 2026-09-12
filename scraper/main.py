import logging
import os
import sys

from scraper.notify import send_scan_summary, send_telegram
from scraper.seen import get_changes, load_seen, make_snapshot, save_seen
from scraper.sources.bip_wroclaw import BipWroclawSource
from scraper.sources.licytacje import LicytacjeSource
from scraper.sources.olx import OlxSource, HOUSE_SEARCH_URL as OLX_HOUSE_URL
from scraper.sources.otodom import OtodomSource, HOUSE_SEARCH_URL as OTODOM_HOUSE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _enrich_from_utilities(listing) -> None:
    """Pull _price/_location/_area inserted by BIP source and apply to listing."""
    u = listing.utilities
    if "_price" in u:
        listing.price = u.pop("_price")
    if "_location" in u:
        listing.location = u.pop("_location")
    if "_area" in u:
        listing.area = u.pop("_area")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)

    seen = load_seen()
    logger.info("Loaded %d seen listing IDs", len(seen))

    sources = [
        OlxSource(),
        OtodomSource(),
        OlxSource(search_url=OLX_HOUSE_URL, property_type="dom", default_title="Dom wolnostojący"),
        OtodomSource(search_url=OTODOM_HOUSE_URL, property_type="dom"),
        LicytacjeSource(),
        BipWroclawSource(),
    ]
    sent_count = 0
    source_counts: dict = {}

    for source in sources:
        logger.info("Fetching from %s", type(source).__name__)
        try:
            listings = source.fetch_listings()
        except Exception as e:
            logger.error("Error fetching from %s: %s", type(source).__name__, e)
            continue

        logger.info("Fetched %d listings", len(listings))
        prop_type = getattr(source, "property_type", "dzialka")
        source_key = listings[0].source if listings else type(source).__name__.lower().replace("source", "")
        source_counts[(source_key, prop_type)] = len(listings)

        for listing in listings:
            snapshot = make_snapshot(listing)

            if listing.id not in seen:
                listing.utilities = source.fetch_utilities(listing.url)
                _enrich_from_utilities(listing)
                snapshot = make_snapshot(listing)  # re-make after enrichment to capture real price/area
                logger.info("Utilities for %s: %s", listing.id, listing.utilities)
                seen[listing.id] = snapshot
                sent = send_telegram(listing, token, chat_id)
                if sent:
                    sent_count += 1
                    logger.info("Sent new listing %s: %s", listing.id, listing.title)
                else:
                    logger.warning("Failed to send new listing %s", listing.id)
            else:
                changes = get_changes(seen[listing.id], snapshot)
                if changes:
                    listing.utilities = source.fetch_utilities(listing.url)
                    _enrich_from_utilities(listing)
                    logger.info("Utilities for %s: %s", listing.id, listing.utilities)
                    seen[listing.id] = snapshot
                    sent = send_telegram(listing, token, chat_id, changes=changes)
                    if sent:
                        sent_count += 1
                        logger.info("Sent modified listing %s (changes: %s)", listing.id, changes)
                    else:
                        logger.warning("Failed to send modified listing %s", listing.id)

    save_seen(seen)
    logger.info("Done. Sent %d notifications. Total seen: %d", sent_count, len(seen))

    send_scan_summary(source_counts, sent_count, token, chat_id)


if __name__ == "__main__":
    main()
