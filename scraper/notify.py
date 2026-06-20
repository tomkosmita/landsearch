import logging
import time
from typing import Dict, Optional, Tuple

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


_SOURCE_LABELS = {
    "olx": "OLX",
    "otodom": "Otodom",
    "licytacje": "⚖️ Licytacja komornicza",
    "bip_wroclaw": "🏛️ Przetarg gminny (Wrocław BIP)",
    "bipwroclaw": "🏛️ Przetarg gminny (Wrocław BIP)",  # fallback when source returns 0 listings
}


def format_message(
    listing: Listing,
    changes: Optional[Dict[str, Tuple[Optional[int], Optional[int]]]] = None,
) -> str:
    source_label = _SOURCE_LABELS.get(listing.source, listing.source.upper())

    if changes:
        header = f"🔄 Zmiana ogłoszenia — {source_label}"
        change_lines = []
        if "price" in changes:
            old, new = changes["price"]
            change_lines.append(f"💰 {_fmt_price(new)}  <s>{_fmt_price(old)}</s>")
        else:
            change_lines.append(f"💰 {_fmt_price(listing.price)}")
        if "area" in changes:
            old, new = changes["area"]
            change_lines.append(f"📐 {_fmt_area(new)}  <s>{_fmt_area(old)}</s>")
        else:
            change_lines.append(f"📐 {_fmt_area(listing.area)}")
        details = "\n".join(change_lines)
    else:
        header = f"🆕 Nowa działka — {source_label}"
        details = f"💰 {_fmt_price(listing.price)}\n📐 {_fmt_area(listing.area)}"

    return (
        f"<b>{header}</b>\n"
        f"📍 {listing.location}\n"
        f"{details}\n"
        f"{_fmt_utilities(listing.utilities)}\n\n"
        f'<a href="{listing.url}">Zobacz ogłoszenie ›</a>'
    )


def send_scan_summary(
    source_counts: Dict[str, int],
    sent_count: int,
    token: str,
    chat_id: str,
) -> None:
    lines = ["🔍 <b>Skan zakończony</b>"]
    for source, count in source_counts.items():
        label = _SOURCE_LABELS.get(source, source)
        lines.append(f"  {label}: {count}")
    lines.append(f"📬 Nowe/zmienione: {sent_count}")
    message = "\n".join(lines)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15,
        )
        if not resp.ok:
            logger.warning("Summary send failed %d: %s", resp.status_code, resp.text[:100])
    except Exception as e:
        logger.warning("Summary request failed: %s", e)


def send_telegram(
    listing: Listing,
    token: str,
    chat_id: str,
    changes: Optional[Dict[str, Tuple[Optional[int], Optional[int]]]] = None,
) -> bool:
    message = format_message(listing, changes)
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
