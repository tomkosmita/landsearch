"""Field parsers shared by every Brussels source.

Belgian portals mix English, French and Dutch, and mix European number
formats ("1.250,00 €") with plain ones ("500 EUR"). Everything here returns
None rather than raising: an unparseable field must never drop a listing.
"""

import logging
import re
from datetime import date, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # French
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
    # Dutch
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "juni": 6, "juli": 7,
    "augustus": 8, "oktober": 10,
}

# "available now" in the three languages the portals use
_IMMEDIATE = (
    "immediately", "immediate", "now", "asap", "direct",
    "immediatement", "immédiatement", "tout de suite", "disponible de suite",
    "onmiddellijk", "direct beschikbaar", "nu",
)

_NUM_RE = re.compile(r"\d[\d\s .,]*")
_BRUSSELS_POSTAL_RE = re.compile(r"\b1[0-2]\d{2}\b")


def _to_number(raw: str) -> Optional[float]:
    """Interpret a European or plain number string. '1.250,50' -> 1250.5"""
    s = raw.replace(" ", "").replace(" ", "").strip(" .,")
    if not s:
        return None
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        # whichever separator comes last is the decimal one
        s = (s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".")
             else s.replace(",", ""))
    elif has_comma:
        # a comma followed by exactly 3 digits is a thousands separator
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif has_dot:
        s = s.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", s) else s
    try:
        return float(s)
    except ValueError:
        return None


def parse_eur(text: Optional[str], allow_zero: bool = False) -> Optional[int]:
    """First monetary amount in the text, as whole euros.

    allow_zero matters for charges: portals really do print "Charges: 0 €",
    and that is a known zero, not missing data.
    """
    if not text:
        return None
    m = _NUM_RE.search(text)
    if not m:
        return None
    value = _to_number(m.group(0))
    if value is None or value > 100_000:
        return None
    if value < 0 or (value == 0 and not allow_zero):
        return None
    return int(round(value))


