"""Parsers against markup captured verbatim from probe logs.

These assert field VALUES, not just "it did not crash". A parser that matches
elements but extracts nothing looks fine in a listing count — that is exactly
the failure that shipped Immoweb with 67 of 69 listings priceless.
"""

import json
import unittest

from scraper.brussels.config import SOURCES
from scraper.brussels.sources.html_source import HtmlSource, add_page_param
from scraper.brussels.sources.json_source import JsonSource, iter_json_blobs

# --- fixtures, shapes taken from live probe output -------------------------

BRUKOT_CARD = """<article class="listing-teaser" data-listing-id="{lid}">
<a class="link-to-detail" href="{href}">
<img alt="{alt}" class="listing-teaser-picture-image"/></a>
<h2 class="listing-teaser-type"><a class="link-to-detail" href="{href}">{typ}</a>
<span class="lm-surface ltm-surface">{m2} m²</span></h2>
<h3 class="listing-teaser-neighborhood">{hood}</h3>
<p class="listing-teaser-rent"><span class="listing-rent--rent-wo-charges">{rent} €</span>
<span class="listing-rent--charges-qualifier">excl. charges</span></p>
<ul><li class="listing-tag-available">{avail}</li></ul></article>"""

IMMOWEB_CARD = """<article class="card card--result card--large" id="classified_{cid}">
<h2 class="card__title"><a aria-label="Kot to rent, {commune} ({label})"
 class="card__title-link"
 href="https://www.immoweb.be/en/classified/kot/for-rent/{slug}/{pc}/{cid}">Kot</a></h2>
<p class="card--result__price"><iw-price :price='{price}'></iw-price></p></article>"""

IMMOVLAN_CARD = """<article class="list-view-item mb-3 card card-border"
 data-url="https://immovlan.be/en/detail/{t}/for-rent/{pc}/brussels/{vid}">
<a href="https://immovlan.be/en/detail/{t}/for-rent/{pc}/brussels/{vid}"></a>
<strong class="list-item-price">{price} €</strong>
<h2 class="card-title" itemprop="name">{T} for rent Brussels</h2></article>"""


def page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


class TestBrukot(unittest.TestCase):
    def parse(self):
        html = page(
            BRUKOT_CARD.format(lid="42911", href="/en/BK/18821", typ="Shared housing",
                               alt="Shared housing 100 m² in Brussels Anderlecht",
                               m2="100", hood="Anderlecht", rent="560", avail="1st September"),
            BRUKOT_CARD.format(lid="48673", href="/en/BK/21122", typ="Student room",
                               alt="Student room 16 m² in Brussels Ixelles",
                               m2="16", hood="Ixelles", rent="500", avail="15/09/2026"),
        )
        return HtmlSource("brukot", SOURCES["brukot"]).parse(html, "https://www.brukot.be/en/new")

    def test_all_fields(self):
        a, b = self.parse()
        self.assertEqual(a.id, "brukot:42911")        # portal's own id, not a slug
        self.assertEqual(a.url, "https://www.brukot.be/en/BK/18821")
        self.assertEqual(a.commune, "Anderlecht")
        self.assertEqual(a.surface, 100)
        self.assertEqual(a.price, 560)
        self.assertEqual(str(a.available_from), "2026-09-01")
        self.assertEqual(b.id, "brukot:48673")
        self.assertEqual(str(b.available_from), "2026-09-15")

    def test_excl_charges_leaves_charges_unknown(self):
        for listing in self.parse():
            self.assertIsNone(listing.charges)
            self.assertEqual(listing.price, listing.rent)

    def test_every_listing_is_priced(self):
        self.assertTrue(all(l.price is not None for l in self.parse()))


class TestImmoweb(unittest.TestCase):
    def parse(self):
        def card(cid, commune, pc, rent, charges):
            price = json.dumps({"mainValue": rent, "additionalValue": charges})
            label = f"{rent} €" if charges is None else f"{rent} € (+ {charges} €)"
            return IMMOWEB_CARD.format(cid=cid, commune=commune, slug=commune.lower(),
                                       pc=pc, price=price, label=label)
        return HtmlSource("immoweb", SOURCES["immoweb"]).parse(page(
            card("21799679", "Brussels", "1020", 650, None),
            card("21797743", "Anderlecht", "1070", 450, 100),
        ), "https://www.immoweb.be/en/search")

    def test_price_comes_from_an_attribute(self):
        # Immoweb ships <iw-price :price='{"mainValue":450,...}'>. get_text()
        # cannot see attributes, so a text-only parser found no price at all.
        a, b = self.parse()
        self.assertEqual(a.price, 650)
        self.assertEqual((b.rent, b.charges, b.price), (450, 100, 550))

    def test_id_is_the_classified_number_not_the_postal_code(self):
        a, b = self.parse()
        self.assertEqual(a.id, "immoweb:21799679")
        self.assertEqual(b.id, "immoweb:21797743")

    def test_commune_from_url(self):
        self.assertEqual(self.parse()[1].commune, "anderlecht 1070")

    def test_charges_count_toward_the_budget(self):
        from scraper.brussels.main import passes_filters
        over = HtmlSource("immoweb", SOURCES["immoweb"]).parse(page(
            IMMOWEB_CARD.format(cid="999", commune="Ixelles", slug="ixelles", pc="1050",
                                price=json.dumps({"mainValue": 650, "additionalValue": 120}),
                                label="650 € (+ 120 €)")), "https://x")[0]
        self.assertEqual(over.price, 770)
        self.assertFalse(passes_filters(over), "650 + 120 charges exceeds the 700 cap")


