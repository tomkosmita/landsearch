"""Regression guard for the plot monitor's output.

Kept from the (now removed) Brussels work: these two cases pin what the plot
monitor actually sends, so a future change to the shared seen/notify helpers
cannot quietly alter it.

    python -m unittest discover -s tests
"""

import unittest

from scraper.models import Listing
from scraper.notify import format_message
from scraper.seen import get_changes


class TestFormatMessage(unittest.TestCase):
    def listing(self):
        return Listing(
            id="x", title="T", url="http://u", location="Wrocław", source="olx",
            price=600000, area=800,
            utilities={"water": True, "gas": False, "electricity": True, "sewage": False},
            property_type="dzialka",
        )

    def test_new_listing(self):
        self.assertEqual(
            format_message(self.listing()),
            "<b>🌳 Nowa działka — OLX</b>\n📍 Wrocław\n💰 600 000 zł\n📐 800 m²\n"
            "💧 Woda: ✅  ⛽ Gaz: ❌  ⚡ Prąd: ✅  🚿 Kanalizacja: ❌\n\n"
            '<a href="http://u">Zobacz ogłoszenie ›</a>',
        )

    def test_price_change_strikes_through_the_old_value(self):
        self.assertEqual(
            format_message(self.listing(), {"price": (700000, 600000)}),
            "<b>🔄 Zmiana ogłoszenia — OLX</b>\n📍 Wrocław\n"
            "💰 600 000 zł  <s>700 000 zł</s>\n📐 800 m²\n"
            "💧 Woda: ✅  ⛽ Gaz: ❌  ⚡ Prąd: ✅  🚿 Kanalizacja: ❌\n\n"
            '<a href="http://u">Zobacz ogłoszenie ›</a>',
        )


class TestGetChanges(unittest.TestCase):
    def test_detects_price_and_area(self):
        self.assertEqual(get_changes({"price": 1, "area": 2}, {"price": 3, "area": 2}),
                         {"price": (1, 3)})
        self.assertEqual(get_changes({"price": 1, "area": 2}, {"price": 1, "area": 5}),
                         {"area": (2, 5)})

    def test_migrated_entry_is_not_a_change(self):
        # Entries migrated from the old list format are {}; they must not look
        # like a price change on the next run.
        self.assertEqual(get_changes({}, {"price": 5, "area": 7}), {})


if __name__ == "__main__":
    unittest.main()
