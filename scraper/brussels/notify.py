"""Telegram formatting for the Brussels monitor.

Shares only the transport with the plot monitor (notify.send_message); the
wording, units and emoji are their own so the two feeds stay distinguishable
even when they land in the same app.
"""

import logging
from typing import Any, Dict, List, Optional

from scraper.brussels.models import KotListing
from scraper.notify import send_message

logger = logging.getLogger(__name__)

_KIND_HEADER = {
    "kot": "🛏️ Nowy kot",
    "studio": "🏠 Nowe studio",
    "apartment": "🏢 Nowe mieszkanie",
    "unknown": "🆕 Nowa oferta",
}

_KIND_LABEL = {
    "kot": "pokoje",
    "studio": "studia",
    "apartment": "mieszkania",
    "unknown": "inne",
}


def _fmt_price(price: Optional[int]) -> str:
    return f"{price} €/mc" if price is not None else "brak ceny"


def _fmt_rent_line(listing: KotListing) -> str:
    if listing.price is None:
        return "💰 brak ceny"
    if listing.charges:
        return f"💰 {listing.price} €/mc  <i>({listing.rent} + {listing.charges} opłaty)</i>"
    return f"💰 {listing.price} €/mc"


def _fmt_date(value: Optional[str]) -> str:
    return value or "termin nieznany"


def _fmt_surface(surface: Optional[int]) -> str:
    return f"📐 {surface} m²" if surface else "📐 metraż nieznany"


def format_message(
    listing: KotListing,
    changes: Optional[Dict[str, Any]] = None,
) -> str:
    label = listing.portal.replace("_", ".")
    available = listing.available_from.isoformat() if listing.available_from else None

    if changes:
        header = f"🔄 Zmiana oferty — {label}"
        lines = []
        if "price" in changes:
            old, new = changes["price"]
            lines.append(f"💰 {_fmt_price(new)}  <s>{_fmt_price(old)}</s>")
        else:
            lines.append(_fmt_rent_line(listing))
        if "available" in changes:
            old, new = changes["available"]
            lines.append(f"📅 {_fmt_date(new)}  <s>{_fmt_date(old)}</s>")
        else:
            lines.append(f"📅 {_fmt_date(available)}")
        details = "\n".join(lines)
    else:
        header = f"{_KIND_HEADER.get(listing.kind, _KIND_HEADER['unknown'])} — {label}"
        details = f"{_fmt_rent_line(listing)}\n📅 {_fmt_date(available)}"

    location = listing.commune or "lokalizacja nieznana"
    return (
        f"<b>🇧🇪 {header}</b>\n"
        f"{listing.title}\n"
        f"📍 {location}\n"
        f"{details}\n"
        f"{_fmt_surface(listing.surface)}\n\n"
        f'<a href="{listing.url}">Zobacz ofertę ›</a>'
    )


def send_listing(
    listing: KotListing,
    token: str,
    chat_id: str,
    changes: Optional[Dict[str, Any]] = None,
) -> bool:
    return send_message(format_message(listing, changes), token, chat_id)


def send_scan_summary(
    portal_counts: Dict[str, int],
    kept: int,
    sent: int,
    token: str,
    chat_id: str,
    seeded: bool = False,
    deferred: int = 0,
    failed: Optional[List[str]] = None,
) -> None:
    if seeded:
        lines = ["🇧🇪 <b>Bruksela — baza zainicjowana</b>",
                 "Pierwszy skan: zapisuję stan, nie wysyłam pojedynczych ofert."]
    else:
        lines = ["🇧🇪 <b>Bruksela — skan zakończony</b>"]

    for portal, count in sorted(portal_counts.items()):
        mark = "" if count else "  ⚠️"
        lines.append(f"  {portal}: {count}{mark}")

    lines.append(f"🎯 Po filtrach: {kept}")
    lines.append(f"📬 Nowe/zmienione: {sent}")
    if deferred:
        lines.append(f"⏭️ Odłożone na następny skan (limit): {deferred}")
    if failed:
        lines.append(f"❌ Błąd źródła: {', '.join(sorted(failed))}")

    if not send_message("\n".join(lines), token, chat_id):
        logger.warning("Brussels scan summary was not delivered")
