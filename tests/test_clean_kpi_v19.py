"""Tests for conservative matching and non-invented dashboard KPI input."""
import unittest
import json
from pathlib import Path
import monitor, catalog_scan
CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf8'))

class CleanReleaseTests(unittest.TestCase):
    def test_no_flavoured_water(self):
        for s in ['Dobrá voda Neperlivá jahoda 6×1,5 l', 'Dobrá voda neperlivá malina 1,5 l', 'Dobrá voda Neperlivá bílé hrozny 6×1,5 l']:
            self.assertIsNone(monitor.match_rules(s,CFG['watch_rules']),s)
    def test_plain_water_allowed(self):
        self.assertEqual(monitor.match_rules('Dobrá voda neperlivá PET 1,5 l',CFG['watch_rules'])['id'],'W035')
    def test_omega_supplements_are_not_cooking_fat(self):
        self.assertIsNone(monitor.match_rules('Mollers Omega-3 želé rybičky Cola tbl.45',CFG['watch_rules']))
        self.assertEqual(monitor.match_rules('Omega rostlinný ztužený tuk 250 g',CFG['watch_rules'])['id'],'W030')
    def test_meat_exclusions(self):
        for name in ['Apetisimo Kuřecí stehna gyros, krájená', 'Applaws Cat kapsička kuřecí prsa pro kočky', 'Krůtí prsa čerstvá']:
            self.assertIsNone(monitor.match_rules(name,CFG['watch_rules']),name)
    def test_matching_packs_and_verified_prices_only(self):
        def obj(shop,url,qty,price,verified=True):
            return dict(shop=shop,url=url,name='Hellmanns Majonéza',quantity=qty,price=price,price_verified=verified,terms='akce')
        p=[obj('Rohlík','https://www.rohlik.cz/123', '625 ml',89.9),obj('Košík','https://www.kosik.cz/p123','405 ml',65.9)]
        catalog_scan.compare_catalog_items(p,monitor,[])
        self.assertFalse(p[0].get('other_shop_url'))
        q=[obj('Rohlík','https://www.rohlik.cz/123','625 ml',89.9),obj('Košík','https://www.kosik.cz/p123','625 ml',65.9,False)]
        catalog_scan.compare_catalog_items(q,monitor,[])
        self.assertFalse(q[0].get('other_shop_url'))
        r=[obj('Rohlík','https://www.rohlik.cz/123','625 ml',89.9),obj('Košík','https://www.kosik.cz/p123','625 ml',65.9)]
        catalog_scan.compare_catalog_items(r,monitor,[])
        self.assertEqual(r[0]['other_shop_price'],65.9)
        self.assertEqual(r[1]['other_shop_price'],89.9)
    def test_zero_data_was_not_prefilled_with_old_prices(self):
        x=json.loads((Path(__file__).resolve().parents[1]/'docs/data/latest.json').read_text(encoding='utf8'))
        self.assertEqual(x['offers'],[])
        self.assertEqual(x['catalog'],[])
        self.assertIsNone(x['checked_at'])
if __name__=='__main__': unittest.main()
