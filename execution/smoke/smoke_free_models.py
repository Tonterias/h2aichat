import sys, time, subprocess, json, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path("execution").resolve()))
PORT="8819"; BASE=f"http://127.0.0.1:{PORT}"; EMAIL="modelfree@test.com"
proc=subprocess.Popen([sys.executable,"-m","uvicorn","execution.api_server:app","--port",PORT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        try: urllib.request.urlopen(BASE+"/web",timeout=1); break
        except Exception: time.sleep(0.5)
    body=json.dumps({"email":EMAIL,"password":"secreta123","name":"MF","accept_terms":True,"confirm_adult":True}).encode()
    token=json.loads(urllib.request.urlopen(urllib.request.Request(BASE+"/auth/register",data=body,headers={"Content-Type":"application/json"},method="POST"),timeout=5).read())["token"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True); pg=b.new_page(viewport={"width":900,"height":800})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.add_init_script("localStorage.setItem('h2ai_token','%s')"%token)
        pg.goto(BASE+"/chat"); time.sleep(1.5)
        pg.click("#settingsBtn"); time.sleep(0.8)
        boxes=pg.query_selector_all("#prefsModels .pmodel")
        labels=pg.eval_on_selector_all("#prefsModels label","ls=>ls.map(l=>l.textContent.trim())")
        maxtxt=pg.inner_text("#prefsModelsMax")
        pg.screenshot(path=str(Path(__file__).resolve().parent/"smoke_free_models.png"))
        print(f"IAs mostradas (free): {len(boxes)} | {labels} | {maxtxt} | JS_err={errs}")
        b.close()
finally:
    proc.terminate()
    from engine import ConversationEngine; import auth
    e=ConversationEngine(); c=e._get_conn(); row=c.execute("SELECT id FROM users WHERE email=?",(EMAIL,)).fetchone(); c.close()
    if row: auth.delete_account(e,row[0])
