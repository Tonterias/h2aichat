import sys, time, subprocess, urllib.request, json
from pathlib import Path
sys.path.insert(0, str(Path("execution").resolve()))
import auth
from engine import ConversationEngine
PORT="8817"; BASE=f"http://127.0.0.1:{PORT}"
# crear un usuario de prueba para ver la fila
e=ConversationEngine()
proc=subprocess.Popen([sys.executable,"-m","uvicorn","execution.api_server:app","--port",PORT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        try: urllib.request.urlopen(BASE+"/admin",timeout=1); break
        except Exception: time.sleep(0.5)
    try:
        auth.register_user(e,"rowtest@test.com","secreta123","Row",accept_terms=True,confirm_adult=True)
    except Exception: pass
    token=auth.create_token(0,"contact@h2aichat.com","admin","premium")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True); pg=b.new_page(viewport={"width":1200,"height":950})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto(BASE+"/admin"); pg.evaluate("t=>localStorage.setItem('h2ai_token',t)",token); pg.goto(BASE+"/admin")
        pg.wait_for_selector("#usersTable .plansel",timeout=8000)
        sels=len(pg.query_selector_all("#usersTable .plansel"))
        packs=len(pg.query_selector_all("#usersTable .pack"))
        opts=pg.eval_on_selector("#usersTable .plansel","s=>Array.from(s.options).map(o=>o.value)")
        # hover para ver una leyenda
        pg.hover("#usersTable .pack.danger-pack .danger"); time.sleep(0.5)
        pg.eval_on_selector("#usersTable","e=>e.scrollIntoView()"); time.sleep(0.3)
        pg.screenshot(path=str(Path(__file__).resolve().parent/"smoke_admin_users.png"))
        print(f"desplegables de plan: {sels} | opciones: {opts} | packs: {packs} | JS err: {errs}")
        b.close()
finally:
    proc.terminate()
    c=e._get_conn(); row=c.execute("SELECT id FROM users WHERE email='rowtest@test.com'").fetchone(); c.close()
    if row: auth.delete_account(e,row[0])
