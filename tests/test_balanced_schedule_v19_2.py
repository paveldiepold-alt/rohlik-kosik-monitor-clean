"""Regression tests for food-first entire catalogue checks (v19.3)."""
import json
import unittest
from pathlib import Path
from catalog_scan import (SCAN_PLAN_VERSION, FOOD_CATEGORY_ORDER, balanced_queries,
                          plan_queries, plan_jobs, choose_batch, job_key)
from copy import deepcopy

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text('utf-8'))

class FoodFirstFullScanTests(unittest.TestCase):
    def test_all_queries_checked_in_one_run_without_duplicates(self):
        jobs=plan_jobs(CFG)
        self.assertEqual(len(jobs),len(CFG['sources'])*len(plan_queries(CFG)))
        self.assertEqual(len(set(map(job_key,jobs))),len(jobs))
        chosen,_=choose_batch(jobs,0,len(jobs))
        self.assertEqual(list(map(job_key,chosen)),list(map(job_key,jobs)))
        self.assertEqual({rid for j in jobs for rid in j['rule_ids']},
                         {r['id'] for r in CFG['watch_rules'] if r.get('enabled') is not False})
    def test_first_meat_then_sausage_cheese_food_beverages_then_nonfood(self):
        by_id={r['id']:r for r in CFG['watch_rules']}
        items=balanced_queries(CFG)
        categories=[min(FOOD_CATEGORY_ORDER.index(by_id[rid]['category'])
                        for rid in j['rule_ids']) for j in items]
        self.assertEqual(categories,sorted(categories))
        self.assertEqual(by_id[items[0]['rule_ids'][0]]['category'],'Maso')
        food_last=FOOD_CATEGORY_ORDER.index('Těstoviny a rýže')
        drink_first=FOOD_CATEGORY_ORDER.index('Nápoje / vody')
        first_nonfood=FOOD_CATEGORY_ORDER.index('Kapesníky / balíčky')
        self.assertTrue(max(i for i,c in enumerate(categories) if c<=food_last) <
                        min(i for i,c in enumerate(categories) if c>=drink_first))
        self.assertTrue(max(i for i,c in enumerate(categories) if c<first_nonfood) <
                        min(i for i,c in enumerate(categories) if c>=first_nonfood))
        self.assertEqual([j['shop'] for j in plan_jobs(CFG)[:2]],['Rohlík','Košík'])
    def test_new_watch_rule_expands_plan_without_limit(self):
        expanded=deepcopy(CFG)
        expanded['watch_rules'].append({
            'id':'W999', 'category':'Sladké', 'label':'Nově přidaná značka 999',
            'priority':1, 'product_any':['Nově přidaná značka 999']})
        old_jobs=plan_jobs(CFG)
        new_jobs=plan_jobs(expanded)
        self.assertGreater(len(new_jobs),len(old_jobs))
        self.assertEqual(len(new_jobs), len(expanded['sources'])*len(plan_queries(expanded)))
        self.assertEqual(len(choose_batch(new_jobs,0,len(new_jobs))[0]),len(new_jobs))
        self.assertTrue(any(j['query']=='Nově přidaná značka 999' for j in new_jobs))
        # Food remains before drinks/non-food after adding the rule.
        by_id={r['id']:r for r in expanded['watch_rules']}
        ranks=[min(FOOD_CATEGORY_ORDER.index(by_id[rid]['category']) for rid in j['rule_ids'])
               for j in balanced_queries(expanded)]
        self.assertEqual(ranks,sorted(ranks))

    def test_one_daily_cycle_with_guardrails(self):
        self.assertTrue(SCAN_PLAN_VERSION.startswith('food-first'))
        self.assertNotIn('max_queries_per_run',CFG['catalog_search'])
        self.assertLess(CFG['catalog_search']['max_scan_minutes'],50)
        self.assertGreater(CFG['catalog_search']['pause_between_queries_seconds'],0)
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/prices.yml').read_text('utf-8')
        self.assertIn("cron: '25 5 * * *'",workflow)
        self.assertIn('timeout-minutes: 55',workflow)

if __name__=='__main__':unittest.main()
