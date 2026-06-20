import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from curl_cffi import requests

from scraper.models import Listing
from scraper.sources.base import BaseSource

logger = logging.getLogger(__name__)

BASE_URL = "https://bip.um.wroc.pl"
# kind_id=1 = grunty/działki per search form; try search endpoint first,
# then fall back to category listing /3/10 (candidate for grunty, different from /4/10=lokale)
SEARCH_URL = f"{BASE_URL}/przetargi-nieruchomosci/szukaj?kind_id=1&type_id=-1&status=0"
SEARCH_URL_FALLBACK = f"{BASE_URL}/przetargi-nieruchomosci/3/10"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://bip.um.wroc.pl/",
}

# Keywords identifying land plots vs other property types
PLOT_KEYWORDS = [
    "działk", "działek", "grunt", "teren",
    "nieruchomość gruntow", "nieruchomosc gruntow",
    "budowlan", "niezabudowan",
]

# Exclude non-land listings
EXCLUDE_KEYWORDS = [
    "lokal", "mieszkan", "garaż", "garaz", "budynek", "kamienica",
]

UTILITY_PATTERNS = {
    "water": ["woda", "wodociąg", "wodociag", "wodna"],
    "gas": ["gaz"],
    "electricity": ["prąd", "prad", "energia elektryczna", "elektryczn"],
    "sewage": ["kanalizacja"],
}

MAX_PAGES = 5


