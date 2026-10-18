"""Product detail / packaging / thumbnails: deterministic offline tests."""
import json
import unittest
from pathlib import Path
from dataclasses import asdict
from monitor import (Offer, parse_card, apply_detail, precise_pack, size_from_listing,
                     quantity_base, safe_image_url, add_comparisons, build_report,
                     EXTRACT_JS, DETAIL_JS)

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))

class ProductEnrichmentTests(unittest.TestCase):
    def test_hellmann_size_from_card_listing(self):
        row={'name':"Hellmann's Majonéza",'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza',
             'card':"74,90 Kč 129,90 Kč -42 % Hellmann's Majonéza\n625 ml\n119,84 Kč/l",
             'current_price':'74,90 Kč', 'image_url':'https://cdn.kosik.cz/mayo.webp'}
        x=parse_card('Košík',row,CFG)
        self.assertIsNotNone(x)
        self.assertEqual(x.quantity,'625 ml')
        self.assertEqual(x.unit_price,119.84)
        self.assertEqual(x.unit_label,'Kč/l')
        self.assertEqual(x.image_url,'https://cdn.kosik.cz/mayo.webp')
    def test_size_on_product_page_and_no_price_override(self):
        row={'name':"Hellmann's Majonéza",'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza',
             'card':"74,90 Kč -42 % Hellmann's Majonéza",'current_price':'74,90 Kč'}
        x=parse_card('Košík',row,CFG)
        self.assertEqual(x.quantity,'')
        apply_detail(x,{'heading':"Hellmann's Majonéza",'size':'625 ml',
                        'image_url':'https://cdn.kosik.cz/hellmanns.jpg'})
        self.assertEqual(x.quantity,'625 ml')
        self.assertEqual(x.unit_price,119.84)
        self.assertEqual(x.price,74.90)
        self.assertEqual(x.detail_source,'detail page')
        self.assertTrue(x.image_url.endswith('.jpg'))
        self.assertEqual(asdict(x)['quantity'],'625 ml')
    def test_wrong_product_page_cannot_change_metadata(self):
        row={'name':"Hellmann's Majonéza",'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza',
             'card':"74,90 Kč -42 % Hellmann's Majonéza",'current_price':'74,90 Kč'}
        x=parse_card('Košík',row,CFG)
        apply_detail(x,{'heading':'Coca-Cola Original','size':'2 l','image_url':'https://cdn.kosik.cz/coca.jpg'})
        self.assertEqual(x.quantity,'')
        self.assertEqual(x.image_url,'')
    def test_refuse_unsafe_images(self):
        self.assertEqual(safe_image_url('javascript:alert(1)'), '')
        self.assertEqual(safe_image_url('data:image/png;base64,AAAA'), '')
        self.assertEqual(safe_image_url('http://example.com/p.png'), '')
        self.assertEqual(safe_image_url('/product/mayonnaise.jpg','https://www.kosik.cz/p459210-xx'),
                         'https://www.kosik.cz/product/mayonnaise.jpg')
    def test_no_wrong_size_from_unit_price_or_cart(self):
        self.assertEqual(precise_pack('119,84 Kč/l'), '')
        self.assertEqual(precise_pack('625 ml'), '625 ml')
        self.assertEqual(size_from_listing("Hellmann's Majonéza",{'card':'0 ks v košíku 119,84 Kč/l'}),'')
        self.assertEqual(quantity_base('405 ml'),(0.405,'l'))
    def test_distinguish_volume_625_from_405(self):
        a=Offer(shop='Košík',name="Hellmann's Majonéza",url='https://www.kosik.cz/p444111-x',
                price=74.9,discount_pct=42,old_price=None,brand='Hellmann',favorite=False,
                quantity='625 ml',terms='akce')
        b=Offer(shop='Rohlík',name="Hellmann's Majonéza",url='https://www.rohlik.cz/1333333-x',
                price=59.9,discount_pct=42,old_price=None,brand='Hellmann',favorite=False,
                quantity='405 ml',terms='akce')
        add_comparisons([a,b],[])
        self.assertIsNone(a.other_shop_price)
        self.assertIsNone(b.other_shop_price)
    def test_report_includes_packaging(self):
        row={'name':"Hellmann's Majonéza",'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza',
             'card':"74,90 Kč -42 % Hellmann's Majonéza 625 ml",'current_price':'74,90 Kč'}
        o=parse_card('Košík',row,CFG)
        snapshot={'date':'2026-10-18','checked_at':'2026-10-18T15:00+02:00',
                'offers':[asdict(o)],'changes':[], 'sources':{}, 'source_urls':{}, 'delivery':{'postal_code':'149 00'}}
        self.assertIn('balení: 625 ml',build_report(snapshot))
    def test_frontend_sourcing_consistency(self):
        self.assertIn('image_url',EXTRACT_JS)
        self.assertIn('size',DETAIL_JS)
        html=(Path(__file__).resolve().parents[1]/'docs'/'index.html').read_text(encoding='utf-8')
        self.assertIn('productCell(o)',html)
        self.assertIn('Balení:',html)
        self.assertIn('loading=\'lazy\'',html)

if __name__ == '__main__':unittest.main()
