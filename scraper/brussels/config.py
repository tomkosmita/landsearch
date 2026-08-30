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
        # NOTE: the second probe timed out (curl 28) on every request including
        # robots.txt, while the first probe reached it fine — it is throttling
        # the runner IP. Kept enabled: a timeout costs one slow attempt and the
        # fast-fail then skips the portal.
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
        # DISABLED: probe 33284421731 found no repeated server-side structure at
        # all — skot.be renders its results in JS (classes are obfuscated to
        # single letters). Needs a headless browser, which is out of scope here.
        # robots.txt also disallows /json. Re-enable only with Playwright.
        "enabled": False, "kind": "html", "label": "Skot",
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
        # DISABLED: probe 33285029792 checked flat-overview too (the likelier
        # server-rendered page) and still found no repeated structure —
        # __NEXT_DATA__ carries only an empty initialState.api, so listings are
        # fetched client-side. Same situation as Skot: needs a headless browser.
        "enabled": False, "kind": "json", "label": "Kotzoeker",
        "base": "https://www.kotzoeker.be",
        # URLs supplied by the user. Note the city segment is "brussels", not
        # the French "bruxelles" we had guessed. flat-overview is listed first:
        # an overview page is the likelier server-rendered list, while
        # flat-search is the interactive (JS) view.
        "urls": ["https://www.kotzoeker.be/en/flat-overview/brussels",
                 "https://www.kotzoeker.be/en/flat-search/brussels"],
        "pages": 1,
        "json_paths": [["props", "pageProps", "initialState", "api", "listings"],
                       ["props", "pageProps", "initialState", "api", "results"],
                       ["props", "pageProps", "initialState", "api"]],
        "json_fields": {"id": ["id"], "title": ["title"], "url": ["url"],
                        "price": ["price"], "commune": ["city"],
                        "surface": ["surface"]},
        # Detail URLs look like /en/listing/2JWCUkQkkA/studio-a-louer-a-saint-gilles
        # — the id is mid-path, so the trailing slug must not be used as the id.
        "id_url_regex": r"/listing/([^/]+)/",
        # css-* suffixes are emotion hashes that change on every redeploy, so
        # match only the stable chakra-linkbox part.
        "card": ["div.chakra-linkbox"],
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, p.chakra-text"},
            "price": {"sel": "[class*='price']", "parse": "rent_charges"},
            "commune": {"sel": "[class*='location'], [class*='city']"},
            "surface": {"sel": "[class*='surface'], [class*='area']", "parse": "area"},
        },
    },
    "student_be": {
        # robots.txt disallows "/*?" and "*?*", so NO query-string pagination.
        "enabled": True, "kind": "json", "label": "Student.be",
        "base": "https://www.student.be",
        # The user's link was /en/student-rooms/?location=1000,...&radius=6, but
        # robots.txt disallows "/*?" — so we request the bare path (all of
        # Belgium) and drop non-Brussels listings ourselves via is_outside_brussels.
        "urls": ["https://www.student.be/en/student-rooms/",
                 "https://www.student.be/en/brussels/student-rooms/"],
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
        "enabled": True, "kind": "json", "label": "Zimmo",
        "base": "https://www.zimmo.be",
        # Search URL from the user. The base64 `search` blob decodes to
        # {"filter":{"status":{"in":["TO_RENT"]},"placeId":{"in":[1]},
        #  "category":{"in":["APARTMENT","ROOM"]},
        #  "price":{"unknown":true,"range":{"min":300,"max":1000}}}}
        # Session/tracking params (edge_id, ref, newUser) are stripped — they
        # identify a browser session and do not belong in a scheduled job.
        # NOTE: Zimmo answered 403 to every previous request, including its bare
        # homepage, so this is a long shot: the block is on the request, not the
        # path. Kept enabled for one attempt; the fast-fail caps the cost.
        "urls": ["https://www.zimmo.be/nl/zoeken/?search=eyJmaWx0ZXIiOnsic3RhdHVzIjp7ImluIjpbIlRPX1JFTlQiXX0sInBsYWNlSWQiOnsiaW4iOlsxXX0sImNhdGVnb3J5Ijp7ImluIjpbIkFQQVJUTUVOVCIsIlJPT00iXX0sInByaWNlIjp7InVua25vd24iOnRydWUsInJhbmdlIjp7Im1pbiI6MzAwLCJtYXgiOjEwMDB9fX19"],
        "pages": 1,
        "json_paths": [["props", "pageProps", "results"], ["results"], ["listings"]],
        "json_fields": {"id": ["id"], "title": ["title"], "url": ["url"],
                        "price": ["price"], "commune": ["city"],
                        "surface": ["surface"]},
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
        # robots.txt allows this path (it disallows /results-room/* etc.)
        "urls": ["https://www.appartager.be/bruxelles/colocation-bruxelles"],
        "pages": 2, "page_param": "page",
        # Probe found div.listing_item (15 siblings). Note li.with-price ranked
        # higher there but is the "average price per commune" widget, not offers.
        "card": ["div.listing_item"],
        "fields": {
            "url": {"sel": "a[href]", "attr": "href"},
            "title": {"sel": "h2, h3, [class*='title']"},
            "price": {"sel": "span.price, [class*='price']", "parse": "rent_charges"},
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
