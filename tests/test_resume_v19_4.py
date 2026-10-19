"""Coverage and resume tests for 19.4 – never require live retailer access."""
import datetime as dt
import json
import unittest
from pathlib import Path

import monitor as lib
from catalog_scan import (plan_jobs, scan_plan_signature, resume_plan,
                          advance_scan_progress, process_incremental, job_key,
                          SCAN_PLAN_VERSION)

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))
NOW=dt.datetime(2026,10,19,9,0,tzinfo=dt.timezone(dt.timedelta(hours=2)))

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.jobs=plan_jobs(CFG)
        self.assertGreater(len(self.jobs),100)

    def test_initial_run_schedules_full_food_first_dynamic_plan(self):
        run,start=resume_plan(self.jobs,{})
        self.assertEqual(run,self.jobs)
        self.assertEqual(start,{'Rohlík':0,'Košík':0})
        self.assertEqual(SCAN_PLAN_VERSION,'food-first-resume-partial-19.4')

    def test_resume_after_time_limit_at_next_unfinished_query(self):
        first=self.jobs[:20]
        result={job_key(j):{'status':'ok','items':[]} for j in first}
        # A 429 at position 12 should pause Rohlík only; Košík can progress.
        result[job_key(first[12])]['status']='rate_limited'
        result[job_key(first[14])]['status']='skipped_rate_limit'
        result[job_key(first[16])]['status']='skipped_rate_limit'
        result[job_key(first[18])]['status']='skipped_rate_limit'
        pos=advance_scan_progress(self.jobs,first,result,{'Rohlík':0,'Košík':0})
        self.assertEqual(pos['Rohlík'],6)
        self.assertEqual(pos['Košík'],10)
        next_run, start=resume_plan(self.jobs, {'scan_progress':pos,'scan_plan_signature':scan_plan_signature(self.jobs)})
        self.assertEqual(start,pos)
        self.assertEqual(next_run[0],self.jobs[12])
        self.assertNotIn(self.jobs[1],next_run)

    def test_end_of_cycle_resets_shop_and_new_rules_invalidate_progress(self):
        shoplen=len(self.jobs)//2
        old={'scan_progress':{'Rohlík':shoplen,'Košík':shoplen-5},'scan_plan_signature':scan_plan_signature(self.jobs)}
        batch,start=resume_plan(self.jobs,old)
        self.assertEqual(start['Rohlík'],0)
        self.assertEqual(start['Košík'],shoplen-5)
        self.assertEqual(batch[0],self.jobs[0])
        newer=json.loads(json.dumps(CFG))
        newer['watch_rules'].append({'id':'W998','category':'Sladké','label':'Nový výrobek','product_any':['Nový výrobek']})
        new_jobs=plan_jobs(newer)
        batch,start=resume_plan(new_jobs,old)
        self.assertEqual(batch,new_jobs)
        self.assertEqual(start['Rohlík'],0)

    def test_skipped_status_preserves_previous_real_check(self):
        j=self.jobs[0]; k=job_key(j)
        state={'items':{},'queries':{k:{'checked_at':(NOW-dt.timedelta(hours=1)).isoformat(),
                   'status':'ok','cards':20,'rule_ids':j['rule_ids']}}}
        updated, output=process_incremental(CFG,NOW,state,self.jobs,[j],{k:{'status':'skipped_time_budget','items':[]}},lib)
        self.assertEqual(updated['queries'][k]['status'],'ok')
        self.assertEqual(output['coverage']['queries_responded_24h'],1)
        self.assertEqual(output['coverage']['run_skipped'],1)
        self.assertEqual(output['coverage']['run_attempted'],0)

    def test_true_errors_and_empty_results_separate(self):
        j1,j2=self.jobs[:2]
        results={job_key(j1):{'status':'no_cards','items':[]},
                 job_key(j2):{'status':'error','items':[]}}
        _, out=process_incremental(CFG,NOW,{},self.jobs,[j1,j2],results,lib)
        self.assertEqual(out['coverage']['run_no_cards'],1)
        self.assertEqual(out['coverage']['failed_queries_24h'],1)
        self.assertEqual(out['coverage']['run_attempted'],2)

if __name__=='__main__':unittest.main()
