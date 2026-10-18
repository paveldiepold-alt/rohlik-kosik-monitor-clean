"""V14 regression tests: Zewa pocket, generic kitchen paper towels, boxed tissues."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import monitor

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))

class TestPaperGoods(unittest.TestCase):
    def test_positive_groups(self):
        examples={
            'Zewa Deluxe Standard kapesníky 3-vrstvé 10x10 ks': 'W073',
            'Zewa Deluxe Family kapesníky 3vrstvé':'W075',
            'Zewa Deluxe Standard papírové kapesníky 3vrstvé 10x10ks':'W073',
            'Zewa Wisch Weg Original kuchyňské utěrky 4 role':'W074',
            'Zewa Wisch & Weg Original kuchyňské utěrky 4 role':'W074',
            'Tento Kuchyňské papírové utěrky 2 role':'W074',
            'Harmony Papírové utěrky 3vrstvé 2 role':'W074',
            'Zewa papírové kapesníky v krabici 3vrstvé 90 ks':'W075',
            'Kleenex Papírové kapesníky v krabičce 3 vrstvé 100 ks':'W075',
            'Papírové kapesníky 3vrstvé BOX 100 ks':'W075',
            'Zewa Deluxe toaletní papír 8 rolí':'W053',
            'Zewa Papírové ubrousky bílé 100ks':'W053',
        }
        for name,expected in examples.items():
            with self.subTest(name=name):
                result=monitor.match_rules(name,CFG['watch_rules'])
                self.assertIsNotNone(result)
                self.assertEqual(result['id'],expected)

    def test_negative_cross_category_and_false_positives(self):
        names=[
            'Zewa Deluxe kapesníky v krabici 2vrstvé 100ks',
            'Kapesníky v krabici 2 vrstvé',
            'Zewa Softis kapesníky 3vrstvé balíčky',
            'Zewa Deluxe Design kapesníky 3vrstvé (typ balení neuveden)',
            'Zewa Deluxe vlhčené kapesníky 3 vrstvé',
            'Vlhčené kuchyňské utěrky citron 80 ks',
            'Utěrka z mikrovlákna na kuchyňské linky',
            'Kuchyňské bavlněné utěrky 3 ks',
            'Kapesníky v krabici 2 vrstvé 100ks',
            'Kapesníky papírové 3vrstvé 10x10ks Neznačkové',
            'Zewa Deluxe ubrousky vlhčené 80ks',
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertIsNone(monitor.match_rules(name,CFG['watch_rules']))

    def test_both_shops_and_5pct_threshold(self):
        items=[
            ('Košík','https://www.kosik.cz/p82407-zewa-deluxe-standard-kapesniky-3-vrstve','Zewa Deluxe Standard kapesníky 3 vrstvé','W073'),
            ('Košík','https://www.kosik.cz/p82477-zewa-deluxe-family-kapesniky-3vrstve','Zewa Deluxe Family kapesníky 3vrstvé','W075'),
            ('Košík','https://www.kosik.cz/p233874-zewa-wisch-weg-original-kuchynske-uterky-4-role','Zewa Wisch Weg Original kuchyňské utěrky 4 role','W074'),
            ('Rohlík','https://www.rohlik.cz/1234567-kitchen-paper','Kuchyňské papírové utěrky Harmony 4 role','W074'),
        ]
        for shop,url,name,rid in items:
            with self.subTest(name=name):
                row=dict(url=url,name=name,card='49,90 Kč -7 % '+name,current_price='49,90 Kč')
                offer=monitor.parse_card(shop,row,CFG)
                self.assertIsNotNone(offer)
                self.assertTrue(offer.favorite)
                self.assertEqual(offer.rule_id,rid)
        self.assertGreaterEqual(len(CFG['favorites']),6)

    def test_historical_reclassification_without_touching_linteo(self):
        base=Path(__file__).resolve().parents[1]
        rows=[
            dict(url='a',name='Zewa Deluxe Standard kapesníky 3vrstvé',category='Papír a hygiena',rule_id='W053',favorite=True),
            dict(url='b',name='Zewa ubrousky vlhčené',category='Papír a hygiena',rule_id='W053',favorite=True),
            dict(url='c',name='Linteo Vlhčené ubrousky',category='Papír a hygiena',rule_id='W054',favorite=True),
        ]
        with TemporaryDirectory() as temp:
            folder=Path(temp)/'history';folder.mkdir()
            f=folder/'2026-10-18.json'
            f.write_text(json.dumps({'offers':rows,'changes':[{'url':o['url']} for o in rows]}),encoding='utf-8')
            with patch('monitor.DATA',Path(temp)):
                self.assertEqual(monitor.scrub_historical_paper_goods(CFG),2)
                self.assertEqual(monitor.scrub_historical_paper_goods(CFG),0)
            doc=json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual([r['url'] for r in doc['offers']],['a','c'])
            self.assertEqual(doc['offers'][0]['rule_id'],'W073')
            self.assertEqual(doc['offers'][0]['category'],'Kapesníky / balíčky')

if __name__=='__main__': unittest.main()
