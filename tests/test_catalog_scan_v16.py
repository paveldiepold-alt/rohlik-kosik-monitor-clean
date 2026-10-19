"""Tests for public shop searches across full assortment, independent of internet."""
import datetime as dt
import json
import unittest
from pathlib import Path
import monitor as lib
from catalog_scan import plan_queries, plan_jobs, choose_batch, job_key, row_to_product, process_incremental, compare_catalog_items

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))
NOW=dt.datetime(2026,10,18,17,0,tzinfo=dt.timezone(dt.timedelta(hours=2)))

def row(shop,url,name,current='49,90 Kč',card=None,old=''):
    return {'url':url,'name':name,'current_price':current,'old_price':old,
            'card':card or f'{current} {name}', 'image_url':''}

class WholeCatalogueV16(unittest.TestCase):
    def test_every_rule_covered_both_shops(self):
        plans=plan_queries(CFG)
        jobs=plan_jobs(CFG)
        ids={r['id'] for r in CFG['watch_rules'] if r.get('enabled') is not False}
        self.assertEqual(ids, set(r for p in plans for r in p['rule_ids']))
        self.assertEqual(len(jobs),2*len(plans))
        self.assertTrue(CFG['catalog_search']['enabled'])
        self.assertTrue(any(x['query']=='Aquila' for x in plans))
        self.assertTrue(any(x['query']=='kuchyňské papírové utěrky' for x in plans))
        self.assertTrue(any(x['query']=='Colgate' for x in plans))
    def test_single_full_run_includes_every_query(self):
        jobs=plan_jobs(CFG)
        batch_size=len(jobs)  # dynamicky počet dotazů podle aktuálních pravidel
        batch,cursor=choose_batch(jobs,0,batch_size)
        self.assertEqual(list(map(job_key,batch)),list(map(job_key,jobs)))
        self.assertEqual(cursor,0)
    def test_more_than_196_products_can_be_stored_from_one_query(self):
        # 196 is not, and never was, a product-count ceiling.
        job={'shop':'Košík','query':'Hellmann','rule_ids':['W027']}
        rows=[row('Košík',f'https://www.kosik.cz/p{500000+i}-majoneza',
                  f"Hellmann's Majonéza Original balení {i} 625 ml") for i in range(220)]
        _, result=process_incremental(CFG,NOW,{},plan_jobs(CFG),[job],
            {job_key(job):{'status':'ok','items':rows}},lib)
        self.assertEqual(len(result['catalog']),220)
        self.assertEqual(result['coverage']['batch_product_rows_matched'],220)

    def test_skipped_rate_limited_jobs_not_counted_as_checked(self):
        jobs=plan_jobs(CFG)
        sample=jobs[:4]
        statuses=('ok','skipped_rate_limit','search_unavailable','skipped_time_budget')
        results={job_key(j):{'status':status,'items':[]} for j,status in zip(sample,statuses)}
        _,out=process_incremental(CFG,NOW,{},jobs,sample,results,lib)
        self.assertEqual(out['coverage']['queries_checked_24h'],2)
        self.assertEqual(out['coverage']['queries_responded_24h'],1)
        self.assertEqual(out['coverage']['batch_errors'],3)

    def test_regular_price_in_catalog(self):
        r=row('Košík','https://www.kosik.cz/p123456-majoneza',"Hellmann's Majonéza 625 ml")
        p=row_to_product('Košík',r,CFG,lib,NOW.isoformat())
        self.assertIsNotNone(p)
        self.assertEqual(p['price'],49.9)
        self.assertEqual(p['discount_pct'],0)
        self.assertFalse(p['discount_verified'])
        self.assertTrue(p['favorite'])
    def test_discount_not_needed_for_catalog(self):
        r=row('Rohlík','https://www.rohlik.cz/1234567-kureci-prsni-rizky','Kuřecí prsní řízky 800 g')
        p=row_to_product('Rohlík',r,CFG,lib,NOW.isoformat())
        self.assertEqual(p['category'],'Maso')
        self.assertEqual(p['terms'],'běžná nabídka')
    def test_unwanted_processed_meat_never_catalogued(self):
        r=row('Rohlík','https://www.rohlik.cz/1234567-jerky','Just Meat Sušená kuřecí prsa s pepřem')
        self.assertIsNone(row_to_product('Rohlík',r,CFG,lib,NOW.isoformat()))
    def test_discounts_stay_in_sale_view_only_when_verified(self):
        r=row('Košík','https://www.kosik.cz/p123457-majoneza',"Hellmann's Majonéza 625 ml",
              current='74,90 Kč',old='129,90 Kč',
              card="74,90 Kč 129,90 Kč -42 % Hellmann's Majonéza 625 ml")
        job={'shop':'Košík','query':'Hellmann','rule_ids':['W027']}
        state,output=process_incremental(CFG,NOW,{},plan_jobs(CFG),[job],
            {job_key(job):{'status':'ok','items':[r]}},lib)
        self.assertEqual(len(output['catalog']),1)
        self.assertEqual(len(output['offers']),1)
        self.assertEqual(output['offers'][0].discount_pct,42)
        self.assertEqual(output['offers'][0].price,74.9)
        self.assertEqual(output['coverage']['batch_product_rows_matched'],1)
    def test_non_sale_product_not_labeled_new_discount(self):
        r=row('Košík','https://www.kosik.cz/p123457-majoneza',"Hellmann's Majonéza 625 ml")
        job={'shop':'Košík','query':'Hellmann','rule_ids':['W027']}
        _,output=process_incremental(CFG,NOW,{},plan_jobs(CFG),[job],
            {job_key(job):{'status':'ok','items':[r]}},lib)
        self.assertEqual(len(output['catalog']),1)
        self.assertEqual(len(output['offers']),0)
    def test_errors_do_not_erase_previous_prices(self):
        old=row_to_product('Košík',row('Košík','https://www.kosik.cz/p123457-majoneza',"Hellmann's Majonéza 625 ml"),CFG,lib,NOW.isoformat())
        job={'shop':'Košík','query':'Hellmann','rule_ids':['W027']}
        state={'cursor':0,'items':{old['url']:old},'queries':{}}
        new,out=process_incremental(CFG,NOW,state,plan_jobs(CFG),[job],
            {job_key(job):{'status':'error','items':[]}},lib)
        self.assertEqual(len(out['catalog']),1)
        self.assertEqual(out['coverage']['batch_errors'],1)
        self.assertEqual(new['queries'][job_key(job)]['status'],'error')
    def test_stale_data_not_used_as_current(self):
        old=row_to_product('Košík',row('Košík','https://www.kosik.cz/p123457-majoneza',"Hellmann's Majonéza 625 ml"),CFG,lib,(NOW-dt.timedelta(hours=30)).isoformat())
        state={'items':{old['url']:old},'queries':{}}
        _,out=process_incremental(CFG,NOW,state,plan_jobs(CFG),[],{},lib)
        self.assertEqual(out['catalog'],[])
    def test_catalog_cross_store_comparison_requires_exact_variant(self):
        base={'price':50.,'price_verified':True,'terms':'běžná nabídka','quantity':'625 ml','name':"Hellmann's Majonéza 625 ml",'shop':'Rohlík','url':'https://www.rohlik.cz/1111111-test'}
        a=dict(base);b=dict(base, shop='Košík',url='https://www.kosik.cz/p1111111-test',price=48.)
        compare_catalog_items([a,b],lib)
        self.assertEqual(a['other_shop_price'],48.)
        c=dict(base,shop='Košík',url='https://www.kosik.cz/p1111112-test',quantity='405 ml')
        d=dict(base);compare_catalog_items([c,d],lib)
        self.assertNotIn('other_shop_price',d)

if __name__=='__main__':unittest.main()
