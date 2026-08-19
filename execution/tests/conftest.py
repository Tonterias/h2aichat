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
            # playwright installed but WITHOUT the browser binary, which happens in CI when
            # `playwright install` has not run. It used to skip for lack of the package; now that
            # the package IS there through requirements-dev.txt, it has to skip here too.
            pytest.skip(f"navegador de playwright no disponible ({str(e)[:60]}); ejecuta `playwright install chromium`")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page()
    # In the real chat the user is ALWAYS logged in, so the frontend knows their address
    # (window.MY_MOD_ID) and recognises their own messages as the moderator's. The test server
    # runs without a login, where initSession() never sets that identity, so the dev user's
    # identity is injected to reproduce the real logged-in state.
    pg.add_init_script("window.MY_MOD_ID='dev@local';window.MY_NAME='dev';")
    pg.goto(server)
    pg.wait_for_load_state("networkidle")
    yield pg
    pg.close()
