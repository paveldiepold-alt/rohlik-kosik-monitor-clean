"""Local audit of a monitor JSON report. Usage: python tools/audit_snapshot.py path/to/latest.json"""
import collections
import json
import sys
from pathlib import Path

def verified_pair_count(rows):
    lookup={r.get('url'):r for r in rows if r.get('url')}
    pairs=set()
    for a in rows:
        if not (a.get('price_verified') and isinstance(a.get('price'),(float,int)) and a['price']>0):continue
        b=lookup.get(a.get('other_shop_url'))
        if not b or b.get('shop')==a.get('shop') or b.get('other_shop_url')!=a.get('url'):continue
        if not (b.get('price_verified') and isinstance(b.get('price'),(float,int)) and b['price']>0):continue
        if not (isinstance(a.get('other_shop_price'),(float,int)) and isinstance(b.get('other_shop_price'),(float,int))):continue
        if abs(a['other_shop_price']-b['price'])>.02 or abs(b['other_shop_price']-a['price'])>.02:continue
        if a.get('quantity')!=b.get('quantity'):continue
        pairs.add(tuple(sorted([a['url'],b['url']])))
    return len(pairs)

def audit(data):
    rows=data.get('catalog',[])
    priced=[r for r in rows if r.get('price_verified') is True and isinstance(r.get('price'),(float,int)) and r['price']>0]
    by_url={r.get('url'):r for r in rows if r.get('url')}
    sales=[]
    for r in data.get('offers',[]):
        item=by_url.get(r.get('url'))
        if not item:continue
        if not (item.get('price_verified') and item.get('discount_verified')):continue
        if not isinstance(r.get('price'),(float,int)) or not isinstance(item.get('price'),(float,int)):continue
        if r['price']<=0 or abs(item['price']-r['price'])>0.02:continue
        if not isinstance(r.get('discount_pct'),(int,float)) or r['discount_pct']<=0:continue
        sales.append(r)
    return {'report_checked_at':data.get('checked_at'),'catalog_records':len(rows),'priced_records':len(priced),
      'records_without_verified_price':len(rows)-len(priced),'verified_discount_records':len(sales),
      'verified_cross_shop_pairs':verified_pair_count(rows),'sale_categories':dict(collections.Counter(r.get('category','') for r in sales)),
      'complete_catalog_verified':data.get('catalog_coverage',{}).get('catalog_completeness_verified',False)}

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Použití: python tools/audit_snapshot.py soubor_latest.json')
    print(json.dumps(audit(json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))),ensure_ascii=False,indent=2))
