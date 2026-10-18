"""Regression checks for user's original preferred list and same-origin photos."""
import io
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
import monitor

ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))

class Response:
    ok=True
    headers={'content-type':'image/png'}
    def __init__(self,buf): self.buf=buf
    def body(self):return self.buf

class FakeRequest:
    def __init__(self,buf):self.buf=buf
    def get(self,*a,**k):return Response(self.buf)

class FakePage:
    def __init__(self,buf):self.request=FakeRequest(buf)
    def evaluate(self,*a,**kw): return False

class TestFavoritesAndImages(unittest.TestCase):
    def test_all_original_selected_rules_are_favorites(self):
        self.assertEqual(len(CFG['watch_rules']),75)
        self.assertTrue(all(r.get('priority')==1 for r in CFG['watch_rules']))

    def test_leerdammer_hellmann_and_colgate_are_favorites_even_at_7pct(self):
        products = [
            ('Leerdammer Original sýr plátky 100 g','Rohlík',
             'https://www.rohlik.cz/1298888-leerdammer'),
            ("Hellmann's Majonéza",'Košík','https://www.kosik.cz/p459210-hellmann-s-majoneza'),
            ('Colgate Whitening bělící zubní pasta 75 ml','Rohlík',
             'https://www.rohlik.cz/1298889-colgate'),
        ]
        for name,shop,url in products:
            with self.subTest(name=name):
                row={'name':name,'url':url,'card':'29,90 Kč 32,90 Kč -7 % '+name,'current_price':'29,90 Kč'}
                o=monitor.parse_card(shop,row,CFG)
                self.assertIsNotNone(o)
                self.assertTrue(o.favorite)

    def test_photo_is_local_verified_and_usable_without_hotlink(self):
        im=Image.new('RGB',(300,360),color=(204,204,200))
        stream=io.BytesIO();im.save(stream,format='PNG')
        item=monitor.Offer('Košík',"Hellmann's Majonéza",'https://www.kosik.cz/p459210-hellmann-s-majoneza',
                           74.90,42,129.90,"Hellmann's",True,'625 ml','akce')
        with TemporaryDirectory() as temp, patch.object(monitor,'DATA',Path(temp)):
            self.assertTrue(monitor.cache_product_photo(item,FakePage(stream.getvalue()),
                {'heading':"Hellmann's Majonéza",'image_candidates':['https://example.org/hellmann.jpg']}))
            self.assertRegex(item.image_url,r'^data/images/[a-f0-9]{22}\.webp$')
            actual=Path(temp)/item.image_url.replace('data/','')
            self.assertTrue(actual.exists())
            with Image.open(actual) as img:
                self.assertLessEqual(img.width,144)
                self.assertLessEqual(img.height,160)
                self.assertEqual(img.format,'WEBP')

    def test_wrong_product_detail_does_not_cache_image(self):
        img=Image.new('RGB',(300,300));tmp=io.BytesIO();img.save(tmp,format='PNG')
        offer=monitor.Offer('Košík',"Hellmann's Majonéza",'https://www.kosik.cz/p459210-hellmann-s-majoneza',
                            74.90,42,None,'Hellmann',True,'625 ml','akce')
        with TemporaryDirectory() as temp, patch.object(monitor,'DATA',Path(temp)):
            self.assertFalse(monitor.cache_product_photo(offer,FakePage(tmp.getvalue()),
                 {'heading':'Čokoládová tyčinka','image_candidates':['https://example.org/wrong.png']}))
            self.assertEqual(offer.image_url,'')

    def test_browser_js_accepts_only_local_assets_or_https_images(self):
        text=(ROOT/'docs/index.html').read_text(encoding='utf-8')
        self.assertIn("const isPreferred=o=>Boolean(o.favorite",text)
        self.assertIn('data\\/images\\/[a-f0-9]{22}',text)
        self.assertIn('function confirmedOffers(snapshot)',text)
        self.assertIn('const offers=confirmedOffers(data)',text)

if __name__=='__main__': unittest.main()