class BipWroclawSource(BaseSource):
    def __init__(self) -> None:
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update(HEADERS)
        proxy = os.environ.get("HTTP_PROXY")
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def fetch_listings(self) -> List[Listing]:
        results = self._fetch_from_url(SEARCH_URL)
        if not results:
            logger.info("BIP: search URL returned 0 results, trying fallback %s", SEARCH_URL_FALLBACK)
            results = self._fetch_from_url(SEARCH_URL_FALLBACK)
        return results

    def _fetch_from_url(self, start_url: str) -> List[Listing]:
        results: List[Listing] = []
        url = start_url
        for page in range(1, MAX_PAGES + 1):
            html = self._get_html(url)
            if html is None:
                break
            page_listings, next_url = self._parse_page(html)
            results.extend(page_listings)
            logger.debug("BIP page %d: %d plot listings", page, len(page_listings))
            if not next_url:
                break
            url = next_url
            time.sleep(1)
        return results

    def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        delays = [2, 8, 32]
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                logger.warning("bip.um.wroc.pl returned %d for %s", resp.status_code, url)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
            except requests.RequestException as e:
                logger.warning("Request error %s: %s", url, e)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
        return None

    def _parse_page(self, html: str) -> Tuple[List[Listing], Optional[str]]:
        soup = BeautifulSoup(html, "lxml")
        listings: List[Listing] = []

        items = self._find_listing_items(soup)

        for item in items:
            listing = self._parse_item(item)
            if listing and self._is_plot(listing.title):
                listings.append(listing)

        next_url = self._find_next_page(soup)
        return listings, next_url

    # Navigation link texts to exclude (BIP sidebar/header links)
    _NAV_TEXTS = frozenset([
        "instrukcja obsługi", "urząd miejski", "zespół redakcyjny bip",
        "strona główna", "poprzednia", "następna", "bip",
    ])

    def _is_nav_link(self, text: str) -> bool:
        return text.lower().strip() in self._NAV_TEXTS

    def _find_listing_items(self, soup: BeautifulSoup) -> list:
        # BIP renders a calendar view — table rows are date rows, not listing rows.
        # Strategy 1: find links whose text contains tender keywords.
        # Strategy 2: find links to /content/ or /node/ pages, minus known nav links.
        # Strategy 3: log all hrefs for diagnosis.

        seen_hrefs: set = set()

        # Strategy 1: text-based tender keyword matching
        text_matches = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if re.match(r"^\d{1,2}$", text) or len(text) < 8:
                continue
            if self._is_nav_link(text):
                continue
            if not re.search(
                r"przetarg|sprzedaż|sprzedaz|nieruchom|działk|grunt|teren",
                text, re.IGNORECASE,
            ):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            text_matches.append(a.parent if a.parent else a)

        if text_matches:
            logger.info("BIP: found %d tender links (by text)", len(text_matches))
            for c in text_matches[:3]:
                a = c.find("a") or c
                logger.info(
                    "BIP tender: %r -> %s",
                    a.get_text(strip=True)[:60],
                    a.get("href", "")[:80],
                )
            return text_matches

        # Strategy 2: URL pattern, excluding known nav links
        url_matches = []
        seen_hrefs = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if re.match(r"^\d{1,2}$", text) or len(text) < 5:
                continue
            if self._is_nav_link(text):
                continue
            if not re.search(r"/content/|/node/\d+|przetarg", href, re.IGNORECASE):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            url_matches.append(a.parent if a.parent else a)

        if url_matches:
            logger.info("BIP: found %d tender links (by URL)", len(url_matches))
            for c in url_matches[:3]:
                a = c.find("a") or c
                logger.info("BIP URL link: %r -> %s", a.get_text(strip=True)[:60], a.get("href", "")[:80])
            return url_matches

        # Fallback: Drupal view cards
        cards = soup.select("article, .views-row, .node--type-przetarg")
        if cards:
            logger.info("BIP: found %d card items", len(cards))
            return cards

        # Diagnostic: dump all non-trivial hrefs so we can learn the URL pattern
        all_links = [
            (a.get_text(strip=True)[:50], a["href"][:80])
            for a in soup.find_all("a", href=True)
            if a.get_text(strip=True) and not re.match(r"^\d{1,2}$", a.get_text(strip=True))
        ]
        for text, href in all_links[:15]:
            logger.warning("BIP href: %r -> %s", text, href)
        h1 = soup.find("h1")
        logger.warning(
            "BIP: no items found. Page title: %s | H1: %s",
            soup.title.string if soup.title else "N/A",
            h1.get_text(strip=True)[:80] if h1 else "N/A",
        )
        return []

    def _parse_item(self, item) -> Optional[Listing]:
        try:
            # item is the parent container of a tender link (td/div/li/a)
            if item.name == "a":
                link = item
            else:
                link = item.select_one("a[href*='/content/'], a[href*='/node/']")
                if not link:
                    link = item.find("a")
            if not link:
                return None

            href = link.get("href", "")
            url = href if href.startswith("http") else f"{BASE_URL}{href}"

            # Generate a stable ID from URL path
            path = re.sub(r"[^\w]", "_", href.strip("/"))
            listing_id = f"bip_wroclaw_{path[-60:]}"

            title = link.get_text(strip=True) or item.get_text(" ", strip=True)[:120]

            # Extract price from text — "cena wywoławcza: 500 000 zł"
            full_text = item.get_text(" ", strip=True)
            price = self._parse_price(full_text)
            area = self._parse_area(full_text)

            # Location is Wrocław by definition for this BIP
            location = "Wrocław"
            addr_match = re.search(
                r"ul(?:ica)?\.?\s+[A-ZŁŻŹĆĄŚĘÓ][^\d\n]{2,40}\d+",
                full_text,
            )
            if addr_match:
                location = f"Wrocław, {addr_match.group(0).strip()}"

            return Listing(
                id=listing_id,
                title=title,
                url=url,
                location=location,
                source="bip_wroclaw",
                price=price,
                area=area,
                utilities={},
            )
        except Exception as e:
            logger.debug("Failed to parse BIP item: %s", e)
            return None

    def _parse_price(self, text: str) -> Optional[int]:
        # "500 000,00 zł" or "500.000 zł"
        match = re.search(r"([\d\s]{3,})[,\.]\d{2}\s*zł", text)
        if match:
            digits = re.sub(r"\s", "", match.group(1))
            try:
                return int(digits)
            except ValueError:
                pass
        # "500000 zł" (no separator)
        match2 = re.search(r"(\d{5,})\s*zł", text)
        if match2:
            try:
                return int(match2.group(1))
            except ValueError:
                pass
        return None

    def _parse_area(self, text: str) -> Optional[int]:
        ha_match = re.search(r"(\d+)[,\.](\d+)\s*ha", text, re.IGNORECASE)
        if ha_match:
            try:
                return int(float(f"{ha_match.group(1)}.{ha_match.group(2)}") * 10000)
            except ValueError:
                pass
        m2_match = re.search(r"(\d[\d\s]*)\s*m[²2]", text, re.IGNORECASE)
        if m2_match:
            try:
                return int(re.sub(r"\s", "", m2_match.group(1)))
            except ValueError:
                pass
        return None

    def _is_plot(self, title: str) -> bool:
        lower = title.lower()
        if any(kw in lower for kw in EXCLUDE_KEYWORDS):
            return False
        return any(kw in lower for kw in PLOT_KEYWORDS)

    def _find_next_page(self, soup: BeautifulSoup) -> Optional[str]:
        next_link = soup.select_one(
            "a[rel='next'], li.pager__item--next a, .pager-next a"
        )
        if not next_link:
            for a in soup.find_all("a"):
                if "następna" in (a.get_text(strip=True) or "").lower():
                    next_link = a
                    break
        if next_link:
            href = next_link.get("href", "")
            return href if href.startswith("http") else f"{BASE_URL}{href}"
        return None

    def fetch_utilities(self, url: str) -> Dict[str, bool]:
        time.sleep(1)
        html = self._get_html(url)
        if html is None:
            return {}
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True).lower()
        return {
            utility: any(kw in text for kw in keywords)
            for utility, keywords in UTILITY_PATTERNS.items()
        }
