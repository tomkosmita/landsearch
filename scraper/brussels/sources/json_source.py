"""Generic source for portals that render an embedded JSON payload.

Immoweb, 2ememain and the aggregators are React/Next.js apps whose pages are a
rendering of an internal JSON API. Reading that payload is both more reliable
and less work than parsing the DOM they produce. Falls back to HtmlSource's
card parsing when no usable JSON turns up.
"""

import json
import logging
import re
from typing import Any, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.brussels import parsing
from scraper.brussels.config import REQUEST_DELAY_SEC
from scraper.brussels.models import KotListing
from scraper.brussels.sources.html_source import HtmlSource
from scraper.http import get_html

logger = logging.getLogger(__name__)

# A listing must look priced. Matching on "url"/"id" alone is not enough:
# student.be ships an `ads` array of ADVERTS carrying exactly those keys, and
# the probe duly mistook them for offers.
_PRICE_MARKERS = ("price", "priceInfo", "pricing", "rent", "rentPrice",
                  "monthlyPrice", "priceCents", "amount")
# Adverts and tracking payloads carry these; never treat such a list as offers.
_NOT_LISTING_MARKERS = ("campaign_name", "iframe_tag", "javascript_tag", "cloudinary_key")


def looks_like_listing(item: dict) -> bool:
    if any(k in item for k in _NOT_LISTING_MARKERS):
        return False
    return any(k in item for k in _PRICE_MARKERS)

# JS assignments that carry a page's data payload. window.classified is what
# Immoweb injects on a listing detail page.
_JS_ASSIGN_RES = (
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\});?\s*</script>", re.DOTALL),
    re.compile(r"window\.classified\s*=\s*(\{.*?\});?\s*</script>", re.DOTALL),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>", re.DOTALL),
)


def iter_json_blobs(html: str):
    """Yield every JSON payload embedded in the page.

    Shared with probe.py so reconnaissance and scraping look at exactly the
    same places — a blob the probe cannot see is one the scraper cannot use.
    """
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script"):
        text = (script.string or script.get_text() or "").strip()
        if not text:
            continue
        script_type = (script.get("type") or "").lower()
        if script.get("id") == "__NEXT_DATA__" or script_type in (
            "application/json", "application/ld+json"
        ):
            try:
                yield json.loads(text), f"script id={script.get('id')!r} type={script_type!r}"
            except (json.JSONDecodeError, ValueError):
                continue
    for regex in _JS_ASSIGN_RES:
        m = regex.search(html)
        if m:
            try:
                yield json.loads(m.group(1)), f"js assignment {regex.pattern[:28]}"
            except (json.JSONDecodeError, ValueError):
                continue


def dig(obj: Any, path: List[str]) -> Any:
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
        if obj is None:
            return None
    return obj


class JsonSource(HtmlSource):
    def parse(self, html: str, page_url: str) -> List[KotListing]:
        raw_items = self._extract_items(html)
        if not raw_items:
            logger.warning("%s: no JSON listings found, falling back to HTML cards",
                           self.label)
            return super().parse(html, page_url)

        out = []
        for raw in raw_items:
            listing = self._build_from_json(raw, page_url)
            if listing:
                out.append(listing)
        logger.info("%s: %d JSON items -> %d listings", self.label, len(raw_items), len(out))
        return out

    # -- JSON discovery ---------------------------------------------------
    def _extract_items(self, html: str) -> List[dict]:
        for blob in self._json_blobs(html):
            for path in self.cfg.get("json_paths", []):
                found = dig(blob, path)
                if isinstance(found, list) and found and isinstance(found[0], dict):
                    return found
            found = self._find_listing_list(blob)
            if found:
                return found
        return []

    def _json_blobs(self, html: str):
        for blob, _origin in iter_json_blobs(html):
            yield blob

    def _find_listing_list(self, obj: Any, depth: int = 0) -> List[dict]:
        """Recursive hunt for a list of listing-shaped dicts."""
        if depth > 8:
            return []
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and looks_like_listing(obj[0]):
                return obj
            for item in obj[:20]:
                found = self._find_listing_list(item, depth + 1)
                if found:
                    return found
        elif isinstance(obj, dict):
            for value in obj.values():
                found = self._find_listing_list(value, depth + 1)
                if found:
                    return found
        return []

    # -- field extraction -------------------------------------------------
    def _build_from_json(self, raw: dict, page_url: str) -> Optional[KotListing]:
        try:
            spec = self.cfg.get("json_fields", {})

            raw_id = dig(raw, spec.get("id", ["id"])) or raw.get("id") or raw.get("slug")
            href = dig(raw, spec.get("url", ["url"])) or raw.get("url") or raw.get("path")
            if not href and raw.get("slug"):
                href = f"/{raw['slug']}"
            if not href:
                return None
            url = urljoin(self.base or page_url, str(href))
            if not raw_id:
                raw_id = self._listing_id(url)

            title = dig(raw, spec.get("title", ["title"])) or raw.get("title") or ""
            title = str(title).strip() or "Ogłoszenie"

            rent = self._price(raw, spec)
            commune = str(dig(raw, spec.get("commune", ["city"])) or "").strip()
            postal = dig(raw, spec.get("postal", ["postalCode"]))
            if not commune and postal:
                commune = str(postal)

            surface = dig(raw, spec.get("surface", ["surface"]))
            surface = int(surface) if isinstance(surface, (int, float)) and 0 < surface < 1000 else None

            available = parsing.parse_date(
                str(dig(raw, spec.get("avail", ["availableFrom"])) or "")
            )

            return KotListing(
                id=f"{self.name}:{raw_id}",
                portal=self.name,
                title=title,
                url=url,
                commune=commune,
                rent=rent,
                charges=None,
                price=rent,
                surface=surface,
                available_from=available,
                kind=parsing.classify_kind(title),
            )
        except Exception as e:
            logger.debug("%s: failed to build JSON listing: %s", self.label, e)
            return None

    @staticmethod
    def _price(raw: dict, spec: dict) -> Optional[int]:
        value = dig(raw, spec.get("price", ["price"]))
        if isinstance(value, dict):
            value = value.get("amount") or value.get("mainValue") or value.get("value")
        if isinstance(value, str):
            return parsing.parse_eur(value)
        if isinstance(value, (int, float)):
            # 2ememain reports cents; anything this large is not a monthly rent.
            if value > 100_000:
                value = value / 100
            return int(value) if 0 < value <= 100_000 else None
        return None
