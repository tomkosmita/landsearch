"""Configuration for the Brussels student-housing monitor.

The original spec asked for a config.yaml so selectors are easy to fix after a
site redesign. This repo has no YAML dependency and uses Python constants
everywhere, so the same job is done here — same benefit, no new dependency.

Selector values are CANDIDATE LISTS: the sandbox cannot reach any of these
portals, so `python -m scraper.brussels.probe` runs on a GitHub Actions runner
and reports which candidate actually matches. Until a portal has been probed,
treat its selectors as guesses.
"""

from datetime import date
from pathlib import Path

SEEN_FILE = Path("data/brussels_seen.json")

# --- filters -------------------------------------------------------------
# Guiding rule everywhere downstream: missing data NEVER rejects a listing.
# One notification too many beats a missed room.
MAX_PRICE_EUR = 700          # rent + charges
AVAILABLE_FROM = date(2026, 8, 1)   # window is wider than "Sept-Oct" on purpose,
AVAILABLE_TO = date(2026, 11, 30)   # so edge cases are not cut off

# KU Leuven Brussels / Odisee / EhB — city-centre communes
TARGET_POSTAL_CODES = ["1000", "1030", "1040", "1050", "1060", "1080", "1210"]

REQUEST_DELAY_SEC = 3        # polite gap between requests to one portal
NOTIFY_CAP_PER_RUN = 30      # overflow is left unseen so it returns next run

# --- sources -------------------------------------------------------------
# kind: "html"  -> sources.html_source.HtmlSource  (CSS-selector driven)
#       "json"  -> sources.json_source.JsonSource  (embedded JSON / internal API)
# Each entry may be disabled with enabled=False when a portal breaks — no code
# change needed, which matters a lot with 13 of them.

_CARD_CANDIDATES = [
    "article", "li.listing", "div.listing", "div.listing-card", "div.card",
    "[class*='listing-item']", "[class*='property-card']", "[class*='result-item']",
    "[data-testid*='card']", "[class*='kot-card']", "[class*='room-card']",
]

