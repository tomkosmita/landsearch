"""Structural reconnaissance for the Brussels portals.

The dev sandbox cannot reach any of these sites, so selectors in config.py are
candidates, not facts. This runs on a GitHub Actions runner (which has open
egress) and prints what each page ACTUALLY looks like, so the real selectors
can be written from the job log.

Reads no secrets. Output is bounded so the log stays readable.

    python -m scraper.brussels.probe [portal,portal,...]
"""

import json
import logging
import re
import sys
import time
from typing import Any, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scraper.brussels.config import REQUEST_DELAY_SEC, SOURCES
from scraper.http import get_html, make_session

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

MAX_SAMPLE_CHARS = 1500
MAX_SAMPLES = 3
MAX_ROBOTS_CHARS = 2000
LISTING_MARKERS = ("price", "priceInfo", "pricing", "rent", "url", "slug", "vipUrl")


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def probe_feeds(session, base: str) -> None:
    """Spec asks us to check for an official feed before scraping at all."""
    hr(f"{base} — robots.txt / feeds")
    robots = get_html(session, base.rstrip("/") + "/robots.txt", retries=1, label="robots")
    if robots and "<html" not in robots[:200].lower():
        print(robots[:MAX_ROBOTS_CHARS])
        if len(robots) > MAX_ROBOTS_CHARS:
            print(f"... [{len(robots) - MAX_ROBOTS_CHARS} more chars]")
    else:
        print("no robots.txt (or an HTML error page was returned)")

    for path in ("/sitemap.xml", "/rss"):
        time.sleep(1)
        body = get_html(session, base.rstrip("/") + path, retries=1, label="feed")
        if body and any(tag in body[:400].lower() for tag in ("<urlset", "<rss", "<feed", "<sitemapindex")):
            print(f"  FEED FOUND: {path}  ({len(body)} chars) "
                  f"-> prefer this over HTML scraping")


def key_paths(obj: Any, prefix: str = "", depth: int = 0, out: List[str] = None) -> List[str]:
    out = out if out is not None else []
    if depth > 2 or len(out) > 60:
        return out
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:25]:
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, list):
                marker = ""
                if v and isinstance(v[0], dict):
                    hits = [m for m in LISTING_MARKERS if m in v[0]]
                    marker = f"  <<< LISTING CANDIDATE, keys={list(v[0])[:12]}" if hits else ""
                out.append(f"    {path}[] len={len(v)}{marker}")
                if v and isinstance(v[0], dict) and depth < 2:
                    key_paths(v[0], path + "[0]", depth + 1, out)
            elif isinstance(v, dict):
                out.append(f"    {path}{{}} keys={list(v)[:10]}")
                key_paths(v, path, depth + 1, out)
    return out


def find_repeated_structures(soup) -> List[tuple]:
    """Find sibling groups that look like a listing grid.

    Portals with obfuscated class names (skot.be ships class="G", class="M")
    defeat guessed selectors, but a results list is still structurally
    obvious: many sibling elements sharing a tag+class, each holding a link.
    """
    from collections import Counter

    counts = Counter()
    for parent in soup.find_all(True):
        children = [c for c in parent.find_all(recursive=False) if c.name]
        if len(children) < 3:
            continue
        groups = Counter()
        for child in children:
            classes = child.get("class") or []
            if not child.find("a", href=True):
                continue
            key = child.name + ("." + ".".join(classes) if classes else "")
            groups[key] += 1
        for key, n in groups.items():
            if n >= 3:
                counts[key] = max(counts[key], n)

    # Prefer groups that actually carry a price — that is what a listing is.
    ranked = []
    for key, n in counts.items():
        try:
            nodes = soup.select(key)
        except Exception:
            continue
        priced = sum(1 for node in nodes[:40]
                     if "€" in node.get_text() or "EUR" in node.get_text())
        ranked.append((key, n, priced))
    ranked.sort(key=lambda t: (t[2] > 0, t[2], t[1]), reverse=True)
    return [(key, n) for key, n, _ in ranked]