class TestImmovlan(unittest.TestCase):
    def test_fields(self):
        html = page(
            IMMOVLAN_CARD.format(t="apartment", T="Apartment", pc="1000", vid="vbe61442", price="1 980"),
            IMMOVLAN_CARD.format(t="studio", T="Studio", pc="1050", vid="vbe61437", price="640"),
        )
        a, b = HtmlSource("immovlan", SOURCES["immovlan"]).parse(html, "https://immovlan.be/en/real-estate")
        self.assertEqual(a.id, "immovlan:vbe61442")
        self.assertEqual(a.price, 1980)          # space is a thousands separator
        self.assertEqual(a.commune, "1000 brussels")
        self.assertEqual(b.price, 640)
        self.assertTrue(all(l.price is not None for l in (a, b)))


class TestErasmusPlay(unittest.TestCase):
    def test_ld_json_offers(self):
        payload = {"offers": [
            {"name": "Private room at Saint-Josse, Brussels", "sku": "3319171",
             "url": "https://erasmusplay.com/en/bruxellesbrussel/private-room/saint-josse-3319171",
             "price": 605, "availabilityStarts": "2026-09-01"},
            {"name": "Private room at Rue Froebel", "sku": "976392",
             "url": "https://erasmusplay.com/en/bruxellesbrussel/private-room/rue-froebel-976392",
             "price": 520, "availabilityStarts": "2026-10-15"},
        ]}
        html = ('<html><body><script type="application/ld+json">'
                + json.dumps(payload) + "</script></body></html>")
        a, b = JsonSource("erasmusplay", SOURCES["erasmusplay"]).parse(html, "https://erasmusplay.com/en/x.html")
        self.assertEqual(a.id, "erasmusplay:3319171")
        self.assertEqual(a.title, "Private room at Saint-Josse, Brussels")
        self.assertEqual(a.price, 605)
        self.assertEqual(a.commune, "Saint-Josse")        # derived from the title
        self.assertEqual(str(a.available_from), "2026-09-01")
        self.assertEqual(b.commune, "", "unknown commune must stay empty, not be guessed")


class TestAppartager(unittest.TestCase):
    def card(self, commune, slug, price):
        href = f"https://www.appartager.be/colocation-{commune}/{slug}/H150808934489"
        return (f'<div class="listing_item"><a href="{href}">'
                f'<span class="price">{price} € pm</span> Bonjour, je propose une belle '
                f'chambre dans une maison pour un colocataire tranquille</a></div>')

    def test_periphery_is_filtered_out(self):
        from scraper.brussels.main import passes_filters
        html = page(self.card("waterloo", "belle-chambre-a-waterloo", 655),
                    self.card("ixelles-elsene", "studio-a-ixelles", 690))
        got = HtmlSource("appartager", SOURCES["appartager"]).parse(html, "https://www.appartager.be/x")
        by = {l.commune: l for l in got}
        self.assertFalse(passes_filters(by["waterloo"]), "Waterloo is not the Capital Region")
        self.assertTrue(passes_filters(by["ixelles-elsene"]))

    def test_title_is_not_the_whole_card_text(self):
        got = HtmlSource("appartager", SOURCES["appartager"]).parse(
            page(self.card("ixelles-elsene", "studio-a-ixelles", 690)), "https://www.appartager.be/x")
        self.assertNotIn("Bonjour", got[0].title)
        self.assertEqual(got[0].title, "Studio a ixelles")


class TestGenericBehaviour(unittest.TestCase):
    def test_card_without_a_link_is_dropped(self):
        html = page('<article class="listing-teaser"><span>no link</span></article>')
        self.assertEqual(HtmlSource("brukot", SOURCES["brukot"]).parse(html, "https://x"), [])

    def test_json_source_falls_back_to_html(self):
        html = page(BRUKOT_CARD.format(lid="1", href="/en/BK/1", typ="Student room",
                                       alt="Student room", m2="16", hood="Ixelles",
                                       rent="500", avail="1st September"))
        # A JSON source pointed at a page with no JSON must still parse cards.
        self.assertEqual(len(JsonSource("brukot", SOURCES["brukot"]).parse(html, "https://x")), 1)

    def test_adverts_are_not_listings(self):
        # student.be ships an `ads` array of adverts carrying id/url, which the
        # listing heuristic once mistook for offers.
        ads = {"ads": [{"id": 1, "client": "STUDENT", "url": "https://x",
                        "campaign_name": "School pages NL", "iframe_tag": None}]}
        html = ('<html><body><script type="application/json">'
                + json.dumps(ads) + "</script></body></html>")
        src = JsonSource("student_be", SOURCES["student_be"])
        self.assertEqual(src._extract_items(html), [])

    def test_pagination_helper(self):
        self.assertEqual(add_page_param("https://x.be/search?a=1", "page", 3),
                         "https://x.be/search?a=1&page=3")

    def test_window_classified_is_reachable(self):
        html = ("<html><body><script>window.classified = "
                '{"price":{"mainValue":650}};</script></body></html>')
        blobs = [b for b, _ in iter_json_blobs(html)]
        self.assertTrue(any(b.get("price", {}).get("mainValue") == 650 for b in blobs))


if __name__ == "__main__":
    unittest.main()
