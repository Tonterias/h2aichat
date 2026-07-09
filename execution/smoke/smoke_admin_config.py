import sys, time, subprocess, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path("execution").resolve()))
import auth
PORT="8818"; BASE=f"http://127.0.0.1:{PORT}"
proc=subprocess.Popen([sys.executable,"-m","uvicorn","execution.api_server:app","--port",PORT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        try: urllib.request.urlopen(BASE+"/admin",timeout=1); break
        except Exception: time.sleep(0.5)
    token=auth.create_token(0,"contact@h2aichat.com","admin","premium")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True); pg=b.new_page(viewport={"width":1100,"height":1100})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto(BASE+"/admin"); pg.evaluate("t=>localStorage.setItem('h2ai_token',t)",token); pg.goto(BASE+"/admin")
        pg.wait_for_selector("#appConfig input",timeout=8000)
        ins=len(pg.query_selector_all("#appConfig input"))
        has_to=pg.query_selector("#ac_orchestrate_llm_timeout") is not None
        has_delay=pg.query_selector("#ac_orchestrate_bot_delay") is not None
        has_prof=("Económico" in pg.content() and "Premium" in pg.content())
        pg.eval_on_selector("#appConfig","e=>e.scrollIntoView()"); time.sleep(0.4)
        pg.screenshot(path=str(Path(__file__).resolve().parent/"smoke_admin_config.png"))
        print(f"campos sistema: {ins} | timeout={has_to} delay={has_delay} | perfiles={has_prof} | JS_err={errs}")
        b.close()
finally:
    proc.terminate()
