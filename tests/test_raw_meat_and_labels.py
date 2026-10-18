"""Regression tests for raw-only meat, Košík accessibility headings, photo metadata and prices."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from monitor import (clean_product_name, is_raw_meat_name, match_rules, parse_card,
                     parse_item_price, apply_detail, scrub_historical_meat, EXTRACT_JS, DETAIL_JS)
CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))

class RawMeatAndLabelsTests(unittest.TestCase):
    def test_raw_meat_positive(self):
        names = [
          'Kuřecí prsní řízky bez kosti a kůže 1 kg',
          'Campese Kuřecí vykostěná stehna z volného chovu cca 0,3 kg',
          'Kuřecí stehna čerstvá 1 kg',
          'Kuřecí paličky 800 g',
          'Vepřová krkovice bez kosti plátky 500 g',
          'Vepřová panenka vcelku cca 500 g',
          'Hovězí svíčková pravá cca 1 kg',
          'Mražená kuřecí prsa 1 kg',
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(is_raw_meat_name(name))
                self.assertEqual(match_rules(name,CFG['watch_rules'])['category'],'Maso')
    def test_not_raw_meat(self):
        bad = [
          'Just Meat Krůtí prsa s pepřem a solí, 100 g',
          'Just Meat Kuřecí prsa s pepřem a solí, 100 g',
          'Kuřecí prsa sušená 100 g',
          'Kuřecí prsa jerky 50 g',
          'Kuřecí prsní řízky marinované 500 g',
          'Kuřecí prsa v konzervě 100 g',
          'Kuřecí prsa v plechovce 200 g',
          'Krůtí prsa s bylinkami 500 g',
          'Krůtí prsa chlazená 900 g',
          'Krůtí stehna chlazená 600 g',
          'Hovězí svíčková falešná 900 g',
          'Vepřová krkovice uzená 500 g',
          'Vepřová panenka grilovaná 250 g',
          'Hovězí svíčková na smetaně 400 g',
          'Svíčková omáčka s hovězím masem 400 g',
          'Kuřecí prsa v hotové omáčce 400 g',
          'Kuřecí prsa vařená v páře 100 g',
          'Kuřecí prsní řízky obalované 300 g',
        ]
        for name in bad:
            with self.subTest(name=name):
                self.assertFalse(is_raw_meat_name(name))
                r = match_rules(name,CFG['watch_rules'])
                self.assertFalse(r and r['category']=='Maso')
    def test_kosik_accessibility_text_is_not_product_name(self):
        original = "Zobrazit detail produktu Hellmann's Majonéza"
        self.assertEqual(clean_product_name(original),"Hellmann's Majonéza")
        row={'name':original,'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza',
             'card':"74,90 Kč 129,90 Kč -42 % Zobrazit detail produktu Hellmann's Majonéza",
             'current_price':'74,90 Kč'}
        o=parse_card('Košík',row,CFG)
        self.assertIsNotNone(o)
        self.assertEqual(o.name,"Hellmann's Majonéza")
        apply_detail(o,{'heading':"Hellmann's Majonéza",'size':'625 ml','image_url':'https://cdn.kosik.cz/images/majon.jpg'})
        self.assertEqual(o.quantity,'625 ml')
        self.assertEqual(o.unit_price,119.84)
        self.assertTrue(o.image_url.endswith('majon.jpg'))
    def test_unit_price_is_not_item_price(self):
        self.assertIsNone(parse_item_price('699,00 Kč/kg'))
        self.assertIsNone(parse_item_price('119,84 Kč/l'))
        self.assertEqual(parse_item_price('699,00 Kč/kg 69,90 Kč'),69.9)
        self.assertEqual(parse_item_price('69,90 Kč; 699,00 Kč/kg'),69.9)
        self.assertEqual(parse_item_price('46 90 Kč 119,84 Kč/l'),46.9)
    def test_refuse_unit_only_current_price_but_accept_real_card_price(self):
        row={'name':'Colgate Whitening bělící zubní pasta 75 ml',
             'url':'https://www.rohlik.cz/1234567-colgate',
             'card':'732,00 Kč/l 54,90 Kč -21 % Colgate Whitening bělící zubní pasta 75 ml',
             'current_price':'732,00 Kč/l'}
        o=parse_card('Rohlík',row,CFG)
        self.assertIsNotNone(o)
        self.assertEqual(o.price,54.9)
    def test_archive_scrub_idempotent(self):
        with TemporaryDirectory() as t:
            base=Path(t);h=base/'history';h.mkdir()
            saved={'offers':[
                {'url':'a','category':'Maso','name':'Just Meat Kuřecí prsa s pepřem a solí, 100 g'},
                {'url':'b','category':'Maso','name':'Kuřecí prsní řízky bez kosti 1 kg'},
                {'url':'c','category':'Majonézy','name':"Hellmann's Majonéza"}],
                'changes':[{'url':'a'},{'url':'b'}]}
            f=h/'2026-10-18.json';f.write_text(json.dumps(saved),encoding='utf-8')
            with patch('monitor.DATA',base):
                self.assertEqual(scrub_historical_meat(CFG),1)
                self.assertEqual(scrub_historical_meat(CFG),0)
            after=json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual([x['url'] for x in after['offers']],['b','c'])
            self.assertEqual(after['changes'],[{'url':'b'}])
    def test_extractors_offer_img_and_cleaning(self):
        self.assertIn('application/ld+json', DETAIL_JS)
        self.assertIn('og:image', DETAIL_JS)
        self.assertIn('detail\\s+produktu', EXTRACT_JS)
        ui=(Path(__file__).resolve().parents[1]/'docs/index.html').read_text(encoding='utf-8')
        self.assertIn('displayProductName(name)',ui)

if __name__ == '__main__': unittest.main()
