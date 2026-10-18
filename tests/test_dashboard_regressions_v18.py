"""Regression cases for disappearing promos / misleading dashboard statuses."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog_scan
import monitor

CFG = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text(encoding='utf-8'))
NOW = dt.datetime(2026, 10, 18, 18, 33, tzinfo=dt.timezone(dt.timedelta(hours=2)))


class V18DashboardRegressions(unittest.TestCase):
    def test_orion_koko_but_not_other_coconut_sweets(self):
        rule = monitor.match_rules('Orion Koko kokosová tyčinka máčená v mléčné polevě', CFG['watch_rules'])
        self.assertEqual(rule['id'], 'W051')
        self.assertEqual(monitor.match_rules('Opavia Miňonky kakaové oplatky',CFG['watch_rules'])['id'],'W049')
        for name in ['BiOpekárna Zemanka BIO Čoko-kokosky s kakaem',
                     'Kokosky sladké pečivo 100 g']:
            rule = monitor.match_rules(name, CFG['watch_rules'])
            self.assertFalse(rule and rule.get('id') == 'W051')

    def test_disappearing_sale_page_offers_preserved_by_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            (temp / 'docs').mkdir()
            (temp / 'docs' / 'data').mkdir()
            cfg = copy.deepcopy(CFG)
            cfg['catalog_search']['max_queries_per_run'] = 2
            original_root, original_data = monitor.ROOT, monitor.DATA
            monitor.ROOT, monitor.DATA = temp, temp / 'docs' / 'data'
            # Real matching/parsing for Košík, without running a browser.
            sample = dict(name="Hellmann's Majonéza 625 ml",
                          url='https://www.kosik.cz/p459210-hellmann-s-majoneza',
                          card="74,90 Kč 129,90 Kč -42 % Hellmann's Majonéza 625 ml",
                          current_price='74,90 Kč', old_price='129,90 Kč')
            sample_offer = monitor.classify_rows('Košík',[sample],cfg)
            self.assertEqual(len(sample_offer),1)
            called = []
            def fallback(shop, url, limit, max_rounds=16):
                called.append(shop)
                if len(called) <= 2:
                    return ([sample], 'ok', {}) if shop == 'Košík' else ([], 'ok', {})
                return [], 'error', {}
            def finder(batch, cfg):
                result = {}
                for job in batch:
                    # A successful query at Rohlík must NOT disable Košík fallback.
                    success = job['shop'] == 'Rohlík'
                    result[catalog_scan.job_key(job)] = dict(
                        status='ok' if success else 'search_unavailable',
                        detail='fixture',items=[dict(name='Kuřecí prsa',url='https://www.rohlik.cz/1353879-kureci-prsni-rizky-od-ceskeho-vyrobce',card='Kuřecí prsa 100 g',current_price='')]
                              if success else [])
                return result
            try:
                with patch.object(catalog_scan,'playwright_search_batch',side_effect=finder), \
                     patch.object(monitor,'fetch_shop',side_effect=fallback), \
                     patch.object(monitor,'enrich_from_product_pages',return_value={'visited':0,'filled':0,'errors':0,'photos_cached':0}):
                    self.assertEqual(catalog_scan.run_catalog_monitor(cfg,monitor),0)
                    first=json.loads((monitor.DATA/'latest.json').read_text(encoding='utf-8'))
                    self.assertTrue(any(x['shop']=='Košík' for x in first['offers']))
                    self.assertEqual(len(first['changes']),1)
                    self.assertEqual(first['catalog_coverage']['sale_page_fallback']['Košík']['status'],'ok')
                    self.assertEqual(catalog_scan.run_catalog_monitor(cfg,monitor),0)
                    second=json.loads((monitor.DATA/'latest.json').read_text(encoding='utf-8'))
                    self.assertTrue(any(x['shop']=='Košík' for x in second['offers']), 'Do not erase still-fresh verified offer on failed rescan')
                    self.assertEqual(len(second['changes']),0, 'Do not call old item newly observed after skipped rescan')
                    self.assertEqual(len(called),4, 'Fallback must be attempted in both runs even if search worked yesterday')
            finally:
                monitor.ROOT, monitor.DATA = original_root, original_data

    def test_old_price_is_not_renewed_by_null_search_price(self):
        job=catalog_scan.plan_jobs(CFG)[0]
        product_url='https://www.rohlik.cz/1353879-kureci-prsni-rizky-od-ceskeho-vyrobce'
        earlier=(NOW-dt.timedelta(hours=17)).isoformat(timespec='minutes')
        product = dict(url=product_url,shop='Rohlík',name='Kuřecí prsní řízky od českého výrobce',price=99.0,
                       discount_pct=12,discount_verified=True,price_verified=True,
                       checked_at=earlier,old_price=112.0,terms='akce',quantity='500 g',
                       image_url='',brand='Maso',favorite=True,category='Maso',rule_id='W001')
        row = dict(url=product_url,name=product['name'],card=product['name'],current_price='')
        state={'items':{product_url:product},'queries':{}}
        state,out=catalog_scan.process_incremental(CFG,NOW,state,[job],[job],{
            catalog_scan.job_key(job):dict(status='ok',items=[row],detail='fixture')},monitor)
        self.assertEqual(state['items'][product_url]['checked_at'],earlier,
                         'Do not label old verified price as freshly checked')
        state,out=catalog_scan.process_incremental(CFG,NOW+dt.timedelta(hours=2),state,[job],[],{},monitor)
        self.assertEqual(len(out['offers']),0,'Price must expire instead of masquerading as current')

if __name__=='__main__': unittest.main()
