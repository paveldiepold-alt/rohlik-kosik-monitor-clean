import datetime as dt, json, unittest
from pathlib import Path
import monitor as lib
from catalog_scan import process_incremental, plan_jobs, job_key
CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf8'))
NOW=dt.datetime(2026,10,18,18,33,tzinfo=dt.timezone(dt.timedelta(hours=2)))

class RegressionV17(unittest.TestCase):
    def test_pet_food_never_raw_meat(self):
        names=['Applaws Cat miska kuřecí prsa s kachnou pro kočky',
               'Applaws Cat kapsička kuřecí prsa a divoká rýže pro kočky',
               'Applaws Cat Kitten kapsička kuřecí prsa',
               'Kuřecí prsní řízky s kostí 600 g']
        for name in names:
            with self.subTest(name=name):
                match=lib.match_rules(name,CFG['watch_rules'])
                self.assertFalse(match and match['category']=='Maso')
    def test_raw_chicken_allowed(self):
        self.assertEqual(lib.match_rules('Kuřecí prsní řízky bez kosti 600 g',CFG['watch_rules'])['category'],'Maso')
    def test_cached_false_positives_removed(self):
        url='https://www.rohlik.cz/1457756-applaws-cat-miska'
        state={'items':{url:{'url':url,'name':'Applaws Cat miska kuřecí prsa s kachnou pro kočky',
             'category':'Maso','rule_id':'W001','checked_at':NOW.isoformat(), 'price':None}},'queries':{}}
        state,out=process_incremental(CFG,NOW,state,plan_jobs(CFG),[],{},lib)
        self.assertEqual(out['catalog'],[])
        self.assertEqual(state['items'],{})
    def test_rolling_coverage_counts_one_old_success(self):
        job=plan_jobs(CFG)[0]
        state={'items':{},'queries':{job_key(job):{
            'checked_at':(NOW-dt.timedelta(hours=40)).isoformat(),'status':'ok',
            'cards':2,'rule_ids':job['rule_ids']}}}
        _,out=process_incremental(CFG,NOW,state,plan_jobs(CFG),[],{},lib)
        self.assertEqual(out['coverage']['queries_responded_24h'],0)
        self.assertEqual(out['coverage']['queries_responded_window'],1)
    def test_explicit_price_verification(self):
        self.assertGreater(CFG['catalog_search']['cache_retention_hours'],CFG['catalog_search']['price_max_age_hours'])
