"""Acceptance tests for bottle-size selection in the online price monitor."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from monitor import (
    beverage_volume_liters, is_allowed_beverage, match_rules,
    parse_card, scrub_historical_beverages,
)

CFG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
RULES = CFG["watch_rules"]


class TestBottlePreferences(unittest.TestCase):
    def test_soft_drinks_at_least_one_litre_per_pet_bottle(self):
        expected = [
            "Coca-Cola Original 1 l PET", "Coca-Cola Original 1,25l plastová láhev",
            "Coca Cola Original 1.5 L", "Coca-Cola Original 2 l",
            "Coca-Cola Original 2,25 l PET", "Coca-Cola Original 6 x 1,5 l PET",
            "Coca-Cola Original 4x1000ml", "Coca-Cola Original 1500 ml",
        ]
        for name in expected:
            with self.subTest(name=name):
                m = match_rules(name, RULES)
                self.assertIsNotNone(m)
                self.assertEqual(m['category'], 'Nápoje / limonády')

    def test_soft_drinks_reject_small_volume_and_other_packages(self):
        rejected = [
            "Coca-Cola Original plechovka 330 ml", "Coca-Cola Original 0,5 l PET",
            "Coca-Cola Original 0.75L PET", "Coca-Cola Original 6x0,33 l",
            "Coca-Cola Original 4 × 500 ml PET", "Coca-Cola Original 0,85 l PET",
            "Coca-Cola Original 2 l skleněná láhev", "Coca-Cola Original sklo 1 l",
            "Coca-Cola Original 1 l plech", "Coca-Cola Original 1 l tetrapak",
            "Coca-Cola Original 1 l karton", "Coca-Cola Original 2l + 0,5l PET",
            "Coca-Cola Original bez uvedeného objemu",
            "Coca-Cola Zero 1,5 l PET", "Coca-Cola Light 2l PET",
        ]
        for name in rejected:
            with self.subTest(name=name):
                self.assertIsNone(match_rules(name, RULES))

    def test_water_only_one_point_five_litre_pet_bottles(self):
        brands = ("Aquila neperlivá", "Rajec jemně perlivá", "Dobrá voda kojenecká")
        for brand in brands:
            for size in ("1,5 l PET", "1.5l", "1500 ml PET", "6×1,5l", "6 x 1500ml"):
                name = brand + " " + size
                with self.subTest(name=name):
                    m = match_rules(name, RULES)
                    self.assertIsNotNone(m)
                    self.assertEqual(m['category'], 'Nápoje / vody')
            for size in ("0,5 l PET", "1 l PET", "2 l PET", "6x0,5 l PET", "500ml", "6x2l", "bez uvedeného objemu", "1,5l sklo", "1,5 l plechovka"):
                name = brand + " " + size
                with self.subTest(name=name):
                    self.assertIsNone(match_rules(name, RULES))

    def test_flavored_water_still_rejected(self):
        for name in ("Aquila citron 1,5 l PET", "Rajec malinová ochucená 1,5 l PET", "Dobrá voda ochucená 1,5 l"):
            with self.subTest(name=name):
                self.assertIsNone(match_rules(name, RULES))

    def test_volume_extraction_counts_individual_bottles(self):
        samples = {
            "6 x 1,5 l": [1.5], "6×1500ml": [1.5], "Coca-Cola 1,25L": [1.25],
            "Coca Cola 2l PET": [2.0], "Aquila 1500 ml": [1.5],
            "4x0,5 l": [0.5], "voda bez objemu": [],
        }
        for name, expected in samples.items():
            with self.subTest(name=name):
                self.assertEqual(beverage_volume_liters(name), expected)

    def test_listing_accept_reject_and_pet_disclaimer(self):
        def row(name):
            return {"name": name, "url": "https://www.rohlik.cz/1999999-test", "card": f"39,90 Kč -25 % {name}", "current_price": "39,90 Kč"}
        self.assertIsNone(parse_card("Rohlík", row("Aquila neperlivá 0,75 l PET"), CFG))
        self.assertIsNone(parse_card("Rohlík", row("Coca-Cola Original 0,5 l PET"), CFG))
        water = parse_card("Rohlík", row("Aquila neperlivá 1,5 l PET"), CFG)
        self.assertIsNotNone(water)
        self.assertNotIn('neověřený', water.note)
        soda = parse_card("Rohlík", row("Coca-Cola Original 2 l"), CFG)
        self.assertIsNotNone(soda)
        self.assertIn('neověřený', soda.note)

    def test_beverage_cleanup_retains_other_categories(self):
        with TemporaryDirectory() as td:
            hist = Path(td) / 'history'; hist.mkdir()
            old = [
                {'name': 'Coca-Cola Original 0,5 l', 'category': 'Nápoje / limonády', 'rule_id': 'W036', 'url': 'bad-cola'},
                {'name': 'Rajec neperlivá 0,75 l', 'category': 'Nápoje / vody', 'rule_id': 'W034', 'url': 'bad-water'},
                {'name': 'Aquila neperlivá 1,5l', 'category': 'Nápoje / vody', 'rule_id': 'W033', 'url': 'good-water'},
                {'name': 'Coca-Cola Original 2l', 'category': 'Nápoje / limonády', 'rule_id': 'W036', 'url': 'good-cola'},
                {'name': 'Banány 1kg', 'category': 'Ovoce', 'rule_id': 'W038', 'url': 'fruit'},
            ]
            snap = {'offers': old, 'changes': [{'url': o['url']} for o in old]}
            history_path = hist / '2026-10-18.json'; history_path.write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
            with patch('monitor.DATA', Path(td)):
                self.assertEqual(scrub_historical_beverages(CFG), 2)
                self.assertEqual(scrub_historical_beverages(CFG), 0)
            clean = json.loads(history_path.read_text(encoding='utf-8'))
            self.assertEqual({o['url'] for o in clean['offers']}, {'good-cola', 'good-water', 'fruit'})
            self.assertEqual({o['url'] for o in clean['changes']}, {'good-cola', 'good-water', 'fruit'})


if __name__ == '__main__':
    unittest.main()
