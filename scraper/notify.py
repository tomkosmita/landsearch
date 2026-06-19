import logging
import time
from typing import Optional

from curl_cffi import requests

from scraper.models import Listing

logger = logging.getLogger(__name__)

YES = "✅"
NO = "❌"


def _fmt_price(price: Optional[int]) -> str:
    if price is None:
        return "brak ceny"
    return f"{price:,}".replace(",", " ") + " zł"


def _fmt_area(area: Optional[int]) -> str:
    return f"{area} m²" if area else "brak danych"


def _fmt_utilities(u: dict) -> str:
    if not u:
        return "brak danych o mediach"
    return (
        f"💧 Woda: {YES if u.get('water') else NO}  "
        f"⛽ Gaz: {YES if u.get('gas') else NO}  "
        f"⚡ Prąd: {YES if u.get('electricity') else NO}  "
        f"🚿 Kanalizacja: {YES if u.get('sewage') else NO}"
    )


def format_message(listing: Listing) -> str:
    source_label = listing.source.upper()
    return (
        f"<b>Nowa działka — {source_label}</b>\n"
        f"📍 {listing.location}\n"
        f"💰 {_fmt_price(listing.price)}\n"
        f"📐 {_fmt_area(listing.area)}\n"
        f"{_fmt_utilities(listing.utilities)}\n\n"
        f'<a href="{listing.url}">Zobacz ogłoszenie ›</a>'
    )


def send_telegram(listing: Listing, token: str, chat_id: str) -> bool:
    message = format_message(listing)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.ok:
                return True
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 15)
                logger.warning("Telegram rate limit, sleeping %ds", retry_after)
                time.sleep(retry_after + 1)
                continue
            logger.error("Telegram error %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("Telegram request failed: %s", e)
            return False
    return False
