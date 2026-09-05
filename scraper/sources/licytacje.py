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

BASE_URL = "https://licytacje.komornik.pl"
# Filter 28 = "grunty" (land plots) on licytacje.komornik.pl
FILTER_URL = f"{BASE_URL}/Notice/Filter/28"

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
}

# Municipalities and districts in/around western Wrocław
WROCLAW_KEYWORDS = [
    "wrocław", "wroclaw",
    "długołęka", "dlugoleka",
    "kobierzyce",
    "siechnice",
    "czernica",
    "kąty wrocławskie", "katy wroclawskie",
    "miękinia", "miekinia",
    "żórawina", "zorawina",
    "sobótka", "sobotka",
    "jordanów śląski",
    "dolnośląsk", "dolnoslaski",
]

# Locations outside the area of interest — explicitly excluded even if a whitelist keyword matches
EXCLUDE_LOCATIONS = [
    "bielsko", "bielsko-biała", "bielsko biała",
    "cieszyn", "żywiec", "zywiec",
    "czechowice", "andrychów", "andrychow",
    "kęty", "kety", "oświęcim", "oswiecim",
    "tychy", "katowice", "gliwice", "bytom", "zabrze", "rybnik",
    "częstochowa", "czestochowa",
]

UTILITY_PATTERNS = {
    "water": ["woda", "wodociąg", "wodociag", "wodna"],
    "gas": ["gaz"],
    "electricity": ["prąd", "prad", "energia elektryczna", "elektryczn"],
    "sewage": ["kanalizacja"],
}

MAX_PAGES = 10


class LicytacjeSource(BaseSource):
    def __init__(self) -> None:
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update(HEADERS)
        proxy = os.environ.get("HTTP_PROXY")
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def fetch_listings(self) -> List[Listing]:
        results: List[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            url = f"{FILTER_URL}?page={page}&sortOrder=DataLicytacji"
            html = self._get_html(url)
            if html is None:
                break
            page_listings, has_next = self._parse_page(html)
            results.extend(page_listings)
            logger.debug("Page %d: found %d matching listings", page, len(page_listings))
            if not has_next:
                break
            time.sleep(1)
        return results

    def _get_html(self, url: str, retries: int = 3) -> Optional[str]:
        delays = [2, 8, 32]
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                logger.warning("licytacje.komornik.pl %d for %s", resp.status_code, url)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
            except requests.RequestException as e:
                logger.warning("Request error %s: %s", url, e)
                if attempt < retries - 1:
                    time.sleep(delays[attempt])
        return None

    def _parse_page(self, html: str) -> Tuple[List[Listing], bool]:
        soup = BeautifulSoup(html, "lxml")
        listings: List[Listing] = []

        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.select(".notice-item, .listing-item, .auction-item")

        for row in rows:
            listing = self._parse_row(row)
            if listing and self._is_wroclaw_area(listing.location + " " + listing.title):
                listings.append(listing)

        next_btn = soup.select_one(
            "a[rel='next'], li.next:not(.disabled) a, .pagination a[href*='page=']"
        )
        # Also check page number vs total pages
        has_next = next_btn is not None

        return listings, has_next

    def _parse_row(self, row) -> Optional[Listing]:
        try:
            link = row.select_one("a[href*='/Notice/']")
            if not link:
                return None

            href = link.get("href", "")
            url = href if href.startswith("http") else f"{BASE_URL}{href}"

            id_match = re.search(r"/Notice/(?:Details|Index)/(\d+)", url)
            if not id_match:
                return None
            listing_id = f"licytacje_{id_match.group(1)}"

            title = link.get_text(strip=True)
            if not title:
                title = row.get_text(" ", strip=True)[:120]

            cells = row.find_all("td")
            location = ""
            price: Optional[int] = None
            area: Optional[int] = None

            for cell in cells:
                text = cell.get_text(" ", strip=True)
                if re.search(r"\d[\d\s]*[,\.]\d{2}\s*zł", text):
                    price = self._parse_price(text)
                elif re.search(r"\d+[,\.]\d+\s*ha", text, re.IGNORECASE):
                    area = self._parse_area(text)
                elif re.search(r"\d+\s*m[²2]", text, re.IGNORECASE):
                    area = area or self._parse_area(text)

            # Location is usually a dedicated column (city name without digits/dates)
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and not re.search(r"\d{4}[-/]\d{2}|\d+\s*zł|\d+\s*ha", text):
                    if 2 < len(text) < 60:
                        location = text
                        break

            if not location:
                location = title

            # Try to parse area from title if not found in cells
            if area is None:
                area = self._parse_area(title)

            return Listing(
                id=listing_id,
                title=title,
                url=url,
                location=location,
                source="licytacje",
                price=price,
                area=area,
                utilities={},
            )
        except Exception as e:
            logger.debug("Failed to parse row: %s", e)
            return None

    def _parse_price(self, text: str) -> Optional[int]:
        # "100 000,00 zł" or "100.000,00 zł" → 100000
        match = re.search(r"([\d\s]+)[,\.]\d{2}\s*zł", text)
        if match:
            digits = re.sub(r"\s", "", match.group(1))
            try:
                return int(digits)
            except ValueError:
                pass
        return None

    def _parse_area(self, text: str) -> Optional[int]:
        # "0,1234 ha" or "1.2345 ha" → m²
        ha_match = re.search(r"(\d+)[,\.](\d+)\s*ha", text, re.IGNORECASE)
        if ha_match:
            try:
                hectares = float(f"{ha_match.group(1)}.{ha_match.group(2)}")
                return int(hectares * 10000)
            except ValueError:
                pass
        # "1234 m²"
        m2_match = re.search(r"(\d[\d\s]*)\s*m[²2]", text, re.IGNORECASE)
        if m2_match:
            try:
                return int(re.sub(r"\s", "", m2_match.group(1)))
            except ValueError:
                pass
        return None

    def _is_wroclaw_area(self, text: str) -> bool:
        lower = text.lower()
        if any(kw in lower for kw in EXCLUDE_LOCATIONS):
            return False
        return any(kw in lower for kw in WROCLAW_KEYWORDS)

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
