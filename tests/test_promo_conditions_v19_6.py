"""v19.6 – expiry + multibuy conditions on exact product offers."""
import json
import unittest
from pathlib import Path

from promo_terms import extract_promotion, is_conditional
from monitor import Offer, parse_card, apply_detail
from catalog_scan import row_to_product, compare_catalog_items, _offer_from_product
import monitor

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))


class PromoTermsTests(unittest.TestCase):
    def test_kosik_bref_example_date_not_pack(self):
        x=extract_promotion('Bref Power Aktiv Pine tuhý WC blok 3x50g 79,90 Kč -20 % do 3. 11.')
        self.assertEqual(x['promo_until'],'3. 11.')
        self.assertEqual(x['promo_condition'],'')
        self.assertIsNone(x['promo_min_qty'])

    def test_multibuy_expiry(self):
        x=extract_promotion('sleva 35 % při nákupu 2 kusů platí do 22.10.2026')
        self.assertEqual(x['promo_min_qty'],2)
        self.assertEqual(x['promo_condition'],'Od 2 ks')
        self.assertEqual(x['promo_until'],'22. 10. 2026')

    def test_bundle_and_membership(self):
        x=extract_promotion('Akce 2+1 zdarma s kartou Kaufland Card do 31.10.')
        self.assertEqual(x['promo_min_qty'],3)
        self.assertIn('2+1 zdarma',x['promo_condition'])
        self.assertIn('Klubová',x['promo_condition'])

    def test_personal_and_invalid_date(self):
        x=extract_promotion('sleva pro vás do 31. 2.')
        self.assertEqual(x['promo_until'],'')
        self.assertIn('Individuální',x['promo_condition'])

    def test_never_infer_promotion_from_package(self):
        x=extract_promotion('Bref 3x50 g za 79,90 Kč, výhodné balení')
        self.assertEqual(x['promo_condition'],'')
        self.assertEqual(x['promo_until'],'')

    def test_date_and_condition_from_listing(self):
        row=dict(shop='Košík',name='Bref Power Aktiv Pine tuhý WC blok 3x50g',
            url='https://www.kosik.cz/p90537-bref-power-aktiv-pine-tuhy-wc-blok-3x50g',
            card='79,90 Kč 99,90 Kč -20 % do 3. 11. Bref Power Aktiv Pine tuhý WC blok 3x50g',
            current_price='79,90 Kč')
        offer=parse_card('Košík',row,CFG)
        self.assertIsNotNone(offer)
        self.assertEqual(offer.promo_until,'3. 11.')
        self.assertIsNone(offer.promo_min_qty)
        product=row_to_product('Košík',row,CFG,monitor,'2026-10-19T09:00+02:00')
        self.assertEqual(product['promo_until'],'3. 11.')
        self.assertEqual(_offer_from_product(product,monitor).promo_until,'3. 11.')

    def test_from_confirmed_detail_page(self):
        o=Offer(shop='Košík',name='Bref Power Aktiv Pine tuhý WC blok 3x50g',
                url='https://www.kosik.cz/p90537-bref-power-aktiv-pine-tuhy-wc-blok-3x50g',
                price=79.90,discount_pct=20,old_price=99.90,brand='Bref',
                favorite=True,quantity='3 ks',terms='akce')
        apply_detail(o,{'heading':'Bref Power Aktiv Pine tuhý WC blok 3x50g',
                        'promotion_context':'Bref Power Aktiv Pine tuhý WC blok 3x50g 79,90 -20 % do 3. 11.'})
        self.assertEqual(o.promo_until,'3. 11.')
        self.assertEqual(o.promo_source,'detail')
        # A redirect to an unrelated product must not carry across expiry.
        old=o.promo_until
        apply_detail(o,{'heading':'Jiný produkt – Jar citron',
                        'promotion_context':'Jiný produkt do 18. 12. od 3 ks'})
        self.assertEqual(o.promo_until,old)
        self.assertEqual(o.promo_min_qty,None)

    def test_minimum_quantity_no_cross_shop_comparison(self):
        a={'shop':'Rohlík','name':'Bref WC blok','url':'https://www.rohlik.cz/12345',
           'price':69.9,'price_verified':True,'quantity':'3 ks','terms':'akce','promo_condition':'Od 2 ks','promo_min_qty':2}
        b={'shop':'Košík','name':'Bref WC blok','url':'https://www.kosik.cz/p12345',
           'price':79.9,'price_verified':True,'quantity':'3 ks','terms':'akce','promo_condition':'','promo_min_qty':None}
        self.assertTrue(is_conditional(a))
        compare_catalog_items([a,b],monitor)
        self.assertIsNone(a.get('other_shop_price'))
        self.assertIsNone(b.get('other_shop_price'))

    def test_frontend_displays_both_ends_and_conditions(self):
        html=(Path(__file__).resolve().parents[1]/'docs/index.html').read_text('utf-8')
        self.assertIn("if(o.promo_until)td.appendChild(node('span','Do '+o.promo_until",html)
        self.assertIn("if(o.promo_condition)content.appendChild",html)


if __name__=='__main__':unittest.main()
