import pytest
import subprocess
import time
import urllib.request
from pathlib import Path


@pytest.fixture(scope="session")
def server():
    root = Path(__file__).parent.parent.parent
    db = root / "memory" / "humania.db"
    locks = root / "memory" / ".locks"
    if db.exists():
        db.unlink()
    if locks.exists():
        import shutil
        shutil.rmtree(str(locks), ignore_errors=True)

    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "execution.api_server:app",
         "--port", "8765", "--host", "127.0.0.1"],
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/status", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("Server did not start within 10s")

    yield "http://127.0.0.1:8765"

    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            # FASE 37.1: playwright instalado pero SIN el binario del navegador (p. ej. en el CI,
            # que no corre `playwright install`). Antes se saltaba por no tener el paquete; ahora
            # que el paquete SÍ está (via requirements-dev.txt) hay que saltar también aquí.
            pytest.skip(f"navegador de playwright no disponible ({str(e)[:60]}); ejecuta `playwright install chromium`")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page()
    # FASE 31: en el chat real el usuario esta SIEMPRE logueado, asi el frontend conoce su email
    # (window.MY_MOD_ID) y reconoce sus propios mensajes como del moderador. El servidor de test
    # va sin login (dev), donde initSession() no llega a fijar esa identidad; se inyecta la del
    # usuario dev (DEV_USER: dev@local) para reproducir el estado logueado real.
    pg.add_init_script("window.MY_MOD_ID='dev@local';window.MY_NAME='dev';")
    pg.goto(server)
    pg.wait_for_load_state("networkidle")
    yield pg
    pg.close()
