import json
from pathlib import Path
from playwright.sync_api import sync_playwright
SRC=Path(__file__).resolve().parents[1]/'docs'/'index.html'
sample={
      'date':'2026-10-18', 'checked_at':'2026-10-18T15:30:00+02:00', 'demo':True,
      'delivery':{'postal_code':'149 00'},'sources':{},'changes':[],
      'offers':[
      {'favorite':False,'category':'Majonézy','brand':'Hellmann','name':"Hellmann's Majonéza", 'shop':'Košík', 'price':74.9,'discount_pct':42,'quantity':'625 ml','unit_price':119.84,'unit_label':'Kč/l','image_url':'','terms':'akce','other_shop_price':None,'url':'https://www.kosik.cz/p459210-hellmann-s-majoneza'},
      {'favorite':False,'category':'Majonézy','brand':'Hellmann','name':"Hellmann's Majonéza", 'shop':'Košík', 'price':46.9,'discount_pct':47,'quantity':'405 ml','unit_price':115.8,'unit_label':'Kč/l','image_url':'','terms':'akce','other_shop_price':None,'url':'https://www.kosik.cz/p00010-hellmann-s-majoneza'},
      {'favorite':True,'category':'Zelenina','brand':'Mrkev','name':'BIO Mrkev, balení','shop':'Rohlík','price':39.95,'discount_pct':37,'quantity':'500 g','unit_price':79.90,'unit_label':'Kč/kg','image_url':'','terms':'akce','other_shop_price':None,'url':'https://www.rohlik.cz/1234567-mrkev'}
     ]}

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':920},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda err: errors.append(str(err)))
    snap=json.dumps(sample,ensure_ascii=False)
    page.evaluate("window.fetch=async u=>({ok:true,json:async()=> (String(u).includes('index.json')?[]:JSON.parse("+json.dumps(snap)+"))})")
    page.set_content(SRC.read_text(encoding='utf-8'))
    page.wait_for_timeout(550)
    print('ROWS',page.locator('tbody tr').count())
    print('TEXT',page.locator('tbody tr').first.inner_text()[:260])
    print('ERRORS',errors)
    page.screenshot(path='/mnt/data/Rohlik_Kosik_v10_Dashboard_Ukazka.png',full_page=True)
    assert not errors,errors
    assert page.locator('tbody tr').count()==3
    assert page.locator('.pack-chip').count()==3
    browser.close()
