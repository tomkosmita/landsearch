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

SEARCH_URL = (
    "https://www.olx.pl/nieruchomosci/dzialki/sprzedaz/wroclaw/"
    "?search%5Bdistrict_id%5D=393"
    "&search%5Bdist%5D=15"
    "&search%5Bprivate_business%5D=private"
    "&search%5Border%5D=created_at%3Adesc"
    "&search%5Bfilter_float_price%3Ato%5D=500000"
    "&search%5Bfilter_enum_type%5D%5B0%5D=dzialki-budowlane"
    "&search%5Bfilter_float_m%3Afrom%5D=800"
)

OLX_HOME = "https://www.olx.pl/"

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

# Wrocław center — keep only listings west of this longitude
WROCLAW_CENTER_LON = 17.04

UTILITY_PATTERNS = {
    "water": ["woda", "wodociąg", "wodociag", "wodna"],
    "gas": ["gaz"],
    "electricity": ["prąd", "prad", "energia elektryczna", "elektryczn"],
    "sewage": ["kanalizacja"],
}


class OlxSource(BaseSource):
    def __init__(self) -> None:
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update(HEADERS)
        proxy = os.environ.get("HTTP_PROXY")
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def fetch_listings(self) -> List[Listing]:
        html = self._get_html(OLX_HOME)
        if html is None:
            return []

        html = self._get_html(SEARCH_URL)
        if html is None:
            return []

        raw_listings = self._extract_listings_from_html(html)
        if not raw_listings:
            logger.warning("No listings extracted from OLX search page")
            return []

        results: List[Listing] = []
        for raw in raw_listings:
            listing = self._build_listing(raw)
            if listing is None:
                continue
            if not self._is_west_of_wroclaw(raw):
                logger.debug("Skipping eastern listing: %s", listing.location)
                continue
            results.append(listing)

        return results

    def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        delays = [2, 8, 32]
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                logger.warning("OLX returned %d for %s", resp.status_code, url)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
            except Exception as e:
                logger.warning("Request error for %s: %s", url, e)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
        return None

    def _extract_listings_from_html(self, html: str) -> List[dict]:
        # OLX embeds listing data in a <script> tag as JSON
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: look for script with listing JSON (common OLX pattern)
        for script in soup.find_all("script", type="application/json"):
            content = script.string or ""
            if '"ads"' in content or '"listing"' in content:
                try:
                    data = json.loads(content)
                    ads = self._find_ads_in_json(data)
                    if ads:
                        return ads
                except (json.JSONDecodeError, ValueError):
                    pass

        # Strategy 2: window.__STORE__ or similar global
        for script in soup.find_all("script"):
            content = script.string or ""
            match = re.search(r"window\.__STORE__\s*=\s*(\{.+?\})\s*;", content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    ads = self._find_ads_in_json(data)
                    if ads:
                        return ads
                except (json.JSONDecodeError, ValueError):
                    pass

        # Strategy 3: fallback — parse listing cards from HTML directly
        return self._parse_listing_cards(soup)

    def _find_ads_in_json(self, data: dict) -> List[dict]:
        """Recursively search for 'ads' list in nested JSON."""
        if isinstance(data, dict):
            for key in ("ads", "offers", "data"):
                if key in data and isinstance(data[key], list) and data[key]:
                    return data[key]
            for value in data.values():
                result = self._find_ads_in_json(value)
                if result:
                    return result
        return []

    def _parse_listing_cards(self, soup: BeautifulSoup) -> List[dict]:
        """Fallback: extract minimal data from HTML listing cards."""
        listings = []
        for card in soup.select("[data-cy='l-card'], [data-testid='listing-grid-item']"):
            a_tag = card.find("a", href=True)
            if not a_tag:
                continue
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://www.olx.pl" + href

            # Extract ID from URL
            id_match = re.search(r"ID(\w+)\.html", href)
            listing_id = id_match.group(1) if id_match else href.split("/")[-1]

            price_el = card.select_one("[data-testid='ad-price']")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = self._parse_price(price_text)

            title_el = card.select_one("h4, h3, [data-testid='ad-title']")
            title = title_el.get_text(strip=True) if title_el else "Działka"

            location_el = card.select_one("[data-testid='location-date']")
            location = location_el.get_text(strip=True).split("-")[0].strip() if location_el else ""

            listings.append({
                "id": listing_id,
                "title": title,
                "url": href,
                "price": price,
                "location": location,
                "map": None,
            })
        return listings

    def _build_listing(self, raw: dict) -> Optional[Listing]:
        try:
            listing_id = str(raw.get("id", ""))
            if not listing_id:
                return None

            url = raw.get("url", "") or raw.get("url", "")
            if not url.startswith("http"):
                url = "https://www.olx.pl" + url

            price = None
            price_data = raw.get("price", {})
            if isinstance(price_data, dict):
                price = price_data.get("regularPrice", {}).get("value") or price_data.get("value")
            elif isinstance(price_data, (int, float)):
                price = int(price_data)

            title = raw.get("title", "Działka budowlana")
            location = self._extract_location(raw)
            area = self._extract_area(raw)

            return Listing(
                id=listing_id,
                title=title,
                url=url,
                location=location,
                source="olx",
                price=int(price) if price else None,
                area=area,
                utilities={},
            )
        except Exception as e:
            logger.debug("Failed to build listing from %s: %s", raw.get("id"), e)
            return None

    def _extract_location(self, raw: dict) -> str:
        loc = raw.get("location", {})
        if isinstance(loc, dict):
            city = loc.get("city", {})
            if isinstance(city, dict):
                city_name = city.get("name", "")
            else:
                city_name = str(city)
            district = loc.get("district", {})
            district_name = district.get("name", "") if isinstance(district, dict) else ""
            parts = [p for p in [city_name, district_name] if p]
            return ", ".join(parts) or raw.get("location", "")
        return str(loc)

    def _extract_area(self, raw: dict) -> Optional[int]:
        for param in raw.get("params", []):
            if isinstance(param, dict):
                key = param.get("key", "")
                if key in ("m", "area", "powierzchnia"):
                    val = param.get("value", {})
                    if isinstance(val, dict):
                        return int(val.get("key", 0)) or None
                    return int(val) if val else None
        return None

    def _is_west_of_wroclaw(self, raw: dict) -> bool:
        """Return True if listing is west of Wrocław center (or location unknown)."""
        map_data = raw.get("map", {})
        if isinstance(map_data, dict):
            lon = map_data.get("lon") or map_data.get("longitude")
            if lon is not None:
                return float(lon) < WROCLAW_CENTER_LON
        # No coordinates — allow through (better to include than miss)
        return True

    def fetch_utilities(self, url: str) -> Dict[str, bool]:
        time.sleep(1)
        html = self._get_html(url)
        if html is None:
            return {}

        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(" ", strip=True).lower()

        # Also check detail params JSON
        for script in soup.find_all("script", type="application/json"):
            content = (script.string or "").lower()
            if "media" in content or "woda" in content:
                page_text += " " + content

        result = {}
        for utility, keywords in UTILITY_PATTERNS.items():
            result[utility] = any(kw in page_text for kw in keywords)
        return result

    @staticmethod
    def _parse_price(text: str) -> Optional[int]:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
