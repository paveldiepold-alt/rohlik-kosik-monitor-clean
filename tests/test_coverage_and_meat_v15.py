"""Coverage honesty and updated chicken-only shopping list."""
import json
import unittest
from pathlib import Path
from monitor import parse_card, match_rules, price_pair_before_discount, is_raw_meat_name
CFG = json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))

class CoverageMeatV15(unittest.TestCase):
    def test_only_requested_raw_meat(self):
        yes=['Kuřecí prsní řízky bez kosti 1 kg', 'Kuřecí vykostěná stehna z volného chovu',
             'Vepřová krkovice plátky 0,7 kg', 'Vepřová panenka bez řetízku',
             'Hovězí svíčková pravá 1 kg']
        no=['Krůtí prsa chlazená 900 g', 'Krůtí stehna 700 g',
            'Just Meat Kuřecí prsa s pepřem a solí, 100 g',
            'Vepřová krkovice marinovaná 1 kg', 'Hovězí svíčková falešná 1 kg']
        for n in yes:
            with self.subTest(n=n):
                self.assertTrue(is_raw_meat_name(n))
                self.assertEqual(match_rules(n,CFG['watch_rules'])['category'],'Maso')
        for n in no:
            with self.subTest(n=n):
                self.assertFalse(is_raw_meat_name(n))
                r=match_rules(n,CFG['watch_rules'])
                self.assertFalse(r and r['category']=='Maso')
    def test_wrong_original_price_not_published(self):
        self.assertEqual(price_pair_before_discount('cca55,92 Kč 111,92 Kč -50 % pro vás',50),(55.92,111.92))
        row={'name':'Hrozny tmavé volně (odr. Red globe), střapec',
             'url':'https://www.rohlik.cz/1234567-hrozny',
             'card':'0 kusů v košíku cca55,92 Kč 111,92 Kč -50 % pro vás Hrozny tmavé volně (odr. Red globe), střapec',
             'current_price':'111,92 Kč'}
        o=parse_card('Rohlík',row,CFG)
        self.assertIsNotNone(o)
        self.assertEqual(o.price,55.92)
    def test_limit_and_coverage_transparency(self):
        self.assertGreater(CFG['max_items_per_store'],700)
        self.assertGreater(CFG['max_scroll_rounds'],9)
        ui=(Path(__file__).resolve().parents[1]/'docs/index.html').read_text(encoding='utf-8')
        self.assertIn('NEÚPLNÝ vzorek',ui)

if __name__ == '__main__':unittest.main()
