"""Orchestrator: what actually decides whether a message gets sent."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from scraper.brussels import main as orchestrator
from scraper.brussels import seen as state
from scraper.brussels.models import KotListing
from scraper.seen import load_seen, save_seen


def listing(lid="p:1", portal="p", price=500, commune="Ixelles", surface=18,
            avail=date(2026, 9, 1), title="Kot"):
    return KotListing(id=lid, portal=portal, title=title, url=f"https://x/{lid}",
                      commune=commune, rent=price, charges=None, price=price,
                      surface=surface, available_from=avail)


class TestFilters(unittest.TestCase):
    def test_budget(self):
        self.assertTrue(orchestrator.passes_filters(listing(price=700)))
        self.assertFalse(orchestrator.passes_filters(listing(price=701)))

    def test_availability_window(self):
        self.assertTrue(orchestrator.passes_filters(listing(avail=date(2026, 11, 30))))
        self.assertFalse(orchestrator.passes_filters(listing(avail=date(2027, 3, 1))))

    def test_missing_data_never_rejects(self):
        self.assertTrue(orchestrator.passes_filters(listing(price=None)))
        self.assertTrue(orchestrator.passes_filters(listing(avail=None)))
        self.assertTrue(orchestrator.passes_filters(listing(commune="")))

    def test_outside_brussels_rejected(self):
        self.assertFalse(orchestrator.passes_filters(listing(commune="Leuven")))
        self.assertFalse(orchestrator.passes_filters(listing(commune="waterloo")))


class TestQualityGate(unittest.TestCase):
    def test_mostly_priceless_source_is_withheld(self):
        # The Immoweb failure: 67 of 69 listings with no price. Such a source is
        # a broken parser, not sparse data, and would eat the notification cap.
        broken = [listing(lid=f"immoweb:{i}", portal="immoweb", price=None) for i in range(67)]
        broken += [listing(lid="immoweb:a", portal="immoweb", price=500),
                   listing(lid="immoweb:b", portal="immoweb", price=600)]
        good = [listing(lid=f"brukot:{i}", portal="brukot") for i in range(20)]
        kept, suspect = orchestrator.drop_mis_parsed_sources(broken + good)
        self.assertEqual(suspect, ["immoweb"])
        self.assertEqual({l.portal for l in kept}, {"brukot"})

    def test_small_samples_are_not_judged(self):
        # A genuinely sparse source must not be punished for two listings.
        tiny = [listing(lid="k:1", portal="k", price=None), listing(lid="k:2", portal="k", price=400)]
        kept, suspect = orchestrator.drop_mis_parsed_sources(tiny)
        self.assertEqual(suspect, [])
        self.assertEqual(len(kept), 2)

    def test_healthy_source_passes(self):
        good = [listing(lid=f"b:{i}", portal="b") for i in range(10)]
        kept, suspect = orchestrator.drop_mis_parsed_sources(good)
        self.assertEqual(suspect, [])
        self.assertEqual(len(kept), 10)


class TestDuplicateKey(unittest.TestCase):
    def test_needs_all_three_fields(self):
        self.assertEqual(listing().dup_key(), "500|ixelles|18")
        self.assertIsNone(listing(surface=None).dup_key())
        self.assertIsNone(listing(price=None).dup_key())
        self.assertIsNone(listing(commune="").dup_key())


class TestSeenState(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "brussels_seen.json"

    def test_roundtrip_and_missing_file(self):
        self.assertEqual(load_seen(self.path), {})
        save_seen({"a": {"price": 1}}, self.path)
        self.assertEqual(load_seen(self.path), {"a": {"price": 1}})

    def test_migration_guard(self):
        # An entry migrated from the old list format is {} and must not look
        # like a change on the next run.
        self.assertEqual(state.get_changes({}, {"price": 5, "available": None}), {})

    def test_tracks_price_and_availability_not_area(self):
        old = {"price": 500, "available": "2026-09-01"}
        self.assertEqual(state.get_changes(old, {"price": 550, "available": "2026-09-01"}),
                         {"price": (500, 550)})
        self.assertEqual(state.get_changes(old, {"price": 500, "available": "2026-10-01"}),
                         {"available": ("2026-09-01", "2026-10-01")})

    def test_snapshot_shape(self):
        snap = state.make_snapshot(listing())
        self.assertEqual(snap["price"], 500)
        self.assertEqual(snap["available"], "2026-09-01")
        self.assertEqual(snap["dup"], "500|ixelles|18")


class TestNotify(unittest.TestCase):
    def test_charges_are_shown_when_known(self):
        from scraper.brussels.notify import format_message
        l = listing()
        l.rent, l.charges, l.price = 450, 100, 550
        msg = format_message(l)
        self.assertIn("550 €/mc", msg)
        self.assertIn("450 + 100", msg)

    def test_unknown_fields_say_so(self):
        from scraper.brussels.notify import format_message
        msg = format_message(listing(price=None, avail=None, surface=None, commune=""))
        self.assertIn("brak ceny", msg)
        self.assertIn("termin nieznany", msg)
        self.assertIn("lokalizacja nieznana", msg)


class TestPlotMonitorUntouched(unittest.TestCase):
    """The Brussels work must not change what the plot monitor sends."""

    def test_format_message_is_unchanged(self):
        from scraper.models import Listing
        from scraper.notify import format_message
        l = Listing(id="x", title="T", url="http://u", location="Wrocław", source="olx",
                    price=600000, area=800,
                    utilities={"water": True, "gas": False, "electricity": True, "sewage": False},
                    property_type="dzialka")
        self.assertEqual(format_message(l),
                         "<b>🌳 Nowa działka — OLX</b>\n📍 Wrocław\n💰 600 000 zł\n📐 800 m²\n"
                         "💧 Woda: ✅  ⛽ Gaz: ❌  ⚡ Prąd: ✅  🚿 Kanalizacja: ❌\n\n"
                         '<a href="http://u">Zobacz ogłoszenie ›</a>')

    def test_get_changes_defaults_unchanged(self):
        from scraper.seen import get_changes
        self.assertEqual(get_changes({"price": 1, "area": 2}, {"price": 3, "area": 2}),
                         {"price": (1, 3)})
        self.assertEqual(get_changes({}, {"price": 5}), {})


if __name__ == "__main__":
    unittest.main()
