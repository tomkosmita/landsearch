import logging
import os
import sys

from scraper.notify import send_telegram
from scraper.seen import get_changes, load_seen, make_snapshot, save_seen
from scraper.sources.bip_wroclaw import BipWroclawSource
from scraper.sources.licytacje import LicytacjeSource
from scraper.sources.olx import OlxSource
from scraper.sources.otodom import OtodomSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)

    seen = load_seen()
    logger.info("Loaded %d seen listing IDs", len(seen))

    sources = [OlxSource(), OtodomSource(), LicytacjeSource(), BipWroclawSource()]
    sent_count = 0

    for source in sources:
        logger.info("Fetching from %s", type(source).__name__)
        try:
            listings = source.fetch_listings()
        except Exception as e:
            logger.error("Error fetching from %s: %s", type(source).__name__, e)
            continue

        logger.info("Fetched %d listings", len(listings))

        for listing in listings:
            snapshot = make_snapshot(listing)

            if listing.id not in seen:
                listing.utilities = source.fetch_utilities(listing.url)
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


if __name__ == "__main__":
    main()
