import sys, time, subprocess, json, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path("execution").resolve()))
PORT="8815"; BASE=f"http://127.0.0.1:{PORT}"; EMAIL="gearfree@test.com"
proc=subprocess.Popen([sys.executable,"-m","uvicorn","execution.api_server:app","--port",PORT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        try: urllib.request.urlopen(BASE+"/web",timeout=1); break
        except Exception: time.sleep(0.5)
    body=json.dumps({"email":EMAIL,"password":"secreta123","name":"GearFree","accept_terms":True,"confirm_adult":True}).encode()
    reg=json.loads(urllib.request.urlopen(urllib.request.Request(BASE+"/auth/register",data=body,headers={"Content-Type":"application/json"},method="POST"),timeout=5).read())
    token=reg["token"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True); pg=b.new_page(viewport={"width":1200,"height":800})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto(BASE+"/chat"); pg.evaluate("t=>localStorage.setItem('h2ai_token',t)",token); pg.goto(BASE+"/chat")
        time.sleep(1.5)  # initSession
        is_admin=pg.evaluate("()=>window._isAdmin")
        pg.click("#settingsBtn"); time.sleep(0.8)
        visible=pg.is_visible("#userPrefsModal")
        rmax=pg.get_attribute("#prefsRounds","max"); tmax=pg.get_attribute("#prefsTokens","max")
        creat=len(pg.query_selector_all("#prefsCreativity button"))
        plan=pg.inner_text("#prefsPlan")
        pg.screenshot(path=str(Path(__file__).resolve().parent/"smoke_user_gear.png"))
        print(f"is_admin={is_admin} | panel visible={visible} | plan={plan!r} | rondas_max={rmax} | tokens_max={tmax} | botones_creatividad={creat} | JS_err={errs}")
        b.close()
finally:
    proc.terminate()
    try:
        from engine import ConversationEngine
        import auth
        e=ConversationEngine(); c=e._get_conn()
        row=c.execute("SELECT id FROM users WHERE email=?", (EMAIL,)).fetchone(); c.close()
        if row: auth.delete_account(e, row[0])
        c=e._get_conn(); c.execute("DELETE FROM user_prefs WHERE user_id NOT IN (SELECT id FROM users)"); c.commit(); c.close()
    except Exception as ex: print("limpieza:",ex)
