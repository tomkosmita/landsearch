import logging
import os
import sys

from scraper.notify import send_telegram
from scraper.seen import load_seen, save_seen
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

    sources = [OlxSource(), OtodomSource()]
    new_count = 0

    for source in sources:
        logger.info("Fetching from %s", type(source).__name__)
        try:
            listings = source.fetch_listings()
        except Exception as e:
            logger.error("Error fetching from %s: %s", type(source).__name__, e)
            continue

        logger.info("Fetched %d listings", len(listings))
        new_listings = [l for l in listings if l.id not in seen]
        logger.info("%d new listings", len(new_listings))

        for listing in new_listings:
            # Fetch utilities for each new listing
            if hasattr(source, "fetch_utilities"):
                listing.utilities = source.fetch_utilities(listing.url)
                logger.info(
                    "Utilities for %s: %s", listing.id, listing.utilities
                )

            seen.add(listing.id)  # always mark seen to avoid infinite retry loops
            sent = send_telegram(listing, token, chat_id)
            if sent:
                new_count += 1
                logger.info("Sent listing %s: %s", listing.id, listing.title)
            else:
                logger.warning("Failed to send listing %s", listing.id)

    save_seen(seen)
    logger.info("Done. Sent %d new listings. Total seen: %d", new_count, len(seen))


if __name__ == "__main__":
    main()