def parse_rent_and_charges(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Pull rent and charges out of a blob like 'Rent: 500 €, Charges: 50 €'."""
    if not text:
        return None, None
    low = text.lower()
    rent = charges = None
    for kw in ("rent", "loyer", "huur", "huurprijs"):
        m = re.search(kw + r"\D{0,15}?(\d[\d\s .,]*)", low)
        if m:
            rent = parse_eur(m.group(1))
            break
    for kw in ("charges", "charge", "kosten", "lasten"):
        m = re.search(kw + r"\D{0,15}?(\d[\d\s .,]*)", low)
        if m:
            charges = parse_eur(m.group(1), allow_zero=True)
            break
    if rent is None:
        rent = parse_eur(text)
    return rent, charges


def total_price(rent: Optional[int], charges: Optional[int]) -> Optional[int]:
    if rent is None:
        return None
    return rent + (charges or 0)


def parse_area(text: Optional[str]) -> Optional[int]:
    """Surface in m²."""
    if not text:
        return None
    m = re.search(r"(\d[\d\s .,]*)\s*(?:m²|m2|sqm|m\b)", text, re.IGNORECASE)
    if not m:
        return None
    value = _to_number(m.group(1))
    if value is None or value <= 0 or value > 1000:
        return None
    return int(round(value))


def parse_commune(text: Optional[str]) -> str:
    return (text or "").strip()


def parse_postal_code(text: Optional[str]) -> Optional[str]:
    """Brussels postal codes run 1000–1210."""
    if not text:
        return None
    m = _BRUSSELS_POSTAL_RE.search(text)
    return m.group(0) if m else None


def _infer_year(month: int, day: int, today: date) -> int:
    """Pick the nearest sensible year for a date given without one."""
    for year in (today.year, today.year + 1):
        try:
            if date(year, month, day) >= today - timedelta(days=30):
                return year
        except ValueError:
            continue
    return today.year + 1


def parse_date(text: Optional[str], today: Optional[date] = None) -> Optional[date]:
    """Availability date from EN/FR/NL text. None when nothing parses."""
    if not text:
        return None
    today = today or date.today()
    low = text.lower().replace(" ", " ").strip()
    if not low:
        return None

    if any(word in low for word in _IMMEDIATE):
        return today

    # ISO: 2026-09-15
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", low)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Day-first numeric: 15/09/2026, 15-09-26, 1.9.2026
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", low)
    if m:
        year = int(m.group(3))
        return _safe_date(year + 2000 if year < 100 else year,
                          int(m.group(2)), int(m.group(1)))

    # Month name with a day: "1st September", "15 septembre 2026"
    months = "|".join(sorted(_MONTHS, key=len, reverse=True))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th|er|e)?\.?\s+(" + months + r")\b"
                  r"(?:\s+(\d{4}))?", low)
    if not m:
        m2 = re.search(r"\b(" + months + r")\s+(\d{1,2})(?:st|nd|rd|th)?"
                       r"(?:,?\s+(\d{4}))?\b", low)
        if m2:
            month, day, year = _MONTHS[m2.group(1)], int(m2.group(2)), m2.group(3)
            return _safe_date(int(year) if year else _infer_year(month, day, today),
                              month, day)
        # Bare month name: "available from September" -> the 1st
        m3 = re.search(r"\b(" + months + r")\b(?:\s+(\d{4}))?", low)
        if m3:
            month, year = _MONTHS[m3.group(1)], m3.group(2)
            return _safe_date(int(year) if year else _infer_year(month, 1, today),
                              month, 1)
        return None

    day, month, year = int(m.group(1)), _MONTHS[m.group(2)], m.group(3)
    return _safe_date(int(year) if year else _infer_year(month, day, today), month, day)


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        if not (2000 <= year <= 2100):
            return None
        return date(year, month, day)
    except ValueError:
        return None


_KIND_PATTERNS = (
    ("studio", r"\bstudio\w*"),
    # Word boundaries matter: a plain "room" substring also sits inside
    # "bedroom", which would misfile every apartment as a shared room.
    ("kot", r"\b(kot|kots|room|rooms|chambre|chambres|kamer|kamers|"
            r"colocation|coloc|shared|cohousing|house-?share)\b"),
    ("apartment", r"\b(apartment|appartement|appartment|flat|flats)\b"),
)


def classify_kind(text: Optional[str]) -> str:
    """Rough kot / studio / apartment classification from the title."""
    low = (text or "").lower()
    for kind, pattern in _KIND_PATTERNS:
        if re.search(pattern, low):
            return kind
    return "unknown"


# The 19 communes of the Brussels-Capital Region, in both official languages,
# plus the postal range 1000-1210 that covers them.
BRUSSELS_COMMUNES = {
    "brussels", "brussel", "bruxelles", "anderlecht", "auderghem", "oudergem",
    "berchem-sainte-agathe", "sint-agatha-berchem", "etterbeek", "evere",
    "forest", "vorst", "ganshoren", "ixelles", "elsene", "jette", "koekelberg",
    "molenbeek-saint-jean", "sint-jans-molenbeek", "molenbeek",
    "saint-gilles", "sint-gillis", "saint-josse-ten-noode", "saint-josse",
    "sint-joost-ten-node", "schaerbeek", "schaarbeek", "uccle", "ukkel",
    "watermael-boitsfort", "watermaal-bosvoorde", "woluwe-saint-lambert",
    "sint-lambrechts-woluwe", "woluwe-saint-pierre", "sint-pieters-woluwe",
    "laeken", "laken", "neder-over-heembeek", "haren",
}

# Other Belgian student cities. Used only to REJECT — never to accept.
_OTHER_BE_CITIES = (
    "leuven", "louvain", "gent", "ghent", "gand", "antwerpen", "antwerp",
    "anvers", "liege", "liège", "luik", "namur", "namen", "charleroi",
    "brugge", "bruges", "hasselt", "mons", "bergen", "kortrijk", "courtrai",
    "louvain-la-neuve", "wavre", "mechelen", "malines", "aalst", "alost",
    "tournai", "doornik", "arlon", "diepenbeek", "geel", "genk",
)


def is_outside_brussels(text: Optional[str]) -> bool:
    """True only when we can positively tell this is NOT Brussels.

    Deliberately asymmetric: unknown or unrecognised locations return False and
    stay in the results. Only a clear signal — a Belgian postal code outside
    1000-1210, or another Belgian student city named without any Brussels
    commune alongside it — rejects a listing.
    """
    if not text:
        return False
    low = text.lower()

    if any(commune in low for commune in BRUSSELS_COMMUNES):
        return False

    m = re.search(r"\b(\d{4})\b", low)
    if m:
        code = int(m.group(1))
        if 1000 <= code <= 1210:
            return False
        if 1000 <= code <= 9999:  # a valid Belgian postal code, but not Brussels
            return True

    return any(city in low for city in _OTHER_BE_CITIES)


def extract_commune(*texts: Optional[str]) -> str:
    """Find a Brussels commune named anywhere in the given texts.

    Several portals never expose the commune as its own field but do name it in
    the title or address line. Longest match wins so "Woluwe-Saint-Pierre" is
    not reported as "Woluwe-Saint-Lambert"'s prefix or as plain "Brussels".
    """
    for text in texts:
        if not text:
            continue
        low = text.lower()
        hits = [c for c in BRUSSELS_COMMUNES if c in low]
        if hits:
            return max(hits, key=len).title()
    return ""
