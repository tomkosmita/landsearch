import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

from curl_cffi import requests
from bs4 import BeautifulSoup

from scraper.models import Listing
from scraper.sources.base import BaseSource

logger = logging.getLogger(__name__)

# URL provided by user — geometry parameter already constrains to western Wrocław area.
# Switched viewType=map → viewType=listing so the page renders listing cards with __NEXT_DATA__.
SEARCH_URL = (
    "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/cala-polska"
    "?ownerTypeSingleSelect=ALL"
    "&viewType=listing"
    "&mapBounds=17.029403425966603%2C51.246682386894%2C16.714491525627942%2C51.01633555581966"
    "&geometry=aecwHgxifBojBmkD%7B%7B%40mlAil%40__%40gXaAaStTeZhiB%7C%40llAgc%40poBo%5B%7CzCyZ%60aAaHnnAjIpoAtt%40lkDxhAttCn%7C%40xw%40vvBcB%7EdA%7D%5ClRuT%7CgBwuDhMmkBha%40yyAzDec%40%7DMkkBso%40a%60Ckw%40igAsWkKqd%40%3F"
    "&by=LATEST"
    "&direction=DESC"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

UTILITY_PATTERNS = {
    "water": ["woda", "wodociąg", "wodociag"],
    "gas": ["gaz"],
    "electricity": ["prąd", "prad", "energia elektryczna", "elektryczn"],
    "sewage": ["kanalizacja"],
}


class OtodomSource(BaseSource):
    def __init__(self) -> None:
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update(HEADERS)
        proxy = os.environ.get("HTTP_PROXY")
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def fetch_listings(self) -> List[Listing]:
        # Otodom uses cookies set on homepage
        self._get_html("https://www.otodom.pl/")

        html = self._get_html(SEARCH_URL)
        if html is None:
            return []

        raw_listings = self._extract_from_next_data(html)
        if not raw_listings:
            logger.warning("No listings extracted from Otodom search page")
            return []

        results: List[Listing] = []
        for raw in raw_listings:
            listing = self._build_listing(raw)
            if listing:
                results.append(listing)

        return results

    def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        delays = [2, 8, 32]
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                logger.warning("Otodom returned %d for %s", resp.status_code, url)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
            except Exception as e:
                logger.warning("Request error for %s: %s", url, e)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
        return None

    def _extract_from_next_data(self, html: str) -> List[dict]:
        """Extract listings from Next.js __NEXT_DATA__ script tag."""
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.warning("__NEXT_DATA__ script tag not found on Otodom page")
            return []

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse __NEXT_DATA__: %s", e)
            return []

        # Otodom structure: pageProps.data.searchAds.items
        try:
            items = (
                data["props"]["pageProps"]["data"]["searchAds"]["items"]
            )
            if isinstance(items, list):
                return items
        except (KeyError, TypeError):
            pass

        # Fallback: recursive search for "items" list containing listing objects
        return self._find_items(data)

    def _find_items(self, obj) -> List[dict]:
        """Recursively find a list that looks like listings."""
        if isinstance(obj, dict):
            if "items" in obj and isinstance(obj["items"], list):
                items = obj["items"]
                if items and isinstance(items[0], dict) and "slug" in items[0]:
                    return items
            for v in obj.values():
                result = self._find_items(v)
                if result:
                    return result
        return []

    def _build_listing(self, raw: dict) -> Optional[Listing]:
        try:
            listing_id = str(raw.get("id", ""))
            if not listing_id:
                return None

            slug = raw.get("slug", "")
            url = f"https://www.otodom.pl/pl/oferta/{slug}" if slug else ""
            if not url:
                url = raw.get("url", "")

            price_data = raw.get("totalPrice") or raw.get("price", {})
            price = None
            if isinstance(price_data, dict):
                price = price_data.get("value")
            elif isinstance(price_data, (int, float)):
                price = int(price_data)

            area = raw.get("areaInSquareMeters") or raw.get("area")
            if area:
                area = int(area)

            location = self._extract_location(raw)
            title = raw.get("title", "Dom / działka na sprzedaż")

            return Listing(
                id=listing_id,
                title=title,
                url=url,
                location=location,
                source="otodom",
                price=int(price) if price else None,
                area=area,
                utilities={},
            )
        except Exception as e:
            logger.debug("Failed to build Otodom listing from %s: %s", raw.get("id"), e)
            return None

    def _extract_location(self, raw: dict) -> str:
        loc = raw.get("location", {})
        if not isinstance(loc, dict):
            return ""
        addr = loc.get("address", {})
        city = addr.get("city", {}).get("name", "") if isinstance(addr.get("city"), dict) else ""
        street = addr.get("street", {}).get("name", "") if isinstance(addr.get("street"), dict) else ""
        parts = [p for p in [city, street] if p]
        return ", ".join(parts)

    def fetch_utilities(self, url: str) -> Dict[str, bool]:
        time.sleep(1)
        html = self._get_html(url)
        if html is None:
            return {}

        soup = BeautifulSoup(html, "lxml")

        # Try __NEXT_DATA__ first (structured, reliable)
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                data = json.loads(script.string)
                ad = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("ad", {})
                )
                # Look in characteristics / features / description
                text = json.dumps(ad, ensure_ascii=False).lower()
                return self._match_utilities(text)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Fallback: plain text search
        page_text = soup.get_text(" ", strip=True).lower()
        return self._match_utilities(page_text)

    def _match_utilities(self, text: str) -> Dict[str, bool]:
        return {
            utility: any(kw in text for kw in keywords)
            for utility, keywords in UTILITY_PATTERNS.items()
        }