SOURCES = {
    # ---------------- core ----------------
    "brukot": {
        "enabled": True,
        "kind": "html",
        "label": "Brukot",
        "base": "https://www.brukot.be",
        # /en/new is a purpose-built newest-first feed — ideal for a monitor.
        "urls": [
            "https://www.brukot.be/en/new",
            "https://www.brukot.be/en/updated",
            "https://www.brukot.be/en/search",
        ],
        "pages": 2,
        "page_pattern": "https://www.brukot.be/en/search/{page}",
        # Confirmed by probe run 33283870881 (24 cards matched).
        "card": ["article.listing-teaser", "article"],
        "id_attr": "data-listing-id",
        "fields": {
            "url": {"sel": "a.link-to-detail", "attr": "href"},
            # The <img alt> carries the full description ("Student room 16 m² in
            # Brussels Woluwe-Saint-Pierre"); the <h2> only carries the type.
            "title": {"sel": "img.listing-teaser-picture-image", "attr": "alt"},
            "title_fallback": {"sel": "h2.listing-teaser-type"},
            # Brukot prints rent EXCLUDING charges, so charges stay unknown and
            # price == rent. A 700 EUR hit may really cost more once charges land.
            "price": {"sel": "span.listing-rent--rent-wo-charges", "parse": "rent_charges"},
            "commune": {"sel": "h3.listing-teaser-neighborhood"},
            "avail": {"sel": "li.listing-tag-available", "parse": "date"},
            "surface": {"sel": "span.lm-surface", "parse": "area"},
        },
    },
    "immoweb": {
        "enabled": True,
        "kind": "json",
        "label": "Immoweb",
        "base": "https://www.immoweb.be",
        "urls": [
            "https://www.immoweb.be/en/search/kot/for-rent/brussels/district"
            "?countries=BE&maxPrice=700&priceType=MONTHLY_RENTAL_PRICE&orderBy=newest",
            "https://www.immoweb.be/en/search/kot/for-rent/brussels/province"
            "?countries=BE&maxPrice=700&priceType=MONTHLY_RENTAL_PRICE&orderBy=newest",
        ],
        "pages": 2,
        "page_param": "page",
        # Immoweb renders an internal JSON API; probe reports the real key path.
        "json_paths": [
            ["props", "pageProps", "results"],
            ["results"],
            ["data", "results"],
        ],
        "json_fields": {
            "id": ["id"],
            "title": ["property", "type"],
            "url": ["url"],
            "price": ["price", "mainValue"],
            "commune": ["property", "location", "locality"],
            "postal": ["property", "location", "postalCode"],
            "surface": ["property", "netHabitableSurface"],
        },
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='locality']"},
        },
    },

    # ---------------- kot-specific, no login ----------------
    "kotplace": {
        "enabled": True, "kind": "html", "label": "Kotplace",
        "base": "https://kotplace.be",
        # Real listing path supplied by the user. Their link carried
        # ?prix_max=1000, but robots.txt disallows "/*?*prix_max=" — so we
        # request the bare path (allowed) and apply the price cap ourselves,
        # which yields the same result without ignoring the site's rules.
        "urls": ["https://kotplace.be/en/ads/brussels"],
        "pages": 1,
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "avail": {"sel": "[class*='avail'], [class*='date']", "parse": "date"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "skot": {
        "enabled": True, "kind": "html", "label": "Skot",
        "base": "https://skot.be",
        "urls": ["https://skot.be/kot-brussels"],
        "pages": 2, "page_param": "page",
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "avail": {"sel": "[class*='avail'], [class*='date']", "parse": "date"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "kotzoeker": {
        "enabled": True, "kind": "html", "label": "Kotzoeker",
        "base": "https://www.kotzoeker.be",
        "urls": ["https://www.kotzoeker.be/en/flat-search/bruxelles"],
        "pages": 2, "page_param": "page",
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "avail": {"sel": "[class*='avail'], [class*='date']", "parse": "date"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "student_be": {
        # robots.txt disallows "/*?" and "*?*", so NO query-string pagination.
        "enabled": True, "kind": "json", "label": "Student.be",
        "base": "https://www.student.be",
        "urls": ["https://www.student.be/en/brussels/student-rooms/"],
        "pages": 1,
        # React-on-Rails: the page data sits in a script tagged with the
        # component name. `ads` in the same payload is ADVERTISING, not offers.
        "json_paths": [["kots"], ["listings"], ["props", "kots"]],
        "json_fields": {"id": ["id"], "title": ["title"], "url": ["url"],
                        "price": ["price"], "commune": ["city"],
                        "surface": ["surface"], "avail": ["available_at"]},
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
        },
    },

    # ---------------- general classifieds ----------------
    "2ememain": {
        "enabled": True, "kind": "json", "label": "2ememain",
        "base": "https://www.2ememain.be",
        "urls": ["https://www.2ememain.be/l/immo/chambres-etudiantes/"],
        "pages": 2, "page_param": "page",
        "json_paths": [["props", "pageProps", "searchRequestAndResponse", "listings"],
                       ["listings"], ["searchRequestAndResponse", "listings"]],
        "json_fields": {"id": ["itemId"], "title": ["title"], "url": ["vipUrl"],
                        "price": ["priceInfo", "priceCents"],
                        "commune": ["location", "cityName"]},
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city']"},
        },
    },
    "immovlan": {
        "enabled": True, "kind": "html", "label": "Immovlan",
        "base": "https://www.immovlan.be",
        "urls": ["https://www.immovlan.be/en/real-estate?transactiontypes=for-rent"
                 "&propertytypes=student-accommodation&towns=brussels"],
        "pages": 2, "page_param": "page",
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "zimmo": {
        "enabled": True, "kind": "html", "label": "Zimmo",
        "base": "https://www.zimmo.be",
        "urls": ["https://www.zimmo.be/en/brussel-1000/for-rent/student-housing/"],
        "pages": 2, "page_param": "p",
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "appartager": {
        "enabled": True, "kind": "html", "label": "Appartager",
        "base": "https://www.appartager.be",
        "urls": ["https://www.appartager.be/bruxelles/colocation-bruxelles"],
        "pages": 2, "page_param": "page",
        "card": _CARD_CANDIDATES,
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city'], [class*='address']"},
            "avail": {"sel": "[class*='avail'], [class*='date']", "parse": "date"},
        },
    },

    # ---------------- aggregators (React apps, internal JSON APIs) ----------
    "housinganywhere": {
        "enabled": True, "kind": "json", "label": "HousingAnywhere",
        "base": "https://housinganywhere.com",
        "urls": ["https://housinganywhere.com/s/Brussels--Belgium/student-accommodation"],
        "pages": 2, "page_param": "page",
        "json_paths": [["props", "pageProps", "listings"], ["listings"], ["results"]],
        "json_fields": {"id": ["id"], "title": ["typeLabel"], "url": ["path"],
                        "price": ["price", "amount"], "commune": ["city"]},
        "card": _CARD_CANDIDATES,
        "fields": {"url": {"sel": "a[href]", "attr": "href"},
                   "title": {"sel": "h2, h3, [class*='title']"},
                   "price": {"sel": "[class*='price']", "parse": "rent_charges"},
                   "commune": {"sel": "[class*='location'], [class*='city']"}},
    },
    "spotahome": {
        "enabled": True, "kind": "json", "label": "Spotahome",
        "base": "https://www.spotahome.com",
        "urls": ["https://www.spotahome.com/for-rent/brussels/student-apartments"],
        "pages": 2, "page_param": "page",
        "json_paths": [["props", "pageProps", "listings"], ["listings"], ["results"]],
        "json_fields": {"id": ["id"], "title": ["title"], "url": ["url"],
                        "price": ["pricing", "amount"], "commune": ["city"]},
        "card": _CARD_CANDIDATES,
        "fields": {"url": {"sel": "a[href]", "attr": "href"},
                   "title": {"sel": "h2, h3, [class*='title']"},
                   "price": {"sel": "[class*='price']", "parse": "rent_charges"},
                   "commune": {"sel": "[class*='location'], [class*='city']"}},
    },
    "erasmusplay": {
        "enabled": True, "kind": "json", "label": "Erasmus Play",
        "base": "https://erasmusplay.com",
        "urls": ["https://erasmusplay.com/en/bruxelles-brussel.html"],
        "pages": 2, "page_param": "page",
        "json_paths": [["props", "pageProps", "accommodations"], ["accommodations"],
                       ["results"], ["listings"]],
        "json_fields": {"id": ["id"], "title": ["title"], "url": ["url"],
                        "price": ["price"], "commune": ["city"]},
        "card": _CARD_CANDIDATES,
        "fields": {"url": {"sel": "a[href]", "attr": "href"},
                   "title": {"sel": "h2, h3, [class*='title']"},
                   "price": {"sel": "[class*='price']", "parse": "rent_charges"},
                   "commune": {"sel": "[class*='location'], [class*='city']"}},
    },
}


def enabled_sources() -> dict:
    return {name: cfg for name, cfg in SOURCES.items() if cfg.get("enabled")}
