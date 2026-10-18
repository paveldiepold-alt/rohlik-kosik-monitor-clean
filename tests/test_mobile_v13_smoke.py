"""Browser smoke: mobile cards, quick filters, photo fallback, and desktop table."""
import json, tempfile, threading, functools
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

DOCS=Path(__file__).resolve().parents[1]/'docs'
def offer(name,category,brand,shop,price,discount,quantity,url,rule_id):
 return {'rule_id':rule_id,'favorite':True,'category':category,'brand':brand,'name':name,'shop':shop,'price':price,'discount_pct':discount,'quantity':quantity,'unit_label':'Kč/l' if 'ml' in quantity else 'Kč/kg','unit_price':price/(0.625 if quantity=='625 ml' else (0.405 if quantity=='405 ml' else 0.8)),'image_url':'','terms':'akce','other_shop_price':None,'url':url}
mock={'date':'2026-10-18','checked_at':'2026-10-18T16:20:00+02:00','delivery':{'postal_code':'149 00'},'demo':True,'changes':[],'sources':{},'offers':[
 offer('Hellmann\'s Majonéza','Majonézy','Hellmann','Košík',74.9,42,'625 ml','https://www.kosik.cz/p459210-hellmann-s-majoneza','W029'),
 offer('Hellmann\'s Majonéza','Majonézy','Hellmann','Košík',46.9,47,'405 ml','https://www.kosik.cz/p459240-hellmann-s-majoneza','W029'),
 offer('Hrozny tmavé volně (odr. Red globe), cca 0,8 kg, -50 % pro vás','Ovoce','Hroznové víno','Rohlík',111.92,50,'0,8 kg','https://www.rohlik.cz/1354562','W045'),
 offer('Leerdammer Original sýr plátky, 100 g','Sýry / plátkové','Leerdammer','Rohlík',52.4,27,'100 g','https://www.rohlik.cz/1334562','W023'),
 offer('BIO Mrkev balení cca 500 g','Zelenina','Mrkev','Rohlík',39.95,37,'500 g','https://www.rohlik.cz/1344562','W048'),
]}

def test_browser():
 with tempfile.TemporaryDirectory() as t:
  base=Path(t);(base/'data').mkdir()
  (base/'index.html').write_text((DOCS/'index.html').read_text(encoding='utf8'),encoding='utf8')
  (base/'data/latest.json').write_text(json.dumps(mock,ensure_ascii=False),encoding='utf8')
  (base/'data/index.json').write_text('[]')
  class Quiet(SimpleHTTPRequestHandler):
   def log_message(self,*args):pass
  handler=functools.partial(Quiet,directory=str(base))
  srv=ThreadingHTTPServer(('127.0.0.1',0),handler)
  threading.Thread(target=srv.serve_forever,daemon=True).start()
  url=f'http://127.0.0.1:{srv.server_port}/'
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   for width,height,filename in [(320,750,'rk_v13_320_tmp.png'),(390,844,'Rohlik_Kosik_v13_mobil.png'),(430,900,'rk_v13_430_tmp.png'),(1440,900,'Rohlik_Kosik_v13_desktop.png')]:
    page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda err: errors.append(str(err)))
    page.goto('about:blank')
    page.evaluate("window.fetch=async u=>({ok:true,json:async()=>String(u).includes('index.json')?[]:JSON.parse("+json.dumps(json.dumps(mock,ensure_ascii=False))+"),status:200})")
    page.set_content((DOCS/'index.html').read_text(encoding='utf8'),wait_until='domcontentloaded')
    page.wait_for_timeout(400)
    assert page.locator('.item-card').count()==5, f"No cards {page.locator('.item-card').count()}; errors={errors}"
    assert page.locator('#body tr').count()==5
    assert any('74,90 Kč' in t for t in page.locator('.item-card').all_inner_texts())
    assert 'Otevřít na' in page.locator('.item-card').first.inner_text()
    assert page.locator('.item-card img').count()>=1, 'Known exact 625ml product image not rendered'
    assert page.locator('img[src^="data:image/webp"]').count()>=1
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1') if width<=768 else True
    if width<=768:
     assert page.locator('.gridwrap').is_hidden()
     page.locator('[data-quick="favorites"]').click()
     assert page.locator('.item-card').count()==5
     page.locator('[data-quick="Košík"]').click()
     assert page.locator('.item-card').count()==2
     page.locator('[data-quick="all"]').click()
     page.locator('#filter-toggle').click()
     assert page.locator('#brand').is_visible()
     page.locator('#search').fill('Leerdammer')
     assert page.locator('.item-card').count()==1
     page.locator('#search').fill('')
     page.locator('#filter-toggle').click()
     page.locator('#mobile-sort').select_option('price')
     assert '39,95' in page.locator('.item-card').first.inner_text()
     page.locator('#mobile-sort').select_option('discount')
     page.screenshot(path='/mnt/data/'+filename,full_page=True)
    else:
     assert page.locator('.gridwrap').is_visible()
     page.screenshot(path='/mnt/data/'+filename,full_page=True)
    assert not errors,errors
    page.close()
   browser.close()
  srv.shutdown()

if __name__=='__main__':
 test_browser();print('PASS v13 desktop/mobile browser smoke')
