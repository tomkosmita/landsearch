"""Field parsers. Every case here comes from real portal output."""

import unittest
from datetime import date

from scraper.brussels import parsing


class TestPrice(unittest.TestCase):
    def test_european_formats(self):
        self.assertEqual(parsing.parse_eur("500 €"), 500)
        self.assertEqual(parsing.parse_eur("€ 1.250"), 1250)
        self.assertEqual(parsing.parse_eur("1 250 EUR"), 1250)   # immovlan "1 980 €"
        self.assertEqual(parsing.parse_eur("1.250,50 €"), 1250)
        self.assertEqual(parsing.parse_eur("675€/month"), 675)

    def test_zero_is_missing_unless_allowed(self):
        # Brukot really does print "Charges: 0 €", which is a known zero.
        self.assertIsNone(parsing.parse_eur("0 €"))
        self.assertEqual(parsing.parse_eur("0 €", allow_zero=True), 0)

    def test_no_number_is_none(self):
        self.assertIsNone(parsing.parse_eur("op aanvraag"))
        self.assertIsNone(parsing.parse_eur(None))

    def test_rent_and_charges(self):
        self.assertEqual(parsing.parse_rent_and_charges("Rent: 500 €, Charges: 50 €"), (500, 50))
        self.assertEqual(parsing.parse_rent_and_charges("Rent: 500 €, Charges: 0 €"), (500, 0))
        self.assertEqual(parsing.parse_rent_and_charges("Loyer 480 € charges 60 €"), (480, 60))
        self.assertEqual(parsing.parse_rent_and_charges("625 €"), (625, None))

    def test_excl_charges_is_not_a_charges_amount(self):
        # Brukot prints "560 € excl. charges" — the words must not yield a number.
        rent, charges = parsing.parse_rent_and_charges("560 € excl. charges")
        self.assertEqual(rent, 560)
        self.assertIsNone(charges)

    def test_total(self):
        self.assertEqual(parsing.total_price(500, 50), 550)
        self.assertEqual(parsing.total_price(500, 0), 500)
        self.assertIsNone(parsing.total_price(None, 50))


class TestArea(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(parsing.parse_area("18 m²"), 18)
        self.assertEqual(parsing.parse_area("25m2"), 25)
        self.assertIsNone(parsing.parse_area("nice room"))


class TestDate(unittest.TestCase):
    TODAY = date(2026, 8, 30)

    def d(self, text):
        return parsing.parse_date(text, self.TODAY)

    def test_month_names_three_languages(self):
        self.assertEqual(self.d("1st September"), date(2026, 9, 1))       # brukot
        self.assertEqual(self.d("dès le 15 septembre 2026"), date(2026, 9, 15))
        self.assertEqual(self.d("Beschikbaar vanaf 15/09/2026"), date(2026, 9, 15))

    def test_iso_and_bare_month(self):
        self.assertEqual(self.d("2026-10-01"), date(2026, 10, 1))   # erasmusplay
        self.assertEqual(self.d("available from September"), date(2026, 9, 1))

    def test_year_inferred_forward(self):
        # A July date given without a year means next July, not four months ago.
        self.assertEqual(self.d("1st July"), date(2027, 7, 1))

    def test_immediate_and_garbage(self):
        self.assertEqual(self.d("Available immediately"), self.TODAY)
        self.assertIsNone(self.d("ask us"))
        self.assertIsNone(self.d(None))


class TestLocation(unittest.TestCase):
    def test_brussels_communes_pass(self):
        for text in ("Ixelles", "Saint-Gilles 1060", "Bruxelles", "Schaarbeek",
                     "1000", "Laeken", "Woluwe-Saint-Pierre", "ixelles-elsene"):
            self.assertFalse(parsing.is_outside_brussels(text), text)

    def test_other_cities_rejected(self):
        for text in ("Leuven", "Gent", "Antwerpen 2000", "Liège 4000", "9000 Gent"):
            self.assertTrue(parsing.is_outside_brussels(text), text)

    def test_periphery_rejected(self):
        # These ring Brussels and show up in its searches, but are a long
        # commute from a city-centre campus.
        for text in ("waterloo", "Avenue Des Lilas, Waterloo", "Kraainem", "Zaventem"):
            self.assertTrue(parsing.is_outside_brussels(text), text)

    def test_unknown_location_passes(self):
        # Missing data never rejects a listing.
        for text in ("", None, "Somewhere odd"):
            self.assertFalse(parsing.is_outside_brussels(text))

    def test_brussels_wins_when_both_named(self):
        self.assertFalse(parsing.is_outside_brussels("Room in Brussels near Leuven campus"))

    def test_extract_commune_longest_match(self):
        self.assertEqual(parsing.extract_commune("Private room at Saint-Josse, Brussels"), "Saint-Josse")
        self.assertEqual(parsing.extract_commune("Kot in Woluwe-Saint-Pierre"), "Woluwe-Saint-Pierre")
        self.assertEqual(parsing.extract_commune("Private room at Rue Froebel"), "")


class TestKind(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertEqual(parsing.classify_kind("Nice studio near ULB"), "studio")
        self.assertEqual(parsing.classify_kind("Chambre en colocation"), "kot")
        # "bedroom" contains "room"; without word boundaries this misfiled every
        # apartment as a shared room.
        self.assertEqual(parsing.classify_kind("2-bedroom apartment"), "apartment")
        self.assertEqual(parsing.classify_kind("Nice place"), "unknown")


if __name__ == "__main__":
    unittest.main()
