"""Generic CSS-selector-driven source.

With 13 portals, hand-writing 13 near-identical parsers is not maintainable.
This class does the shared work and reads everything portal-specific from
scraper.brussels.config.
"""

import logging
import re
import time
from typing import List, Optional
from urllib.parse import urljoin, urlparse, urlencode, parse_qsl, urlunparse

from bs4 import BeautifulSoup

from scraper.brussels import parsing
from scraper.brussels.config import REQUEST_DELAY_SEC
from scraper.brussels.models import KotListing
from scraper.brussels.sources.base import KotSource
from scraper.http import get_html, make_session

logger = logging.getLogger(__name__)


def add_page_param(url: str, param: str, page: int) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query[param] = str(page)
    return urlunparse(parts._replace(query=urlencode(query)))


class HtmlSource(KotSource):
    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.cfg = cfg
        self.label = cfg.get("label", name)
        self.base = cfg.get("base", "")
        self.session = make_session()

    # -- fetching ---------------------------------------------------------
    def _urls(self) -> List[str]:
        urls = list(self.cfg.get("urls", []))
        pages = self.cfg.get("pages", 1)
        if pages > 1 and urls:
            first = urls[0]
            pattern, param = self.cfg.get("page_pattern"), self.cfg.get("page_param")
            for page in range(2, pages + 1):
                if pattern:
                    urls.append(pattern.format(page=page))
                elif param:
                    urls.append(add_page_param(first, param, page))
        return urls

    def fetch_listings(self) -> List[KotListing]:
        results: List[KotListing] = []
        seen_ids = set()
        # Warm up cookies the way the plot sources do; several portals hand out
        # a session on the homepage before serving search results.
        if self.base:
            get_html(self.session, self.base, retries=1, label=self.label)
            time.sleep(REQUEST_DELAY_SEC)

        urls = self._urls()
        for index, url in enumerate(urls):
            html = get_html(self.session, url, label=self.label)
            time.sleep(REQUEST_DELAY_SEC)
            if html is None:
                logger.warning("%s: no HTML for %s", self.label, url)
                # A portal that fails its first URL is down or blocking us.
                # Retrying every remaining page costs ~40s of backoff each and
                # will not succeed, so give up on this portal now.
                if index == 0:
                    logger.warning("%s: first URL failed, skipping %d remaining URL(s)",
                                   self.label, len(urls) - 1)
                    break
                continue
            for listing in self.parse(html, url):
                if listing.id not in seen_ids:
                    seen_ids.add(listing.id)
                    results.append(listing)
        return results

    # -- parsing ----------------------------------------------------------
    def parse(self, html: str, page_url: str) -> List[KotListing]:
        soup = BeautifulSoup(html, "lxml")
        cards = self._find_cards(soup)
        if not cards:
            logger.warning("%s: no cards matched any candidate selector", self.label)
            return []

        out = []
        for card in cards:
            listing = self._build(card, page_url)
            if listing:
                out.append(listing)
        logger.info("%s: %d cards -> %d listings", self.label, len(cards), len(out))
        return out

    def _find_cards(self, soup) -> list:
        """First candidate selector that yields a plausible number of cards wins."""
        best = []
        for selector in self.cfg.get("card", []):
            try:
                found = soup.select(selector)
            except Exception:
                continue
            # A card must contain a link; a selector matching the whole page body
            # would otherwise "win" with one useless match.
            found = [c for c in found if c.find("a", href=True)]
            if len(found) > len(best):
                best = found
            if len(best) >= 5:
                break
        return best

    def _text(self, card, spec: Optional[dict]) -> Optional[str]:
        if not spec:
            return None
        node = None
        for selector in spec["sel"].split(","):
            node = card.select_one(selector.strip())
            if node is not None:
                break
        if node is None:
            return None
        if spec.get("attr"):
            value = node.get(spec["attr"])
            return value if isinstance(value, str) else None
        return node.get_text(" ", strip=True)

    def _build(self, card, page_url: str) -> Optional[KotListing]:
        try:
            fields = self.cfg.get("fields", {})
            href = self._text(card, fields.get("url"))
            if not href:
                link = card.find("a", href=True)
                href = link["href"] if link else None
            if not href:
                return None
            url = urljoin(page_url, href)

            title = (self._text(card, fields.get("title"))
                     or self._text(card, fields.get("title_fallback"))
                     or card.get_text(" ", strip=True)[:120])

            price_text = self._text(card, fields.get("price"))
            # Fall back to the whole card: many portals put the price in an
            # element whose class name we have not guessed yet.
            rent, charges = parsing.parse_rent_and_charges(
                price_text or card.get_text(" ", strip=True)
            )

            commune = parsing.parse_commune(self._text(card, fields.get("commune")))
            card_text = card.get_text(" ", strip=True)
            if not commune:
                postal = parsing.parse_postal_code(card_text)
                commune = postal or ""

            surface = parsing.parse_area(self._text(card, fields.get("surface")) or card_text)
            available = parsing.parse_date(self._text(card, fields.get("avail")))

            # A portal's own id attribute beats a slug guessed from the URL.
            raw_id = None
            id_attr = self.cfg.get("id_attr")
            if id_attr:
                raw_id = card.get(id_attr)
            # Some portals put a stable id mid-path (kotzoeker:
            # /en/listing/<id>/<slug>), where the last segment is only a slug.
            id_regex = self.cfg.get("id_url_regex")
            if not raw_id and id_regex:
                m = re.search(id_regex, url)
                if m:
                    raw_id = m.group(1)
            return KotListing(
                id=f"{self.name}:{raw_id or self._listing_id(url)}",
                portal=self.name,
                title=title.strip(),
                url=url,
                commune=commune,
                rent=rent,
                charges=charges,
                price=parsing.total_price(rent, charges),
                surface=surface,
                available_from=available,
                kind=parsing.classify_kind(title),
            )
        except Exception as e:
            logger.debug("%s: failed to build listing: %s", self.label, e)
            return None

    @staticmethod
    def _listing_id(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or path or url