def probe_url(session, name: str, cfg: dict, url: str) -> None:
    hr(f"{cfg.get('label', name)} — {url}")
    html = get_html(session, url, label=name)
    if html is None:
        print("FETCH FAILED (see warnings above) — portal likely blocks us or the URL is wrong")
        return
    print(f"fetched {len(html)} chars")

    soup = BeautifulSoup(html, "lxml")
    title = soup.find("title")
    print(f"page <title>: {title.get_text(strip=True)[:120] if title else '(none)'}")

    low = html.lower()
    for flag in ("cloudflare", "just a moment", "captcha", "access denied", "are you human"):
        if flag in low:
            print(f"  !! anti-bot marker in body: {flag!r}")

    print("\n-- <script> tags --")
    scripts = soup.find_all("script")
    print(f"{len(scripts)} script tags")
    for s in scripts:
        body = (s.string or s.get_text() or "").strip()
        sid, stype = s.get("id"), s.get("type")
        if sid or stype in ("application/json", "application/ld+json") or len(body) > 5000:
            print(f"  id={sid!r} type={stype!r} len={len(body)}")
    if re.search(r"window\.__NUXT__\s*=", html):
        print("  window.__NUXT__ present")

    print("\n-- JSON key paths (depth 2) --")
    found_any = False
    for s in scripts:
        body = (s.string or s.get_text() or "").strip()
        if not body or not body.startswith(("{", "[")):
            continue
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        found_any = True
        print(f"  [script id={s.get('id')!r} type={s.get('type')!r}]")
        for line in key_paths(data)[:60]:
            print(line)
    if not found_any:
        print("  no parseable JSON in any script tag")

    print("\n-- candidate CSS selectors --")
    for selector in cfg.get("card", []):
        try:
            hits = [c for c in soup.select(selector) if c.find("a", href=True)]
        except Exception as e:
            print(f"  {selector!r}: bad selector ({e})")
            continue
        if hits:
            print(f"  {selector!r}: {len(hits)} cards with links")

    print("\n-- sample cards --")
    samples = []
    for selector in cfg.get("card", []):
        try:
            hits = [c for c in soup.select(selector) if c.find("a", href=True)]
        except Exception:
            continue
        if len(hits) >= 2:
            samples = hits[:MAX_SAMPLES]
            print(f"(from selector {selector!r})")
            break
    if not samples:
        print("  no candidate selector matched >=2 linked cards")
        print("\n-- repeated structures (auto-detected listing grids) --")
        guesses = find_repeated_structures(soup)
        if guesses:
            for sel, count in guesses[:8]:
                print(f"  {sel!r}: {count} sibling elements with links")
            best_sel, _ = guesses[0]
            example = soup.select(best_sel)
            if example:
                print(f"\n  --- example of {best_sel!r} ---")
                print("  " + str(example[0])[:MAX_SAMPLE_CHARS].replace("\n", "\n  "))
        else:
            print("  none found — the list is probably rendered client-side by JS")
            body_tag = soup.find("body")
            print(str(body_tag)[:MAX_SAMPLE_CHARS] if body_tag else html[:MAX_SAMPLE_CHARS])
    for i, card in enumerate(samples, 1):
        print(f"\n  --- card {i} ---")
        print("  " + str(card)[:MAX_SAMPLE_CHARS].replace("\n", "\n  "))


def main() -> None:
    wanted = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] else list(SOURCES)
    wanted = [w.strip() for w in wanted if w.strip()]
    unknown = [w for w in wanted if w not in SOURCES]
    if unknown:
        print(f"Unknown portals: {unknown}. Known: {list(SOURCES)}")
        sys.exit(1)

    session = make_session()
    bases_done = set()
    for name in wanted:
        cfg = SOURCES[name]
        base = cfg.get("base", "")
        if base and base not in bases_done:
            bases_done.add(base)
            probe_feeds(session, base)
            time.sleep(REQUEST_DELAY_SEC)
        # One URL per portal is enough to learn the structure.
        for url in cfg.get("urls", [])[:1]:
            probe_url(session, name, cfg, url)
            time.sleep(REQUEST_DELAY_SEC)

    hr("PROBE DONE")


if __name__ == "__main__":
    main()
