"""Send the N most recent listings from all sources to Telegram.

Does NOT touch seen_ids.json — purely a read-only snapshot for human review.
"""

import logging
import os
import sys
import time

from curl_cffi import requests as cffi_requests

from scraper.models import Listing
from scraper.sources.olx import OlxSource
from scraper.sources.otodom import OtodomSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

MAX_LISTINGS = 15

_SOURCE_LABELS = {
    "olx": "OLX",
    "otodom": "Otodom",
}


def _fmt_price(price) -> str:
    if price is None:
        return "brak ceny"
    return f"{price:,}".replace(",", " ") + " zł"


def _fmt_area(area) -> str:
    return f"{area} m²" if area else "brak danych"


def _format_message(listing: Listing) -> str:
    label = _SOURCE_LABELS.get(listing.source, listing.source.upper())
    return (
        f"<b>📋 {label}</b>\n"
        f"📍 {listing.location}\n"
        f"💰 {_fmt_price(listing.price)}\n"
        f"📐 {_fmt_area(listing.area)}\n"
        f'<a href="{listing.url}">Zobacz ogłoszenie ›</a>'
    )


def _send(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            resp = cffi_requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.ok:
                return True
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 15)
                logger.warning("Rate limit — sleeping %ds", retry_after)
                time.sleep(retry_after + 1)
                continue
            logger.error("Telegram error %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("Request failed: %s", e)
            return False
    return False


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)

    all_listings: list[Listing] = []
    for source_cls in (OlxSource, OtodomSource):
        source = source_cls()
        name = source_cls.__name__
        try:
            listings = source.fetch_listings()
            logger.info("%s: fetched %d listings", name, len(listings))
            all_listings.extend(listings)
        except Exception as e:
            logger.error("%s fetch failed: %s", name, e)

    to_send = all_listings[:MAX_LISTINGS]
    logger.info("Sending %d most recent listings", len(to_send))

    intro = (
        f"🏡 <b>Najnowsze działki w okolicach Wrocławia</b>\n"
        f"Pokazuję {len(to_send)} ogłoszeń (OLX + Otodom, posortowane od najnowszych)"
    )
    _send(token, chat_id, intro)

    for i, listing in enumerate(to_send):
        time.sleep(0.5)
        msg = _format_message(listing)
        ok = _send(token, chat_id, msg)
        if ok:
            logger.info("Sent %d/%d: %s", i + 1, len(to_send), listing.title)
        else:
            logger.warning("Failed to send listing %s", listing.id)


if __name__ == "__main__":
    main()
