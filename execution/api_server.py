import sys
import json
import os
import traceback
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Query, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse, Response


class _SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        _req_enter()  # FASE 28: peticiones HTTP en vuelo (~usuarios concurrentes)
        # FASE 36.2 (T6): el EMBED necesita que sitios EXTERNOS puedan enmarcar la pagina.
        # Se relaja el anti-clickjacking SOLO en las rutas de embed (`?embed=1` sobre una
        # conversacion o un enlace compartido); el resto del sitio sigue con `DENY`/`'none'`.
        _p = scope.get("path", "")
        _is_embed = (b"embed=1" in scope.get("query_string", b"")
                     and (_p.startswith("/conversations/") or _p.startswith("/c/")))
        _frame_ancestors = b"*" if _is_embed else b"'none'"
        async def _send(msg):
            if msg["type"] == "http.response.start":
                if msg.get("status", 0) >= 500:
                    _http_5xx_inc()  # FASE 28.6: contar errores de servidor
                headers = list(msg.get("headers", []))
                headers = [(k, v) for k, v in headers if k != b"server"]
                headers.extend([
                    (b"cache-control", b"no-cache, no-store, must-revalidate"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    # FASE 20.1-A2: red de seguridad contra XSS en el Markdown de los bots.
                    # 'unsafe-inline' es necesario: la SPA y las paginas de auth llevan JS/CSS inline.
                    # Origenes externos permitidos (hallazgo UAT PO 2026-06-12): iconos Tabler
                    # (cdn.jsdelivr) y video Vimeo de la home dinamica. Nada mas.
                    (b"content-security-policy",
                     b"default-src 'self'; script-src 'self' 'unsafe-inline' https://player.vimeo.com; "
                     b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                     b"font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
                     b"connect-src 'self'; frame-src https://player.vimeo.com; frame-ancestors " + _frame_ancestors),
                ])
                # X-Frame-Options no admite lista blanca: en embed se OMITE (manda el CSP);
                # fuera de embed se mantiene DENY.
                if not _is_embed:
                    headers.append((b"x-frame-options", b"DENY"))
                if os.environ.get("HUMANIA_ENV", "dev") == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                msg = dict(msg, headers=headers)
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        finally:
            _req_exit()
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from engine import ConversationEngine
import auth
import email_sender
import telegram_sender
from lm_studio import LMStudioClient
from opencode_go import OpenCodeGoClient
from openrouter_client import OpenRouterClient
from i18n import TRANSLATIONS, LANGUAGES, render_web, resolve_web_lang, render_gallery
import i18n
import seo
from share_page import render_shared_page
import concurrent.futures
import time as _time
import threading as _threading
import system_metrics
import html as _htmlmod


def _html_escape(s):
    return _htmlmod.escape(s or "", quote=True)

# ── FASE 28: contadores "en vuelo" para el medidor de capacidad y la prueba de carga ──
# Dos perillas separadas (como pidió el PO): peticiones HTTP en vuelo ≈ usuarios
# concurrentes; orquestaciones en curso = la carga pesada real. Thread-safe + pico.
_inflight_lock = _threading.Lock()
_inflight = {"orch": 0, "requests": 0}
_inflight_peak = {"orch": 0, "requests": 0}


def _req_enter():
    with _inflight_lock:
        _inflight["requests"] += 1
        if _inflight["requests"] > _inflight_peak["requests"]:
            _inflight_peak["requests"] = _inflight["requests"]


def _req_exit():
    with _inflight_lock:
        _inflight["requests"] = max(0, _inflight["requests"] - 1)


def _orch_enter():
    with _inflight_lock:
        _inflight["orch"] += 1
        if _inflight["orch"] > _inflight_peak["orch"]:
            _inflight_peak["orch"] = _inflight["orch"]


def _orch_exit():
    with _inflight_lock:
        _inflight["orch"] = max(0, _inflight["orch"] - 1)


def get_inflight():
    """Snapshot de los contadores en vuelo (orquestaciones y peticiones)."""
    with _inflight_lock:
        return dict(_inflight), dict(_inflight_peak)


# FASE 28.5: salud de las llamadas LLM (acumulado desde el arranque)
_llm_stats = {"ok": 0, "timeout": 0, "error": 0, "rate_limited": 0}


def _llm_stat(kind):
    with _inflight_lock:
        _llm_stats[kind] = _llm_stats.get(kind, 0) + 1


def get_llm_stats():
    with _inflight_lock:
        s = dict(_llm_stats)
    s["total"] = s["ok"] + s["timeout"] + s["error"] + s["rate_limited"]
    s["fail_pct"] = round((s["total"] - s["ok"]) / s["total"] * 100, 1) if s["total"] else 0.0
    return s


# FASE 28.6: errores 5xx acumulados desde el arranque
_http_5xx = {"n": 0}


def _http_5xx_inc():
    with _inflight_lock:
        _http_5xx["n"] += 1


def get_http_5xx():
    with _inflight_lock:
        return _http_5xx["n"]


def read_infra_health():
    """FASE 28.6: caducidad del certificado TLS y frescura del último backup.
    Best-effort: devuelve None en lo que no aplique (p. ej. en local sin cert)."""
    out = {"tls_days_left": None, "backup_age_hours": None, "host": None}
    # TLS: días hasta caducar el certificado del dominio (solo en producción)
    host = os.environ.get("HUMANIA_TLS_HOST") or ("h2aichat.com" if os.environ.get("HUMANIA_ENV") == "production" else None)
    out["host"] = host
    if host:
        try:
            import ssl as _ssl
            import socket as _socket
            from datetime import datetime as _dt, timezone as _tz
            ctx = _ssl.create_default_context()
            with _socket.create_connection((host, 443), timeout=4) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
            exp = _dt.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=_tz.utc)
            out["tls_days_left"] = round((exp - _dt.now(_tz.utc)).total_seconds() / 86400, 1)
        except Exception:
            pass
    # Backup: antigüedad del fichero de backup más reciente (ruta configurable)
    bdir = os.environ.get("HUMANIA_BACKUP_PATH")
    if bdir and os.path.isdir(bdir):
        try:
            import glob as _glob
            files = _glob.glob(os.path.join(bdir, "*"))
            if files:
                newest = max(files, key=os.path.getmtime)
                out["backup_age_hours"] = round((_time.time() - os.path.getmtime(newest)) / 3600, 1)
        except Exception:
            pass
    return out


def _count_orchestration(fn):
    """Decorador: cuenta la orquestación como 'en vuelo' mientras corre (carga pesada)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _orch_enter()
        try:
            return fn(*args, **kwargs)
        finally:
            _orch_exit()
    return wrapper


# ── FASE 29: orquestación asíncrona ("dispara y sondea") ─────────────────────
# /orchestrate lanza el debate en un hilo de fondo y responde al instante; el
# chat muestra los mensajes por su polling y consulta /api/orchestration-status.
ORCH_MAX_CONCURRENT = 12          # tope de debates simultáneos en segundo plano (decisión PO)
ORCH_STALE_SECONDS = 1800         # si una tarea 'running' no se actualiza en este tiempo -> se da por muerta
_orch_lock = _threading.Lock()
_orch_tasks = {}                  # thread_id -> {status, round, total_rounds, bots, started_at, updated_at, summary}


def _orch_register(thread, total_rounds, n_bots):
    now = _time.time()
    with _orch_lock:
        _orch_tasks[thread] = {"status": "running", "round": 0, "total_rounds": total_rounds,
                               "bots": n_bots, "started_at": now, "updated_at": now, "summary": None}


def _orch_set_progress(thread, rnd, total, n_bots):
    with _orch_lock:
        t = _orch_tasks.get(thread)
        if t:
            t.update(round=rnd, total_rounds=total, bots=n_bots, updated_at=_time.time())


def _orch_finish(thread, status, summary=None):
    with _orch_lock:
        t = _orch_tasks.get(thread)
        if t:
            t.update(status=status, updated_at=_time.time(),
                     summary=(summary if isinstance(summary, dict) else None))


def _orch_is_running(thread):
    with _orch_lock:
        t = _orch_tasks.get(thread)
        return bool(t and t["status"] == "running")


def _orch_count_running():
    with _orch_lock:
        return sum(1 for t in _orch_tasks.values() if t["status"] == "running")


def _orch_get(thread):
    """Snapshot del estado de un debate. Heartbeat: una tarea 'running' que lleva
    demasiado sin actualizarse (p. ej. el server se reinició) se reporta 'stalled'
    para que el cartel no gire para siempre."""
    with _orch_lock:
        t = _orch_tasks.get(thread)
        if not t:
            return None
        snap = dict(t)
    if snap["status"] == "running" and (_time.time() - snap["updated_at"]) > ORCH_STALE_SECONDS:
        snap["status"] = "stalled"
    return snap


# ── FASE 28: muestreador de salud del sistema ────────────────────────────────
ORCH_CAPACITY = 8                       # orquestaciones simultáneas que tomamos como "saturación" (ajustable tras la carga)
HEALTH_DISK_PATH = os.path.abspath(os.sep)  # "/" en Linux, "C:\\" en Windows
HEALTH_SAMPLE_INTERVAL = 30             # segundos entre muestras pasivas
# Umbrales de ROJO confirmados por el PO (2026-06-23): capacidad >80, RAM >85, disco >75 (uso)
HEALTH_THRESHOLDS = {"capacity_pct": 80, "ram_pct": 85, "disk_used_pct": 75}
_health_sampler_started = False


def build_health_sample(eng):
    """Foto actual de salud: métricas del SO + contadores en vuelo + capacidad."""
    m = system_metrics.read_system_metrics(HEALTH_DISK_PATH)
    cur, peak = get_inflight()
    cap = system_metrics.compute_capacity(m, inflight_orch=cur["orch"], orch_cap=ORCH_CAPACITY)
    return {
        "ram_pct": m.get("ram_pct"), "swap_pct": m.get("swap_pct"), "cpu_pct": m.get("cpu_pct"),
        "disk_used_pct": m.get("disk_used_pct"), "disk_free_pct": m.get("disk_free_pct"),
        "load1": m.get("load1"), "cpu_count": m.get("cpu_count"), "has_psutil": m.get("has_psutil"),
        "inflight_orch": cur["orch"], "inflight_requests": cur["requests"],
        "peak_orch": peak["orch"], "peak_requests": peak["requests"],
        "capacity_pct": cap["capacity_pct"], "worst": cap["worst"], "sub": cap["sub"],
        "orch_capacity": ORCH_CAPACITY,
        "llm": get_llm_stats(),          # FASE 28.5: salud de LLM
        "http_5xx": get_http_5xx(),      # FASE 28.6: errores 5xx acumulados
        "infra": read_infra_health(),    # FASE 28.6: TLS / backup
    }


def sample_system_health(eng):
    """Toma una muestra y la persiste (para el histórico)."""
    s = build_health_sample(eng)
    try:
        auth.record_system_health(eng, s)
    except Exception:
        pass
    return s


def _start_health_sampler():
    """Hilo de fondo que muestrea cada HEALTH_SAMPLE_INTERVAL s. Debe correr DENTRO
    del proceso del servidor para ver los contadores en vuelo reales. Se arranca solo
    en producción (o con HUMANIA_HEALTH_SAMPLER=1); en tests no, para no escribir sola."""
    global _health_sampler_started
    if _health_sampler_started:
        return
    _health_sampler_started = True

    def _loop():
        while True:
            try:
                sample_system_health(engine)
                _health_alert_check(engine)
            except Exception:
                pass
            _time.sleep(HEALTH_SAMPLE_INTERVAL)
    _threading.Thread(target=_loop, daemon=True, name="health-sampler").start()


ALERT_REMINDER_INTERVAL = 1800   # 30 min: recordatorio si SIGUE atascado en el mismo nivel

# Alertas por NIVELES con histéresis (modelo estándar de monitorización, decisión PO 2026-06-26).
# Cada métrica tiene varios umbrales ascendentes ("aviso" -> "crítico") y una línea de
# RECUPERACIÓN por debajo de la cual el episodio se considera resuelto.
#   - El umbral "aviso" coincide con HEALTH_THRESHOLDS (lo que pinta el panel /admin).
#   - La línea de recuperación es el umbral "aviso" menos un DEADBAND de 10 puntos. Ese
#     margen (histéresis) es la práctica estándar para evitar "flapping": que la métrica
#     oscilando justo en el umbral dispare avisos/recuperaciones en bucle. Hay que bajar
#     claramente (10 puntos) para dar el problema por cerrado.
# Reglas (por métrica, estado en memoria del proceso):
#   1) Sube a un nivel MÁS ALTO que el peor alcanzado en este episodio -> aviso INMEDIATO
#      (se salta el silencio de 30 min: un empeoramiento siempre avisa).
#   2) Se mantiene en el mismo nivel -> recordatorio cada ALERT_REMINDER_INTERVAL.
#   3) Baja por debajo de la línea de recuperación -> aviso de RECUPERACIÓN (✅) y el
#      episodio se REARMA: si vuelve a subir, cuenta como problema nuevo y vuelve a avisar.
#   (Mejora parcial sin bajar de la línea de recuperación: no se avisa, sigue armado al peor nivel.)
_ALERT_DEADBAND = 10
ALERT_LEVELS = {
    "capacity": {"metric": "capacity_pct", "name": "Capacidad",
                 "levels": [(HEALTH_THRESHOLDS["capacity_pct"], "aviso"), (92, "crítico")]},
    "ram":      {"metric": "ram_pct", "name": "RAM",
                 "levels": [(HEALTH_THRESHOLDS["ram_pct"], "aviso"), (95, "crítico")]},
    "disk":     {"metric": "disk_used_pct", "name": "Disco",
                 "levels": [(HEALTH_THRESHOLDS["disk_used_pct"], "aviso"), (90, "crítico")]},
}
# línea de recuperación = umbral de aviso - deadband
for _cfg in ALERT_LEVELS.values():
    _cfg["recovery"] = _cfg["levels"][0][0] - _ALERT_DEADBAND

# estado por métrica: {"level": peor nivel alcanzado en el episodio (0=normal), "last_ts": float}
_alert_state = {}


def _level_for(value, levels):
    """Devuelve el índice de nivel (0=normal, 1=aviso, 2=crítico...) del valor."""
    lvl = 0
    if value is not None:
        for i, (thr, _name) in enumerate(levels, start=1):
            if value >= thr:
                lvl = i
    return lvl


def _alert_time_str():
    """Hora 'HH:MM (Madrid)' para los avisos (el droplet corre en UTC). Fallback a UTC si no hay tz db."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M") + " (Madrid)"
    except Exception:
        return _time.strftime("%d/%m/%Y %H:%M", _time.gmtime()) + " UTC"


def _health_alert_check(eng, sample=None):
    """FASE 28.7 / 30+: vigila la salud y avisa por Telegram por NIVELES con histéresis
    (ver ALERT_LEVELS). Avisa al empeorar de nivel (inmediato), recuerda cada 30 min si
    persiste, y avisa de recuperación al volver a la normalidad. Silenciable con
    HUMANIA_ALERTS=0 (p. ej. durante una prueba de carga deliberada).

    Se usa Telegram (no email) porque el droplet bloquea el SMTP saliente y para no
    gastar el cupo de Resend, reservado al correo de los usuarios."""
    if os.environ.get("HUMANIA_ALERTS", "1") != "1":
        return []
    s = sample or build_health_sample(eng)
    now = _time.time()
    hora = _alert_time_str()
    cond = (f"RAM {s.get('ram_pct')}% · CPU {s.get('cpu_pct')}% · disco {s.get('disk_used_pct')}% · "
            f"{s.get('inflight_orch')} orquestando · {s.get('inflight_requests')} peticiones en vuelo")
    sent = []

    def _emit(text):
        try:
            telegram_sender.send_telegram(f"{text}\n\n🕐 {hora}")
            return True
        except Exception:
            return False

    for key, cfg in ALERT_LEVELS.items():
        value = s.get(cfg["metric"])
        if value is None:
            continue
        st = _alert_state.setdefault(key, {"level": 0, "last_ts": 0.0})
        cur = _level_for(value, cfg["levels"])
        # (3) recuperación: estaba alertado y baja por debajo de la línea de recuperación
        if st["level"] > 0 and value < cfg["recovery"]:
            if _emit(f"✅ [H2AI] {cfg['name']} recuperada: {value}%\n\nCondiciones: {cond}"):
                st["level"] = 0
                st["last_ts"] = now
                sent.append(key)
            continue
        # (1) empeora: nivel más alto que el peor del episodio -> aviso inmediato
        if cur > st["level"]:
            label = cfg["levels"][cur - 1][1]
            if _emit(f"\U0001F6A8 [H2AI alerta] {cfg['name']} {label}: {value}%\n\nCondiciones: {cond}"):
                st["level"] = cur
                st["last_ts"] = now
                sent.append(key)
        # (2) mismo nivel mantenido -> recordatorio cada ALERT_REMINDER_INTERVAL
        elif cur == st["level"] and st["level"] > 0:
            if now - st["last_ts"] >= ALERT_REMINDER_INTERVAL:
                label = cfg["levels"][cur - 1][1]
                if _emit(f"\U0001F6A8 [H2AI alerta] {cfg['name']} sigue en {label}: {value}%\n\nCondiciones: {cond}"):
                    st["last_ts"] = now
                    sent.append(key)
        # cur < st["level"] pero >= recuperación: mejora parcial, no se avisa
    return sent

app = FastAPI(title="H2AI Chat API", version="1.0")
engine = ConversationEngine(base_path=Path(__file__).parent.parent)
auth.init_auth_tables(engine)
auth.cleanup_expired(engine)  # GDPR 20.8e: minimizacion al arrancar
auth.record_startup(engine, version=app.version)  # FASE 23: monitor de arranques/caidas
# FASE 28: muestreador de salud en hilo de fondo. Solo en producción (o con el flag),
# nunca bajo tests (escribiría solo en la BD). El panel funciona igual sin él (lee en vivo).
if os.environ.get("HUMANIA_ENV", "dev") == "production" or os.environ.get("HUMANIA_HEALTH_SAMPLER") == "1":
    _start_health_sampler()
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "templates")), name="static")
app.add_middleware(_SecurityHeadersMiddleware)

_token = os.environ.get("HUMANIA_TOKEN", "humania-dev-token")
if os.environ.get("HUMANIA_ENV", "dev") == "production" and _token == "humania-dev-token":
    raise RuntimeError("HUMANIA_TOKEN must be set in production. Generate one: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
email_sender.validate_production_config()  # FASE 20.1-A3: fallo en arranque si el email esta mal configurado
SECRET_TOKEN = _token
_rate_store = defaultdict(list)


@app.middleware("http")
async def security_middleware(request, call_next):
    client_ip = request.client.host if request.client else "testclient"
    # FASE 40.2: modo self-host "100% local" (docker-compose fija HUMANIA_LOCAL=1). En una
    # instancia en tu propia máquina, un solo usuario, no hace falta login: se trata como
    # local (admin, sin auth). staging/PROD NO ponen esa variable, así que no les afecta.
    is_local = client_ip in ("127.0.0.1", "::1", "localhost", "testclient") or os.environ.get("HUMANIA_LOCAL") == "1"
    protected = any(request.url.path.startswith(p) for p in ("/api/", "/orchestrate", "/turn/", "/message/", "/messages/")) and request.url.path != "/api/feedback"  # /api/feedback es publico: permite feedback anonimo (C)

    # FASE 20.1 (hallazgo UAT PO 2026-06-12): el JWT del usuario se valida ANTES que el
    # token maestro. Los navegadores de usuarios reales no tienen (ni deben tener) el
    # token maestro: una sesion JWT valida da acceso a nivel de usuario con sus limites
    # de plan (20.2). El token maestro queda como acceso de administracion/scripts.
    user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = auth.decode_token(engine, auth_header[7:])
        if payload is None:
            return JSONResponse(status_code=401, content={"error": "Token invalido, expirado o revocado"})
        user = {"user_id": int(payload["sub"]), "email": payload.get("email", ""),
                "name": payload.get("name", ""), "plan": payload.get("plan", "free")}

    master_ok = request.headers.get("X-Humania-Token") == SECRET_TOKEN
    if protected and not is_local and user is None and not master_ok:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if user is None:
        if master_ok:
            user = dict(auth.DEV_USER)  # acceso de administracion via token maestro
        elif auth.auth_enforced() and (protected or request.url.path == "/"):
            if request.url.path == "/":
                return RedirectResponse(url="/web", status_code=302)
            return JSONResponse(status_code=401, content={"error": "Autenticacion requerida"})
        else:
            user = dict(auth.DEV_USER)
    request.state.user = user
    if request.url.path == "/orchestrate" and not is_local:
        now = _time.time()
        _rate_store[client_ip] = [t for t in _rate_store[client_ip] if now - t < 60]
        if len(_rate_store[client_ip]) > 10:
            return JSONResponse(status_code=429, content={"error": "Too many requests"})
        _rate_store[client_ip].append(now)
    is_production = os.environ.get("HUMANIA_ENV", "dev") == "production"
    if is_production:
        scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
        if scheme != "https":
            return RedirectResponse(url=request.url.replace(scheme="https").__str__(), status_code=301)
    return await call_next(request)


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=128)
    name: str = Field("", max_length=100)
    accept_terms: bool = False
    confirm_adult: bool = False


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=128)


class FeedbackRequest(BaseModel):
    kind: str = Field(..., max_length=20)            # conversation | contact | public
    conversation_id: str = Field("", max_length=300)
    vote: str = Field("", max_length=10)             # up | down | neutral
    comment: str = Field("", max_length=2000)
    contact_type: str = Field("", max_length=40)     # idea | duda | fallo | otro
    contact_email: str = Field("", max_length=254)


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest, request: Request):
    kind = (req.kind or "").strip()
    if kind not in ("conversation", "contact", "public"):
        raise HTTPException(status_code=400, detail="kind invalido")
    vote = (req.vote or "").strip().lower() or None
    if vote and vote not in ("up", "down", "neutral"):
        raise HTTPException(status_code=400, detail="vote invalido")
    comment = (req.comment or "").strip() or None
    contact_type = (req.contact_type or "").strip() or None
    contact_email = (req.contact_email or "").strip() or None
    conversation_id = (req.conversation_id or "").strip() or None
    if kind == "conversation" and not vote and not comment:
        raise HTTPException(status_code=400, detail="feedback vacio")
    if kind == "contact" and not comment:
        raise HTTPException(status_code=400, detail="comentario requerido")
    user = getattr(request.state, "user", None)
    uid = user.get("user_id") if user else None
    user_id = uid if uid else None  # 0 (DEV/anonimo) -> None
    if kind == "public":
        user_id = None  # las reacciones publicas son anonimas
    fid = auth.save_feedback(engine, kind, user_id=user_id, conversation_id=conversation_id,
                             vote=vote, comment=comment, contact_type=contact_type, contact_email=contact_email)
    return {"success": True, "id": fid}


@app.get("/health")
def health():
    """Comprobacion de salud para el smoke post-deploy: app viva + BD accesible."""
    try:
        conn = engine._get_conn()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="db unavailable")


ADMIN_EMAIL = os.environ.get("HUMANIA_ADMIN_EMAIL", "contact@h2aichat.com").strip().lower()


def _is_admin(request: Request) -> bool:
    """Admin = email administrador, token maestro o dev/local (ambos = DEV_USER)."""
    user = getattr(request.state, "user", None) or {}
    email = (user.get("email") or "").strip().lower()
    return email == ADMIN_EMAIL or email == auth.DEV_USER["email"]


def _require_admin(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Acceso solo para administración")


@app.get("/api/admin/stats")
def admin_stats_endpoint(request: Request):
    """Panel /admin: solo accesible logueado como el email administrador."""
    user = getattr(request.state, "user", None)
    if not user or (user.get("email") or "").strip().lower() != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Acceso solo para administración")
    return auth.admin_stats(engine)


@app.get("/api/admin/feedback/comments")
def admin_feedback_comments(request: Request, limit: int = 100):
    """Panel /admin (FASE 20.7.1): comentarios de texto dejados en conversaciones. Solo lectura,
    solo admin. Sin paginacion aun (Fase 37.x): ultimos `limit` (tope 100)."""
    _require_admin(request)
    return auth.list_conversation_comments(engine, limit=min(int(limit), 100))


@app.get("/admin", response_class=HTMLResponse)
def serve_admin():
    p = Path(__file__).parent / "templates" / "admin.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<h1>Panel</h1><p>admin.html no encontrado</p>"


# ── FASE 23: gestion de usuarios + monitor de arranques (solo admin) ─────────

class PlanRequest(BaseModel):
    plan: str = Field(..., max_length=20)


class StatusRequest(BaseModel):
    status: str = Field(..., max_length=20)


@app.get("/api/admin/users")
def admin_list_users(request: Request, q: str = "", limit: int = 50, offset: int = 0):
    _require_admin(request)
    return auth.list_users(engine, query=q or None, limit=min(int(limit), 200), offset=max(int(offset), 0))


@app.get("/api/admin/users/{user_id}")
def admin_user_detail(user_id: int, request: Request):
    _require_admin(request)
    u = auth.get_user_detail(engine, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return u


@app.post("/api/admin/users/{user_id}/plan")
def admin_set_plan(user_id: int, req: PlanRequest, request: Request):
    _require_admin(request)
    try:
        ok = auth.set_plan(engine, user_id, req.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"success": True, "plan": req.plan}


@app.post("/api/admin/users/{user_id}/status")
def admin_set_status(user_id: int, req: StatusRequest, request: Request):
    _require_admin(request)
    try:
        ok = auth.set_status(engine, user_id, req.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"success": True, "status": req.status}


@app.post("/api/admin/users/{user_id}/reset-usage")
def admin_reset_usage(user_id: int, request: Request):
    _require_admin(request)
    if not auth.reset_usage(engine, user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"success": True}


@app.post("/api/admin/users/{user_id}/verify-email")
def admin_verify_email_ep(user_id: int, request: Request):
    _require_admin(request)
    if not auth.admin_verify_email(engine, user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"success": True}


@app.post("/api/admin/users/{user_id}/resend-verification")
def admin_resend_verification(user_id: int, request: Request):
    _require_admin(request)
    result = auth.admin_create_verification(engine, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    token, email = result
    sent = False
    try:
        email_sender.send_verification_email(email, token)
        sent = True
    except Exception:
        traceback.print_exc()
    return {"success": True, "email_sent": sent}


@app.post("/api/admin/users/{user_id}/send-reset")
def admin_send_reset(user_id: int, request: Request):
    _require_admin(request)
    result = auth.admin_create_password_reset(engine, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o inactivo")
    token, email = result
    sent = False
    try:
        email_sender.send_password_reset_email(email, token)
        sent = True
    except Exception:
        traceback.print_exc()
    return {"success": True, "email_sent": sent}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, request: Request):
    _require_admin(request)
    if not auth.delete_account(engine, user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"success": True}


@app.get("/api/admin/startups")
def admin_startups(request: Request, limit: int = 50):
    _require_admin(request)
    return {"startups": auth.list_startups(engine, limit=min(int(limit), 200))}


@app.get("/api/admin/orch-times")
def admin_orch_times(request: Request, limit: int = 50):
    _require_admin(request)
    return auth.list_orch_times(engine, limit=min(int(limit), 500))


# ── FASE 28: salud del sistema ───────────────────────────────────────────────
@app.get("/api/admin/health")
def admin_health(request: Request, record: int = 0):
    """Foto EN VIVO de la salud (calculada al momento). Con ?record=1 también la
    guarda en el histórico (lo usa el arnés de carga para densificar la serie)."""
    _require_admin(request)
    sample = build_health_sample(engine)
    if record:
        try:
            auth.record_system_health(engine, sample)
        except Exception:
            pass
    return {
        "sample": sample,
        "thresholds": HEALTH_THRESHOLDS,
        "peak": auth.get_system_peak(engine),
    }


@app.get("/api/admin/health/history")
def admin_health_history(request: Request, hours: int = 24):
    _require_admin(request)
    return auth.list_system_health(engine, hours=min(max(int(hours), 1), 720))


@app.get("/api/admin/health/peak")
def admin_health_peak(request: Request):
    _require_admin(request)
    return {"peak": auth.get_system_peak(engine)}


@app.post("/api/admin/health/reset")
def admin_health_reset(request: Request):
    """Pone a CERO las estadísticas de observabilidad (botón del panel): vacía la
    gráfica de salud + el récord de pico + los tiempos + la basura del arnés, y
    resetea los contadores en memoria (picos en vuelo, salud LLM, 5xx). NO borra
    cuentas, conversaciones reales ni feedback."""
    _require_admin(request)
    deleted = auth.reset_observability_stats(engine)
    with _inflight_lock:
        _inflight_peak["orch"] = 0
        _inflight_peak["requests"] = 0
        for k in _llm_stats:
            _llm_stats[k] = 0
        _http_5xx["n"] = 0
    _alert_state.clear()
    return {"ok": True, "deleted": deleted}


@app.post("/api/admin/backup")
def admin_backup(request: Request):
    """FASE 28: copia de seguridad de la BD bajo demanda (botón del panel)."""
    _require_admin(request)
    path, size = engine.backup_db()
    return {"ok": True, "file": os.path.basename(path), "bytes": size}


@app.get("/api/admin/plan-limits")
def admin_get_plan_limits(request: Request):
    _require_admin(request)
    return {"limits": get_plan_limits(engine),
            "fields": [{"key": k, "label": l, "type": t} for k, l, t in PLAN_LIMIT_FIELDS],
            "order": PLAN_ORDER}


@app.post("/api/admin/plan-limits")
def admin_set_plan_limits(request: Request, limits: dict):
    _require_admin(request)
    valid = {k: t for k, l, t in PLAN_LIMIT_FIELDS}
    clean = {}
    for plan in PLAN_ORDER:
        clean[plan] = dict(PLAN_LIMITS_DEFAULT[plan])
        for k, v in (limits.get(plan, {}) or {}).items():
            if k not in valid:
                continue
            if valid[k] == "bool":
                clean[plan][k] = bool(v)
            else:
                try:
                    clean[plan][k] = max(0, int(v))
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail=f"{plan}.{k} debe ser un numero")
    engine.set_setting("plan_limits", json.dumps(clean))
    return {"success": True, "limits": clean}


# FASE 27: el ENGRANAJE de cada usuario (su config, acotada por su plan). No es admin: cada
# usuario logueado ajusta lo SUYO.
@app.get("/api/me/prefs")
def get_my_prefs(request: Request):
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    eff = effective_user_config(engine, user, engine.get_all_settings(SETTINGS_DEFAULTS))
    return {
        "prefs": auth.get_user_prefs(engine, user.get("user_id")),
        "plan": eff["plan"],
        "limits": eff["limits"],
        "effective": {"rounds": eff["rounds"], "max_tokens": eff["max_tokens"]},
        "creativity_labels": CREATIVITY_LABELS,
    }


@app.post("/api/me/profile")
def set_my_profile(request: Request, body: dict):
    """FASE 29: cambiar el nombre del usuario (con el que las IAs le llaman en los debates)."""
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    uid = user.get("user_id")
    if not uid:
        return {"ok": True, "name": (body.get("name") or "").strip()[:60], "note": "sin sesion"}
    name = auth.set_user_name(engine, uid, body.get("name", ""))
    return {"ok": True, "name": name}


@app.post("/api/me/prefs")
def set_my_prefs(request: Request, prefs: dict):
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    uid = user.get("user_id")
    if not uid:
        return {"success": True, "note": "sin sesion: no se persiste"}
    limits = get_plan_limits(engine).get(user.get("plan") or "free", PLAN_LIMITS_DEFAULT["free"])
    clean = dict(auth.get_user_prefs(engine, uid))  # preservar lo que no venga en esta llamada
    try:
        if prefs.get("rounds") is not None:
            clean["rounds"] = max(1, min(int(prefs["rounds"]), int(limits["max_rounds"])))
        if prefs.get("max_tokens") is not None:
            clean["max_tokens"] = max(64, min(int(prefs["max_tokens"]), int(limits["max_tokens"])))
        if prefs.get("creativity") is not None:
            clean["creativity"] = max(0, min(int(prefs["creativity"]), int(limits.get("max_creativity", 2))))
        if prefs.get("models") is not None:
            cat = {m["id"]: m for m in get_model_catalog(engine)}
            allow_or = bool(limits.get("openrouter"))
            ids = [m for m in prefs["models"] if m in cat and (allow_or or cat[m].get("provider") != "openrouter")]
            clean["models"] = ids[:int(limits.get("max_models", 3))]
        if prefs.get("system_prompt_extra") is not None:
            # Opción A: instrucciones extra del usuario (se suman al prompt base). Tope de tamaño.
            clean["system_prompt_extra"] = str(prefs["system_prompt_extra"])[:2000]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Valores de configuracion no validos")
    auth.set_user_prefs(engine, uid, clean)
    # FASE 27: registrar/activar las IAs elegidas para que aparezcan ACTIVAS (verdes) en el chat
    # aunque un perfil global las hubiera marcado inactivas.
    cat = {m["id"]: m for m in get_model_catalog(engine)}
    for mid in clean.get("models", []):
        m = cat.get(mid)
        if m:
            engine.register_participant(mid, m.get("role", ""), "bot", m.get("email", f"{mid}@bot.local"),
                                        provider=m.get("provider", "cloud"))
            engine.set_participant_active(mid)
    return {"success": True, "prefs": clean}


@app.get("/api/me/models")
def get_my_models(request: Request):
    """Pieza B: las IAs que ESTE usuario puede elegir (catálogo filtrado por su plan) + su selección."""
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    limits = get_plan_limits(engine).get(user.get("plan") or "free", PLAN_LIMITS_DEFAULT["free"])
    allow_or = bool(limits.get("openrouter"))
    available = [{"id": m["id"], "label": m.get("label", m["id"]), "role": m.get("role", ""), "provider": m.get("provider")}
                 for m in get_model_catalog(engine) if allow_or or m.get("provider") != "openrouter"]
    return {
        "available": available,
        "selected": auth.get_user_prefs(engine, user.get("user_id")).get("models", []),
        "max_models": int(limits.get("max_models", 3)),
        "openrouter": allow_or,
    }


class ShareRequest(BaseModel):
    thread_id: str = Field(..., max_length=300)
    consent: bool = False


@app.post("/api/conversations/share")
def share_conversation(req: ShareRequest, request: Request):
    """Opt-in granular: el usuario consiente (o retira) publicar una conversación SUYA, anonimizada."""
    user = getattr(request.state, "user", None)
    uid = user.get("user_id") if user else None
    if not uid:
        raise HTTPException(status_code=401, detail="Inicia sesión")
    if not (req.thread_id or "").startswith(auth.user_thread_prefix(uid)):
        raise HTTPException(status_code=403, detail="Esa conversación no es tuya")
    auth.set_share_consent(engine, uid, req.thread_id, bool(req.consent))
    return {"success": True, "shared": bool(req.consent)}


# ── Fase 34: enlace publico por conversacion (snapshot inmutable + URL para posts) ──

class ShareLinkRequest(BaseModel):
    lang: str = Field("es", max_length=8)


def _clean_text(s, n):
    import re as _re
    s = _re.sub(r"<[^>]*>", "", s or "")
    s = _re.sub(r"[*_`#>]", "", s)
    return _re.sub(r"\s+", " ", s).strip()[:n]


def _build_share_snapshot(uid, thread_id, lang):
    """Congela el estado ACTUAL de la conversacion (snapshot inmutable para el enlace)."""
    from datetime import datetime as _dt
    msgs = engine.get_thread_context(thread_id, limit=100000)  # todos, orden ascendente
    fresh = auth.get_user(engine, uid) or {}
    mod_name = (fresh.get("name") or "").strip() or (fresh.get("email") or "").split("@")[0] or "Moderador"
    # FASE 31: el moderador es por-usuario (su email). Detectamos su remitente en los mensajes;
    # 'miguel' se mantiene como fallback para hilos antiguos anteriores a la refactorizacion.
    _email = (fresh.get("email") or "").strip().lower()
    mod_sender = next((s for s in (_email, "miguel") if s and any(m.get("sender") == s for m in msgs)), _email or "miguel")
    first_mod = next((m for m in msgs if m.get("sender") == mod_sender), (msgs[0] if msgs else None))
    first_other = next((m for m in msgs if m.get("sender") != mod_sender), None)
    # El titulo NO se guarda: el render lo deriva del primer mensaje (siempre completo). Aqui solo desc (og).
    desc = _clean_text((first_other or first_mod or {}).get("body", ""), 200)
    return {
        "thread_id": thread_id,
        "mod_sender": mod_sender,
        "mod_name": mod_name,
        "lang": (lang or "es")[:2],
        "desc": desc,
        "date": _dt.now().strftime("%d/%m/%Y"),
        "count": len(msgs),
        "messages": [{"sender": m.get("sender"), "recipient": m.get("recipient"),
                      "body": m.get("body", ""), "timestamp": m.get("timestamp", "")} for m in msgs],
    }


def _share_url(token):
    return email_sender.base_url() + "/c/" + token


def _require_owner(request: Request, thread_id: str):
    user = getattr(request.state, "user", None)
    uid = user.get("user_id") if user else None
    if not uid:
        raise HTTPException(status_code=401, detail="Inicia sesión")
    if not (thread_id or "").startswith(auth.user_thread_prefix(uid)):
        raise HTTPException(status_code=403, detail="Esa conversación no es tuya")
    return uid


@app.post("/api/conversations/{thread_id}/share")
def create_conversation_share_link(thread_id: str, req: ShareLinkRequest, request: Request):
    """Crea (o 'Actualiza': re-congela sobre el mismo token) el enlace publico de una conversacion propia."""
    uid = _require_owner(request, thread_id)
    snapshot = _build_share_snapshot(uid, thread_id, req.lang)
    if not snapshot["messages"]:
        raise HTTPException(status_code=400, detail="La conversación está vacía")
    token = auth.create_or_update_share_link(engine, uid, thread_id, json.dumps(snapshot, ensure_ascii=False))
    return {"success": True, "token": token, "url": _share_url(token)}


@app.post("/api/conversations/{thread_id}/share/revoke")
def revoke_conversation_share_link(thread_id: str, request: Request):
    uid = _require_owner(request, thread_id)
    auth.revoke_share_link(engine, uid, thread_id)
    return {"success": True}


@app.get("/api/conversations/{thread_id}/share")
def get_conversation_share_link(thread_id: str, request: Request):
    uid = _require_owner(request, thread_id)
    link = auth.get_share_link_for_thread(engine, uid, thread_id)
    if not link:
        return {"shared": False}
    return {"shared": True, "token": link["token"], "url": _share_url(link["token"]),
            "updated_at": link.get("updated_at")}


@app.get("/c/{token}", response_class=HTMLResponse)
def serve_shared_conversation(token: str, request: Request):
    """Pagina PUBLICA (sin login) de una conversacion compartida. Render server-side + tarjeta social."""
    lang = resolve_web_lang(request.query_params.get("lang"), request.cookies.get("web_lang"),
                            request.headers.get("accept-language"))
    base = email_sender.base_url()
    link = auth.get_share_link(engine, token)
    # Enlace inexistente, revocado o corrupto -> a la home directamente (hallazgo PO).
    if not link:
        return RedirectResponse(url="/web", status_code=302)
    try:
        snapshot = json.loads(link["snapshot"])
    except Exception:
        return RedirectResponse(url="/web", status_code=302)
    _embed = request.query_params.get("embed") == "1"
    return HTMLResponse(render_shared_page(snapshot, lang, base, token, embed=_embed))


_login_attempts = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 5  # intentos fallidos por IP y hora (plan 20.2g)


def _login_rate_limited(request: Request) -> bool:
    client_ip = request.client.host if request.client else "testclient"
    is_local = client_ip in ("127.0.0.1", "::1", "localhost", "testclient") or os.environ.get("HUMANIA_LOCAL") == "1"
    if is_local and not auth.auth_enforced():
        return False
    now = _time.time()
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < 3600]
    return len(_login_attempts[client_ip]) >= LOGIN_MAX_ATTEMPTS


def _record_failed_login(request: Request):
    client_ip = request.client.host if request.client else "testclient"
    _login_attempts[client_ip].append(_time.time())


@app.post("/auth/register")
def auth_register(req: RegisterRequest):
    auth.init_auth_tables(engine)
    try:
        token, user = auth.register_user(engine, req.email, req.password, req.name,
                                          accept_terms=req.accept_terms, confirm_adult=req.confirm_adult)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # FASE 20.4b: email de verificacion (el registro no falla si el envio falla)
    try:
        vtoken = auth.create_verification(engine, user["user_id"])
        email_sender.send_verification_email(user["email"], vtoken)
    except Exception:
        traceback.print_exc()
    return {"success": True, "token": token, "user": user}


@app.post("/auth/login")
def auth_login(req: LoginRequest, request: Request):
    auth.init_auth_tables(engine)
    if _login_rate_limited(request):
        raise HTTPException(status_code=429, detail="Demasiados intentos de login. Espera una hora.")
    result = auth.login_user(engine, req.email, req.password)
    if result is None:
        _record_failed_login(request)
        raise HTTPException(status_code=401, detail="Email o contrasena incorrectos")
    token, user = result
    return {"success": True, "token": token, "user": user}


@app.get("/auth/me")
def auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    if user.get("user_id", 0) != 0:
        fresh = auth.get_user(engine, user["user_id"])
        if fresh is None or fresh.get("status") != "active":
            raise HTTPException(status_code=401, detail="Cuenta no activa")
        usage = auth.get_usage(engine, user["user_id"])
        u = {k: fresh[k] for k in ("user_id", "email", "name", "plan", "email_verified")}
        u["is_admin"] = (fresh["email"] or "").strip().lower() == ADMIN_EMAIL
        return {"user": u, "usage": usage}
    return {"user": dict(user, email_verified=1, is_admin=True), "usage": {"debates": 0, "est_cost_eur": 0.0}}


@app.post("/auth/logout")
def auth_logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth.revoke_token(engine, auth_header[7:])
        return {"success": True}
    return {"success": False, "error": "Sin token"}


def _auth_page(title: str, body_html: str) -> str:
    """Mini-pagina autocontenida con el estilo de la marca para verify/reset."""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} — H2AI Chat</title>
<style>body{{font-family:system-ui,sans-serif;background:#f6f5f2;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e0e0e0;border-radius:14px;padding:36px;max-width:380px;width:90%;text-align:center}}
h2{{margin:0 0 8px;color:#1a1a1a}}p{{color:#5a5855;font-size:14px}}
.logo{{width:34px;height:34px;background:#E8186E;color:#fff;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-weight:700;margin-bottom:14px}}
input{{width:100%;box-sizing:border-box;padding:10px;margin:6px 0;border:1px solid #ddd;border-radius:8px;font-size:14px}}
button,a.btn{{display:inline-block;width:100%;box-sizing:border-box;padding:11px;margin-top:12px;background:#E8186E;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none}}
.err{{color:#E8186E;font-size:13px;display:none;margin-top:8px}}
.pw-wrap{{position:relative}}.pw-wrap input{{padding-right:42px}}
.pw-eye{{position:absolute;right:6px;top:8px;width:auto;margin:0;padding:6px;background:none;border:none;color:#999;font-size:18px;line-height:1;cursor:pointer}}</style></head>
<body><div class="card"><div class="logo">H2</div>{body_html}</div></body></html>"""


@app.get("/auth/verify-email", response_class=HTMLResponse)
def auth_verify_email(token: str = ""):
    if auth.verify_email(engine, token):
        return _auth_page("Email verificado",
                          '<h2>Email verificado ✓</h2><p>Tu cuenta ya tiene acceso completo.</p>'
                          '<a class="btn" href="/">Ir al chat</a>')
    return _auth_page("Enlace no válido",
                      '<h2>Enlace no válido</h2><p>El enlace ha caducado o ya fue usado. '
                      'Pide uno nuevo desde el chat.</p><a class="btn" href="/">Ir al chat</a>')


@app.post("/auth/resend-verification")
def auth_resend_verification(request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("user_id", 0) == 0:
        raise HTTPException(status_code=401, detail="Inicia sesion para reenviar la verificacion")
    fresh = auth.get_user(engine, user["user_id"])
    if fresh is None:
        raise HTTPException(status_code=401, detail="Cuenta no encontrada")
    if fresh.get("email_verified"):
        return {"success": True, "message": "Tu email ya esta verificado"}
    vtoken = auth.create_verification(engine, user["user_id"])
    email_sender.send_verification_email(fresh["email"], vtoken)
    return {"success": True, "message": "Email de verificacion reenviado"}


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., max_length=128)
    password: str = Field(..., max_length=128)


@app.post("/auth/forgot-password")
def auth_forgot_password(req: ForgotPasswordRequest, request: Request):
    auth.init_auth_tables(engine)
    if _login_rate_limited(request):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera una hora.")
    result = auth.create_password_reset(engine, req.email)
    if result:
        token, user = result
        try:
            email_sender.send_password_reset_email(user["email"], token)
        except Exception:
            traceback.print_exc()
    else:
        _record_failed_login(request)  # cuenta intentos sobre emails inexistentes (anti-enumeracion)
    # Respuesta neutra SIEMPRE: no revela si el email existe (plan 20.3a)
    return {"success": True, "message": "Si el email existe, recibiras un enlace"}


@app.get("/auth/reset-password", response_class=HTMLResponse)
def auth_reset_password_page(token: str = ""):
    return _auth_page("Nueva contraseña", f"""
<h2>Nueva contraseña</h2><p>Escribe tu nueva contraseña (mínimo 8 caracteres).</p>
<div class="pw-wrap"><input type="password" id="pw1" placeholder="Contraseña"><button type="button" class="pw-eye" onclick="tpw(this)" aria-label="Mostrar u ocultar contraseña">👁</button></div>
<div class="pw-wrap"><input type="password" id="pw2" placeholder="Repetir contraseña"><button type="button" class="pw-eye" onclick="tpw(this)" aria-label="Mostrar u ocultar contraseña">👁</button></div>
<div class="err" id="err"></div>
<button onclick="doReset()">Cambiar contraseña</button>
<script>
function tpw(b) {{ var i = b.parentElement.querySelector('input'); if (i.type === 'password') {{ i.type = 'text'; b.textContent = '🙈'; }} else {{ i.type = 'password'; b.textContent = '👁'; }} }}
async function doReset() {{
  const p1 = document.getElementById('pw1').value, p2 = document.getElementById('pw2').value;
  const err = document.getElementById('err');
  if (p1 !== p2) {{ err.textContent = 'Las contraseñas no coinciden'; err.style.display = 'block'; return; }}
  const r = await fetch('/auth/reset-password', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{token: {json.dumps(token)}, password: p1}}) }});
  const data = await r.json();
  if (r.ok && data.success) {{
    document.querySelector('.card').innerHTML = '<div class="logo">H2</div><h2>Contraseña cambiada ✓</h2><p>Ya puedes iniciar sesión.</p><a class="btn" href="/web">Ir al login</a>';
  }} else {{ err.textContent = data.detail || 'Token inválido o expirado'; err.style.display = 'block'; }}
}}
</script>""")


@app.post("/auth/reset-password")
def auth_reset_password(req: ResetPasswordRequest):
    try:
        ok = auth.reset_password(engine, req.token, req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=400, detail="Token invalido o expirado")
    return {"success": True}


# ── GDPR (FASE 20.8c): acceso, portabilidad y supresion ─────────────────────

class AccountDeleteRequest(BaseModel):
    password: str = Field(..., max_length=128)


@app.get("/api/account/export")
def account_export(request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("user_id", 0) == 0:
        raise HTTPException(status_code=401, detail="Inicia sesion para exportar tus datos")
    data = auth.export_user_data(engine, user["user_id"])
    return JSONResponse(content=data, headers={
        "Content-Disposition": 'attachment; filename="h2aichat_mis_datos.json"'})


@app.delete("/api/account")
def account_delete(req: AccountDeleteRequest, request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("user_id", 0) == 0:
        raise HTTPException(status_code=401, detail="Inicia sesion para eliminar tu cuenta")
    if not auth.verify_user_password(engine, user["user_id"], req.password):
        raise HTTPException(status_code=403, detail="Contrasena incorrecta")
    auth.delete_account(engine, user["user_id"])
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth.revoke_token(engine, auth_header[7:])
    return {"success": True, "message": "Cuenta y datos eliminados definitivamente"}


class TurnRequest(BaseModel):
    participant_id: str


class MessageRequest(BaseModel):
    recipient_id: str
    body: str = Field(..., max_length=10000)
    sender_id: str
    thread_id: str = "general"
    lang: str = "es"


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return "<h1>H2AI Chat API</h1><p>Frontend no encontrado</p>"


@app.get("/chat", response_class=HTMLResponse)
def serve_chat():
    # FASE 20.1 (hallazgo UAT PO): la SPA debe poder cargarse sin sesion en el header —
    # el navegador no envia el JWT al navegar; la propia SPA valida via /auth/me y
    # devuelve a /web a quien no tenga sesion valida (logica de 20.2f).
    return serve_frontend()


@app.get("/preguntas", response_class=HTMLResponse)
def serve_bank(request: Request):
    """FASE 36.2 (T3) — banco de preguntas: indice publico de TODAS las conversaciones."""
    import public_index
    lang = resolve_web_lang(request.query_params.get("lang"), request.cookies.get("web_lang"),
                            request.headers.get("accept-language"))
    resp = HTMLResponse(public_index.render_bank(lang, email_sender.base_url()))
    resp.set_cookie("web_lang", lang, max_age=31536000, samesite="lax")
    return resp


@app.get("/web", response_class=HTMLResponse)
def serve_website(request: Request):
    web_path = Path(__file__).parent / "templates" / "indexweb.html"
    if not web_path.exists():
        return HTMLResponse("<h1>H2AI Chat</h1><p>Website no encontrado</p>")
    # FASE 33.1: render i18n server-side. AC-9: ?lang -> cookie -> idioma del navegador (Accept-Language) -> ES.
    lang = resolve_web_lang(request.query_params.get("lang"), request.cookies.get("web_lang"), request.headers.get("accept-language"))
    html = render_web(web_path.read_text(encoding="utf-8"), lang)
    # FASE 36.2: header y footer = COMPONENTE compartido (chrome.py), el MISMO que monta el
    # banco /preguntas. Se inyecta aqui (modo SPA: navTo + estados de login).
    import chrome
    html = html.replace("<!--CHROME_NAV-->", chrome.render_nav(lang, mode="spa"), 1)
    html = html.replace("<!--CHROME_FOOTER-->", chrome.render_footer(lang, mode="spa"), 1)
    # FASE 33.1 T5: galería = datos por idioma, renderizada en servidor (SEO)
    html = html.replace('<div id="galleryGrid" style="margin-top:24px"></div>',
                        f'<div id="galleryGrid" style="margin-top:24px">{render_gallery(lang)}</div>')
    # FASE 33.1 (capa cliente): inyectar idioma + claves web.* para que el JS traduzca lo que pinta
    _web_strings = {k: v for k, v in TRANSLATIONS[lang].items() if k.startswith("web.")}
    _inject = ("<script>window.WEB_LANG=%s;window.WEB_I18N=%s;</script>"
               % (json.dumps(lang), json.dumps(_web_strings, ensure_ascii=False)))
    html = html.replace("</head>", _inject + "</head>", 1)
    # FASE 36.3: SEO de la home (description/OG/canonical/hreflang/robots) — via seo.py, como el resto del sitio.
    _base_url = email_sender.base_url()
    _canonical = _base_url + "/web" + ("?lang=en" if lang == "en" else "")
    _home_title = ("H2AI Chat — Plataforma de diálogo multi-agente de inteligencia artificial"
                   if lang == "es" else
                   "H2AI Chat — Multi-agent artificial intelligence dialogue platform")
    html = seo.inject_home_seo(
        html, lang=lang, title=_home_title,
        desc=TRANSLATIONS[lang].get("web.hero.sub", ""),
        canonical=_canonical, image_url=_base_url + "/static/og-share.png",
        alternates=[("es", _base_url + "/web"), ("en", _base_url + "/web?lang=en"),
                    ("x-default", _base_url + "/web")])
    if lang != "es":
        html = html.replace('<html lang="es">', f'<html lang="{lang}">', 1)
    resp = HTMLResponse(html)
    resp.set_cookie("web_lang", lang, max_age=31536000, samesite="lax")
    return resp


def _resolve_conversation(path: str):
    """FASE 33.1 T5b: resuelve una conversación DENTRO de conversations/, con subcarpetas por
    idioma (en/, y a futuro es/). Anti-traversal: el fichero debe estar contenido en
    conversations/. Devuelve el Path si existe y es .html; si no, None."""
    base = (Path(__file__).parent.parent / "conversations").resolve()
    # T6: ES movido a es/. Probamos la ruta tal cual y, si no existe, en es/ (las
    # URLs planas antiguas —prensa, marcadores— siguen resolviendo sin romperse).
    for candidate in (path, f"es/{path}"):
        p = (base / candidate).resolve()
        if p.is_file() and p.suffix == ".html" and base in p.parents:
            return p
    return None


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    """FASE 36 (T5) — permite el rastreo y apunta al sitemap; cierra zonas privadas."""
    base = email_sender.base_url()
    return ("User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Disallow: /admin\n"
            "Disallow: /chat\n"
            f"Sitemap: {base}/sitemap.xml\n")


@app.get("/sitemap.xml")
def sitemap_xml():
    """FASE 36 (T5) — mapa del sitio generado desde la galeria (fuente unica): se regenera
    solo al anadir conversaciones. Incluye landing (ES/EN) y las conversaciones curadas."""
    from urllib.parse import quote
    base = email_sender.base_url()

    def _xe(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _url(loc, lastmod=None, prio=None):
        parts = ["<url><loc>%s</loc>" % _xe(loc)]
        if lastmod:
            parts.append("<lastmod>%s</lastmod>" % lastmod)
        if prio:
            parts.append("<priority>%s</priority>" % prio)
        parts.append("</url>")
        return "".join(parts)

    urls = [
        _url(base + "/web", prio="1.0"),
        _url(base + "/web?lang=en", prio="0.9"),
        _url(base + "/preguntas", prio="0.9"),
        # FASE 36.3: la raiz "/" (app de chat, tras login) NO va en el sitemap; la home canonica es /web.
    ]
    for rel, meta in sorted(i18n.GALLERY_SEO_INDEX.items()):
        loc = base + "/conversations/" + quote(rel, safe="/")
        urls.append(_url(loc, lastmod=seo._iso_date(meta.get("meta", "")) or None, prio="0.8"))

    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(urls) + "</urlset>")
    return Response(content=body, media_type="application/xml")


def _seo_alternates(rel, base_url):
    """FASE 36 (T6) — hreflang SOLO para pares de traduccion literal reales (p. ej. la
    fundacional). El resto de la galeria son conversaciones distintas por idioma, no
    traducciones: enlazarlas seria incorrecto."""
    other = i18n.SEO_HREFLANG_PAIRS.get(rel)
    if not other:
        return None
    this_lang = i18n.GALLERY_SEO_INDEX.get(rel, {}).get("lang", "es")
    other_lang = i18n.GALLERY_SEO_INDEX.get(other, {}).get("lang", "en")
    es_rel = rel if this_lang == "es" else other
    return [
        (this_lang, base_url + "/conversations/" + rel),
        (other_lang, base_url + "/conversations/" + other),
        ("x-default", base_url + "/conversations/" + es_rel),
    ]


@app.get("/conversations/{path:path}", response_class=HTMLResponse)
def serve_conversation(path: str, request: Request):
    # Se inyecta la barra de navegacion aqui en vez de modificar los 20+ archivos HTML exportados: un solo punto de cambio.
    # FASE 33.1 T5b: subcarpetas por idioma (en/) + anti-traversal en _resolve_conversation.
    conv_path = _resolve_conversation(path)
    if conv_path is not None:
        html = conv_path.read_text(encoding="utf-8")
        # FASE 36.2 (T5): modo EMBED (`?embed=1`) -> pagina "desnuda" para incrustar en blogs.
        _embed = request.query_params.get("embed") == "1"
        # FASE 36 (SEO): reescribimos <head>+<h1> en el MISMO punto que la barra (un solo
        # sitio). Los textos salen de la galeria (fuente unica). Curada -> SEO completo e
        # indexable; no curada (Nivel 0: pruebas/duplicados) -> noindex.
        _conv_base = (Path(__file__).parent.parent / "conversations").resolve()
        _rel = conv_path.relative_to(_conv_base).as_posix()
        _seo_meta = i18n.GALLERY_SEO_INDEX.get(_rel)
        _base_url = email_sender.base_url()
        if _seo_meta:
            _canonical = _base_url + "/conversations/" + _rel
            _og_image = _base_url + "/static/og-share.png"
            html = seo.inject_seo(html, _seo_meta, _canonical, _og_image,
                                  alternates=_seo_alternates(_rel, _base_url))
        else:
            html = seo.inject_noindex(html)
        # La pagina embebida NO debe indexarse (canonical ya apunta a la version normal).
        if _embed:
            html = seo.inject_noindex(html)
        # Pulgares (hallazgo UAT PO 2026-06-12): mismo sistema localStorage que la web
        # estatica (conversacion.html) — sin backend, sin cookies, cada visitante ve su voto.
        nav = """<div style="position:sticky;top:0;z-index:100;background:rgba(246,245,242,0.9);backdrop-filter:blur(12px);border-bottom:1px solid #e0e0e0;padding:10px 24px;display:flex;align-items:center;gap:12px;font-family:system-ui,sans-serif">
  <a href="/web" style="display:flex;align-items:center;gap:8px;text-decoration:none;color:#1a1a1a;font-weight:700;font-size:14px">
    <img src="/static/logo.png" alt="H2AI Chat" style="width:26px;height:26px;object-fit:contain"> H2AI Chat
  </a>
  <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
    <button id="h2aiVoteUp" onclick="h2aiVote(1)" style="border:1px solid #e0e0e0;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px">&#128077; <span id="h2aiCountUp">0</span></button>
    <button id="h2aiVoteDown" onclick="h2aiVote(-1)" style="border:1px solid #e0e0e0;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px">&#128078; <span id="h2aiCountDown">0</span></button>
    <a href="/web" style="text-decoration:none;color:#5a5855;font-size:12px;font-weight:500;padding:5px 12px;border-radius:6px;transition:all.15s" onmouseover="this.style.background='#f0eee9'" onmouseout="this.style.background='none'">&larr; __BACK__</a>
  </div>
</div>
<script>
(function(){
  var convId = __CONV_ID__;
  function load(){
    var stored = JSON.parse(localStorage.getItem("h2ai_votes")||"{}");
    var v = stored[convId]||{up:0,down:0,user:0};
    document.getElementById("h2aiCountUp").textContent = v.up;
    document.getElementById("h2aiCountDown").textContent = v.down;
    document.getElementById("h2aiVoteUp").style.borderColor = v.user===1 ? "#E8186E" : "#e0e0e0";
    document.getElementById("h2aiVoteDown").style.borderColor = v.user===-1 ? "#E8186E" : "#e0e0e0";
  }
  window.h2aiVote = function(dir){
    var stored = JSON.parse(localStorage.getItem("h2ai_votes")||"{}");
    var v = stored[convId]||{up:0,down:0,user:0};
    if(v.user===dir) return;
    if(v.user===1) v.up--;
    if(v.user===-1) v.down--;
    v.user=dir;
    if(dir===1) v.up++;
    if(dir===-1) v.down++;
    stored[convId]=v;
    localStorage.setItem("h2ai_votes",JSON.stringify(stored));
    try{fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'public',conversation_id:convId,vote:dir===1?'up':'down'})});}catch(e){}
    load();
  };
  load();
})();
</script>"""
        # FASE 33.1: el boton "Volver" de la barra inyectada se traduce segun el idioma de la conversacion (en/ -> EN).
        _conv_lang = "en" if path.startswith("en/") else "es"
        _en = _conv_lang == "en"
        nav = nav.replace("__BACK__", "Back" if _en else "Volver")
        nav = nav.replace("__CONV_ID__", json.dumps(conv_path.stem))
        # FASE 36.2 (T7): boton "Insertar" (embed) en la barra + recuadro con el <iframe>.
        _embed_url = _base_url + "/conversations/" + _rel + "?embed=1"
        _iframe = ('<iframe src="%s" width="100%%" height="600" '
                   'style="border:1px solid #eee;border-radius:8px" loading="lazy"></iframe>' % _embed_url)
        _embed_lbl = "Embed" if _en else "Insertar"
        _copy_lbl = "Copy" if _en else "Copiar"
        _embed_btn = ('<button onclick="h2aiEmbedToggle()" style="border:1px solid #e0e0e0;background:#fff;'
                      'border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px">&lt;/&gt; %s</button>'
                      % _embed_lbl)
        nav = nav.replace('<button id="h2aiVoteUp"', _embed_btn + '<button id="h2aiVoteUp"', 1)
        _embed_box = (
            '<div id="h2aiEmbedBox" style="display:none;background:#fff;border-bottom:1px solid #e0e0e0;'
            'padding:12px 24px;font-family:system-ui,sans-serif">'
            '<div style="max-width:760px;margin:0 auto;display:flex;gap:8px;align-items:center">'
            '<textarea id="h2aiEmbedCode" readonly style="flex:1;height:46px;font-family:monospace;'
            'font-size:11px;border:1px solid #e0e0e0;border-radius:6px;padding:8px;resize:none">%s</textarea>'
            '<button onclick="h2aiEmbedCopy()" style="border:0;background:#E8186E;color:#fff;'
            'border-radius:6px;padding:8px 14px;cursor:pointer;font-size:12px;white-space:nowrap">%s</button>'
            '</div></div>'
            '<script>function h2aiEmbedToggle(){var b=document.getElementById("h2aiEmbedBox");'
            'b.style.display=b.style.display==="none"?"block":"none";}'
            'function h2aiEmbedCopy(){var t=document.getElementById("h2aiEmbedCode");t.select();'
            'try{navigator.clipboard.writeText(t.value);}catch(e){document.execCommand("copy");}}</script>'
            % (_html_escape(_iframe), _copy_lbl)
        )
        # Favicon en la pestana (los HTML exportados no lo traen): inyectado aqui, un solo punto.
        if "</head>" in html:
            html = html.replace("</head>", '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">'
                                '<meta name="ai-generated" content="true"></head>', 1)
        # FASE 35 (AI Act Art. 50): aviso de contenido generado por IA, arriba del cuerpo (scrollea con la pagina).
        _ai_notice = ('<div style="background:#FFF3D6;border-bottom:1px solid #EBCF8A;color:#6B4E00;'
                      'font-size:12px;line-height:1.5;padding:9px 18px;text-align:center">&#9888; %s</div>'
                      % TRANSLATIONS.get(_conv_lang, TRANSLATIONS["es"]).get("ai.notice", ""))
        if _embed:
            # Modo embed: sin barra ni votos; solo el aviso AI Act + un pie discreto de vuelta.
            _foot = ('<div style="font-family:system-ui,sans-serif;text-align:center;padding:10px;'
                     'font-size:12px;color:#888;border-top:1px solid #eee">'
                     '<a href="%s" target="_blank" rel="noopener" style="color:#E8186E;text-decoration:none;'
                     'font-weight:600">%s</a></div>'
                     % (_base_url + "/conversations/" + _rel, "via H2AI Chat" if _en else "vía H2AI Chat"))
            if "<body>" in html:
                html = html.replace("<body>", "<body>" + _ai_notice, 1)
            elif "<main>" in html:
                html = html.replace("<main>", _ai_notice + "<main>", 1)
            html = html.replace("</body>", _foot + "</body>", 1) if "</body>" in html else html + _foot
        else:
            _top = nav + _embed_box + _ai_notice
            if "<body>" in html:
                html = html.replace("<body>", "<body>" + _top, 1)
            elif "<main>" in html:
                html = html.replace("<main>", _top + "<main>", 1)
        return HTMLResponse(content=html)
    raise HTTPException(status_code=404, detail="Conversacion no encontrada")


@app.get("/status")
def get_status(request: Request, thread_id: str = Query("general")):
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    state = engine.read_state(auth.scope_thread(user, thread_id))
    return {
        "state": state.get("state"),
        "current_turn": state.get("current_turn"),
        "queue": state.get("queue", []),
        "participants": list(state.get("participants", {}).keys()),
        "turn_history": state.get("turn_history", [])[-5:]
    }


@app.get("/api/turn-history")
def get_turn_history(request: Request, thread_id: str = Query("general")):
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    state = engine.read_state(auth.scope_thread(user, thread_id))
    return {
        "history": state.get("turn_history", []),
        "queue": state.get("queue", []),
        "current_turn": state.get("current_turn")
    }


@app.get("/api/participants")
def get_participants():
    state = engine.read_state()
    participants = state.get("participants", {})
    result = []
    for pid, info in participants.items():
        result.append({
            "id": pid,
            "type": info.get("type"),
            "role": info.get("role"),
            "status": info.get("status"),
            "email": info.get("email"),
            "provider": info.get("provider"),  # FASE 40.1 (T5): para el distintivo nube/local
        })
    return {"participants": result}


@app.get("/api/all-messages")
def get_all_messages(request: Request, thread_id: str = None):
    user = getattr(request.state, "user", None)
    # FASE 20.1 (hallazgo UAT PO): el nombre del hilo se traduce tambien al LEER, igual
    # que al escribir, y se devuelve el canonico para que el frontend se sincronice.
    # Sin esto, la carga inicial pedia "general" y el usuario veia la pantalla en blanco.
    scoped = auth.scope_thread(user, thread_id) if thread_id else None
    state = engine.read_state()
    participants = state.get("participants", {})
    all_msgs = []
    for pid in participants:
        msgs = engine.get_messages(pid, thread_id=scoped)
        all_msgs.extend(msgs)
    # FASE 20.2e: un usuario real solo ve sus propios threads
    all_msgs = [m for m in all_msgs if auth.visible_to_user(user, m.get("thread_id", "general"))]
    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return {"messages": all_msgs, "count": len(all_msgs), "thread_id": scoped}


@app.get("/api/threads")
def get_threads(request: Request):
    user = getattr(request.state, "user", None)
    state = engine.read_state()
    participants = state.get("participants", {})
    threads = set()
    for pid in participants:
        msgs = engine.get_messages(pid)
        for m in msgs:
            tid = m.get("thread_id", "general")
            if auth.visible_to_user(user, tid):
                threads.add(tid)
    if not threads:
        threads.add(auth.scope_thread(user, "general"))
    shared = []
    try:
        if user and user.get("user_id"):
            shared = auth.list_shared_threads(engine, user["user_id"])
    except Exception:
        shared = []
    return {"threads": sorted(threads), "shared": shared}


@app.post("/turn/acquire")
def acquire_turn(req: TurnRequest):
    try:
        ok = engine.acquire_turn(req.participant_id)
        return {"success": ok, "message": "Turn acquired" if ok else "Turn already held"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/turn/release")
def release_turn(req: TurnRequest):
    try:
        ok = engine.release_turn(req.participant_id)
        if not ok:
            ok = engine.force_release_turn(req.participant_id)
        return {"success": ok, "message": "Turn released" if ok else "Not your turn"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/message/send")
def send_message(req: MessageRequest, request: Request):
    user = getattr(request.state, "user", None)
    try:
        msg_id = engine.send_message(req.recipient_id, req.body, req.sender_id,
                                     thread_id=auth.scope_thread(user, req.thread_id))
        return {"success": True, "message_id": msg_id}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/messages/{participant_id}")
def get_messages(participant_id: str, unread_only: bool = False, thread_id: str = None):
    try:
        msgs = engine.get_messages(participant_id, unread_only=unread_only, thread_id=thread_id if thread_id else None)
        return {"participant_id": participant_id, "count": len(msgs), "messages": msgs}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/messages/{participant_id}/read")
def mark_read(participant_id: str, message_id: str = ""):
    ok = engine.mark_as_read(participant_id, message_id)
    return {"success": ok}


@app.delete("/api/thread/{thread_id}")
def delete_thread(thread_id: str, request: Request):
    user = getattr(request.state, "user", None)
    if not auth.visible_to_user(user, thread_id):
        raise HTTPException(status_code=403, detail="Este hilo no es tuyo")
    conn = engine._get_conn()
    c = conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
    deleted = c.rowcount
    conn.execute("DELETE FROM shared_conversation WHERE thread_id = ?", (thread_id,))  # Fase 34: mata el enlace publico
    conn.commit()
    conn.close()
    return {"deleted": deleted}


ORCHESTRATE_SYSTEM = "Eres {bot_id}, un asistente en una conversacion entre varios agentes. EMPIEZA tu respuesta con ({bot_id}) y TERMINALA con (/{bot_id}). No consensuéis ni discutáis de entrada o gratuitamente, criticad a las otras IAs, pero con educación y escribid con un lenguaje sencillo, sin florituras (todo en el idioma de la pregunta, tratando de no repetiros y cuidando las tildes)."
# Version en ingles: se usa cuando la UI esta en ingles (req.lang=='en') para que las IAs respondan en ingles
ORCHESTRATE_SYSTEM_EN = "You are {bot_id}, an assistant in a conversation between several agents. START your reply with ({bot_id}) and END it with (/{bot_id}). Don't jump to conclusions or argue immediately or gratuitously. Critique other AIs, but do so politely and in simple language, without embellishment (all in the language of the question and try to not repeat yourself)."

BOTS_CONFIG_DEFAULT = {
    "qwen_plus":      {"provider": "cloud", "model": "qwen3.7-plus",      "role": "creativo",  "email": "qwen_plus@bot.humania.local",      "max_tokens": 800},
    "minimax":        {"provider": "cloud", "model": "minimax-m2.7",      "role": "estratega", "email": "minimax@bot.humania.local",        "max_tokens": 800},
    "deepseek_flash": {"provider": "cloud", "model": "deepseek-v4-flash", "role": "analista",  "email": "deepseek_flash@bot.humania.local", "max_tokens": 2000},
}

# Ids alineados al catalogo (qwen_plus/minimax/deepseek_flash) para no crear bots
# "fantasma" al reaplicar el perfil (antes usaba qwen/deepseek, ids divergentes).
PROFILE_OPENCODE = {
    "qwen_plus":      {"provider": "cloud", "model": "qwen3.7-plus",      "role": "creativo",  "email": "qwen_plus@bot.humania.local",      "max_tokens": 800},
    "minimax":        {"provider": "cloud", "model": "minimax-m2.7",      "role": "estratega", "email": "minimax@bot.humania.local",        "max_tokens": 800},
    "deepseek_flash": {"provider": "cloud", "model": "deepseek-v4-flash", "role": "analista",  "email": "deepseek_flash@bot.humania.local", "max_tokens": 2000},
}

PROFILE_OPENROUTER = {
    "gpt":    {"provider": "openrouter", "model": "openai/gpt-5.4",              "role": "creativo",  "email": "gpt@bot.humania.local",    "max_tokens": 1500},
    "claude": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6",  "role": "estratega", "email": "claude@bot.humania.local", "max_tokens": 1500},
    "gemini": {"provider": "openrouter", "model": "google/gemini-3.5-flash",      "role": "analista",  "email": "gemini@bot.humania.local", "max_tokens": 2000},
}

PROFILES = {"opencode": PROFILE_OPENCODE, "openrouter": PROFILE_OPENROUTER}

# FASE 27 (pieza B): catálogo de IAs disponibles. El usuario elige las suyas de aquí,
# filtradas por su plan (proveedor permitido + nº máximo). El admin podrá curarlo más adelante.
MODEL_CATALOG_DEFAULT = [
    {"id": "qwen_plus",      "label": "Qwen",     "model": "qwen3.7-plus",                "provider": "cloud",      "role": "creativo",  "email": "qwen_plus@bot.humania.local",      "max_tokens": 800},
    {"id": "minimax",        "label": "MiniMax",  "model": "minimax-m2.7",                "provider": "cloud",      "role": "estratega", "email": "minimax@bot.humania.local",        "max_tokens": 800},
    {"id": "deepseek_flash", "label": "DeepSeek", "model": "deepseek-v4-flash",           "provider": "cloud",      "role": "analista",  "email": "deepseek_flash@bot.humania.local", "max_tokens": 2000},
    {"id": "kimi",           "label": "Kimi",     "model": "kimi-k2.6",                   "provider": "cloud",      "role": "creativo",  "email": "kimi@bot.humania.local",           "max_tokens": 1500, "reasoning_effort": "none"},
    {"id": "glm",            "label": "GLM",      "model": "glm-5.2",                     "provider": "cloud",      "role": "estratega", "email": "glm@bot.humania.local",            "max_tokens": 2000},
    {"id": "mimo",           "label": "MiMo",     "model": "mimo-v2.5-pro",               "provider": "cloud",      "role": "analista",  "email": "mimo@bot.humania.local",           "max_tokens": 1500},
    {"id": "gpt",            "label": "GPT-5.4",  "model": "openai/gpt-5.4",              "provider": "openrouter", "role": "creativo",  "email": "gpt@bot.humania.local",            "max_tokens": 1500},
    {"id": "claude",         "label": "Claude",   "model": "anthropic/claude-sonnet-4.6", "provider": "openrouter", "role": "estratega", "email": "claude@bot.humania.local",         "max_tokens": 1500},
    {"id": "gemini",         "label": "Gemini",   "model": "google/gemini-3.5-flash",     "provider": "openrouter", "role": "analista",  "email": "gemini@bot.humania.local",         "max_tokens": 2000},
]


def get_model_catalog(engine):
    raw = engine.get_setting("model_catalog")
    if raw:
        try:
            c = json.loads(raw)
            if isinstance(c, list) and c:
                return c
        except json.JSONDecodeError:
            pass
    return MODEL_CATALOG_DEFAULT


def normalize_ghost_bots(engine):
    """Al arrancar: apaga (status=inactive, NO borra) los bots 'activos' cuyo id no
    esta ni en el catalogo ni en la config por defecto. Son fantasmas de perfiles
    antiguos (p. ej. qwen/deepseek del viejo perfil Economico, hoy qwen_plus/
    deepseek_flash) que salian con 0 turnos en el dashboard. La orquestacion ya los
    ignoraba; esto solo evita que aparezcan 'activos'. Reversible e idempotente."""
    try:
        valid = {m["id"] for m in get_model_catalog(engine)} | set(BOTS_CONFIG_DEFAULT.keys())
        parts = engine.read_state().get("participants", {})
        apagados = []
        for pid, info in parts.items():
            if info.get("type") == "bot" and info.get("status") == "active" and pid not in valid:
                if engine.set_participant_inactive(pid):
                    apagados.append(pid)
        return apagados
    except Exception:
        return []  # best-effort: nunca debe tumbar el arranque


# Limpieza de fantasmas al arrancar (apaga bots fuera del catalogo; reversible)
normalize_ghost_bots(engine)


def effective_user_bots(engine, user, global_bots_config):
    """Pieza B: si el usuario eligió IAs (y su plan las permite), usa esas; si no, el global.
    Filtra por proveedor (free/basic sin OpenRouter) y por el nº máximo del plan."""
    plan = user.get("plan") or "free"
    all_limits = get_plan_limits(engine)
    limits = all_limits.get(plan, all_limits["free"])
    chosen = auth.get_user_prefs(engine, user.get("user_id")).get("models")
    if not chosen:
        return global_bots_config
    cat = {m["id"]: m for m in get_model_catalog(engine)}
    allow_or = bool(limits.get("openrouter"))
    ids = [mid for mid in chosen if mid in cat and (allow_or or cat[mid].get("provider") != "openrouter")]
    ids = ids[:int(limits.get("max_models", 3))]
    if not ids:
        return global_bots_config
    def _bot(mid):
        b = {k: cat[mid][k] for k in ("provider", "model", "role", "email", "max_tokens")}
        if cat[mid].get("reasoning_effort"):  # opcional: bajar/quitar razonamiento (p. ej. Kimi)
            b["reasoning_effort"] = cat[mid]["reasoning_effort"]
        return b
    return {mid: _bot(mid) for mid in ids}


def is_free_model(model: str) -> bool:
    """Modelos 'free' de los gateways (Zen: sufijo '-free'; OpenRouter: ':free').

    Prohibidos por RGPD: retienen/entrenan con el contenido (ver docs/calidad-seguridad-legal/GDPR.md §2.1).
    """
    if not model:
        return False
    m = str(model).strip().lower()
    return m.endswith("-free") or m.endswith(":free") or ":free" in m


def assert_no_free_models(bots_config: dict) -> None:
    """Lanza HTTP 400 si algun bot usa un modelo 'free' (entrena/retiene)."""
    if not isinstance(bots_config, dict):
        return
    offenders = [cfg.get("model") for cfg in bots_config.values()
                 if isinstance(cfg, dict) and is_free_model(cfg.get("model"))]
    if offenders:
        raise HTTPException(
            status_code=400,
            detail=("Modelos 'free' no permitidos (retienen/entrenan con el contenido, "
                    f"ver docs/calidad-seguridad-legal/GDPR.md §2.1): {', '.join(offenders)}"),
        )


# ── FASE 32: editor del catálogo de IAs en /admin ───────────────────────────
CATALOG_PROVIDERS = ("cloud", "openrouter")
CATALOG_TOKENS_RANGE = (64, 4000)
CATALOG_ROLES = ("creativo", "estratega", "analista")
# OpenRouter tiene ~300 modelos y cobra por token -> lista CURADA (vetados). OpenCode
# se lista en vivo via GET /models (tarifa plana, todos OK).
OPENROUTER_SUGGESTIONS = ["openai/gpt-5.4", "anthropic/claude-sonnet-4.6", "google/gemini-3.5-flash"]


def validate_catalog(entries):
    """Valida y NORMALIZA el catálogo. Lanza HTTP 400 si algo no cuadra."""
    import re as _re
    if not isinstance(entries, list) or not entries:
        raise HTTPException(status_code=400, detail="El catálogo no puede estar vacío.")
    seen, clean = set(), []
    for e in entries:
        if not isinstance(e, dict):
            raise HTTPException(status_code=400, detail="Entrada de catálogo inválida.")
        mid = _re.sub(r"[^a-z0-9_]", "", (e.get("id") or "").strip().lower())
        if not mid:
            raise HTTPException(status_code=400, detail="Cada IA necesita un id (solo letras, números y _).")
        if mid in seen:
            raise HTTPException(status_code=400, detail=f"Id duplicado: {mid}")
        seen.add(mid)
        model = (e.get("model") or "").strip()
        if not model:
            raise HTTPException(status_code=400, detail=f"La IA '{mid}' necesita un modelo.")
        if is_free_model(model):
            raise HTTPException(status_code=400, detail=f"Modelo 'free' no permitido (RGPD): {model}")
        provider = (e.get("provider") or "cloud").strip().lower()
        if provider not in CATALOG_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Proveedor inválido en '{mid}': {provider}")
        try:
            mt = int(e.get("max_tokens", 800))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"max_tokens inválido en '{mid}'.")
        mt = max(CATALOG_TOKENS_RANGE[0], min(mt, CATALOG_TOKENS_RANGE[1]))
        entry = {"id": mid, "label": (e.get("label") or mid).strip()[:40], "model": model,
                 "provider": provider, "role": (e.get("role") or "creativo").strip()[:30],
                 "email": f"{mid}@bot.humania.local", "max_tokens": mt}
        if e.get("reasoning_effort"):  # de momento el toggle solo pone 'none'
            entry["reasoning_effort"] = "none"
        clean.append(entry)
    return clean


@app.get("/api/admin/catalog")
def admin_get_catalog(request: Request):
    _require_admin(request)
    return {"catalog": get_model_catalog(engine), "default": MODEL_CATALOG_DEFAULT,
            "providers": list(CATALOG_PROVIDERS), "roles": list(CATALOG_ROLES),
            "tokens_range": list(CATALOG_TOKENS_RANGE), "openrouter_suggestions": OPENROUTER_SUGGESTIONS}


@app.post("/api/admin/catalog")
def admin_save_catalog(request: Request, body: dict):
    _require_admin(request)
    clean = validate_catalog(body.get("catalog", []))
    engine.set_setting("model_catalog", json.dumps(clean))
    return {"ok": True, "catalog": clean}


@app.post("/api/admin/catalog/reset")
def admin_reset_catalog(request: Request):
    _require_admin(request)
    engine.set_setting("model_catalog", "")  # vacío -> get_model_catalog cae al default
    return {"ok": True, "catalog": MODEL_CATALOG_DEFAULT}


@app.post("/api/admin/restart")
def admin_restart(request: Request):
    """Reinicia el proceso del servidor. Seguro: systemd (Restart=always) lo levanta
    en segundos. SIGTERM -> uvicorn cierra con gracia (espera a lo que esté en vuelo)."""
    _require_admin(request)
    is_test = getattr(request.client, "host", None) == "testclient"
    if not is_test:
        def _bye():
            _time.sleep(0.4)  # deja salir la respuesta HTTP antes de morir
            try:
                import signal
                os.kill(os.getpid(), signal.SIGTERM)
            except Exception:
                os._exit(0)
        _threading.Thread(target=_bye, daemon=True).start()
    return {"ok": True, "message": "Reiniciando el servidor… volverá en unos segundos."}


# ── FASE 30: control del servicio de PRE-PROD (staging) desde /admin ─────────────
STAGING_SERVICE = "humania-staging"


def _staging_systemctl(action: str):
    """Ejecuta systemctl sobre el servicio de staging. 'status' (is-active) no necesita
    root; 'start'/'stop' van con `sudo -n` (requiere una entrada sudoers NOPASSWD acotada
    a estos comandos). Devuelve (returncode, stdout, stderr); nunca lanza."""
    import subprocess
    if action == "status":
        cmd = ["systemctl", "is-active", STAGING_SERVICE]
    elif action in ("start", "stop"):
        cmd = ["sudo", "-n", "systemctl", action, STAGING_SERVICE]
    else:
        return -1, "", "accion invalida"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return -1, "", str(e)


@app.get("/api/admin/staging/status")
def admin_staging_status(request: Request):
    _require_admin(request)
    rc, out, err = _staging_systemctl("status")
    state = out or ("desconocido" if rc < 0 else "inactive")
    return {"service": STAGING_SERVICE, "active": (out == "active"), "state": state}


@app.post("/api/admin/staging/start")
def admin_staging_start(request: Request):
    _require_admin(request)
    rc, out, err = _staging_systemctl("start")
    if rc != 0:
        return JSONResponse(status_code=200, content={"ok": False,
            "error": err or "no se pudo arrancar (¿falta el permiso sudo en el servidor?)"})
    return {"ok": True}


@app.post("/api/admin/staging/stop")
def admin_staging_stop(request: Request):
    _require_admin(request)
    rc, out, err = _staging_systemctl("stop")
    if rc != 0:
        return JSONResponse(status_code=200, content={"ok": False,
            "error": err or "no se pudo parar (¿falta el permiso sudo en el servidor?)"})
    return {"ok": True}


@app.post("/api/admin/reboot")
def admin_reboot(request: Request):
    """Reinicia la MÁQUINA entera (droplet) via `sudo -n systemctl reboot`. Requiere sudoers
    NOPASSWD acotado. PROD y PRE vuelven solos (servicios habilitados en el boot)."""
    _require_admin(request)
    if getattr(request.client, "host", None) == "testclient":
        return {"ok": True, "message": "(test) no se reinicia"}
    import subprocess
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", "reboot"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return JSONResponse(status_code=200, content={"ok": False,
                "error": (r.stderr or "").strip() or "no se pudo (¿falta el permiso sudo en el servidor?)"})
    except Exception as e:
        return JSONResponse(status_code=200, content={"ok": False, "error": str(e)})
    return {"ok": True, "message": "Reiniciando la máquina…"}


@app.get("/api/admin/provider-models")
def admin_provider_models(request: Request, provider: str = "cloud"):
    """Modelos para el desplegable al añadir IA. OpenRouter: lista curada; OpenCode: en vivo."""
    _require_admin(request)
    if provider == "openrouter":
        return {"models": OPENROUTER_SUGGESTIONS}
    try:
        import requests as _rq
        from opencode_go import _load_api_key
        r = _rq.get("https://opencode.ai/zen/go/v1/models",
                    headers={"Authorization": "Bearer " + _load_api_key()}, timeout=8)
        if r.status_code == 200:
            data = r.json()
            rows = data.get("data", data if isinstance(data, list) else [])
            return {"models": [m.get("id") for m in rows if m.get("id")]}
    except Exception:
        pass
    return {"models": []}


SETTINGS_DEFAULTS = {
    "orchestrate_rounds": "5",
    "orchestrate_llm_timeout": "90",
    "orchestrate_max_seconds": "800",  # FASE 29: con la orquestacion ASINCRONA ya NO depende de nginx (no hay 504); pasa a ser FRENO DE COSTE/runaway. Default 800 (PO 2026-06-23).
    "orchestrate_bot_delay": "2",
    "orchestrate_context_limit": "3",
    "moderator_pause_seconds": "0",
    "llm_temperature": "0.4",
    "llm_max_tokens": "800",
    "llm_system_prompt": ORCHESTRATE_SYSTEM,
    "llm_system_prompt_en": ORCHESTRATE_SYSTEM_EN,
    "bots_config": json.dumps(BOTS_CONFIG_DEFAULT),
    # FASE 40.1: dirección (global) del servidor de modelos LOCAL, compatible con OpenAI.
    # Sirve para LM Studio (:1234) y Ollama (:11434). La usan los agentes con provider="local".
    # FASE 40.2: la variable de entorno LOCAL_SERVER_URL fija el default (docker-compose la
    # apunta al servicio ollama: http://ollama:11434/v1) para que funcione "de fábrica".
    "local_server_url": os.environ.get("LOCAL_SERVER_URL", "http://localhost:1234/v1"),
}


def _default_local_url() -> str:
    return os.environ.get("LOCAL_SERVER_URL", "http://localhost:1234/v1")


@app.get("/api/settings")
def get_settings():
    return {"settings": engine.get_all_settings(SETTINGS_DEFAULTS)}


# Topes sanos para la config global de orquestacion (PO 2026-06-19): evitan
# valores absurdos que disparan coste/tiempo (p. ej. 99 rondas x 4000 tokens). (min, max) inclusive.
SETTINGS_NUMERIC_LIMITS = {
    "orchestrate_rounds": (1, 5),
    "orchestrate_llm_timeout": (5, 120),
    "orchestrate_max_seconds": (30, 1800),  # FASE 29: async -> freno de coste, ya sin el corse de los 300s de nginx
    "orchestrate_bot_delay": (0, 30),
    "orchestrate_context_limit": (1, 9),
    "moderator_pause_seconds": (0, 60),
    "llm_temperature": (0.0, 1.2),
    "llm_max_tokens": (64, 2000),
}


# FASE 27: límites MÁXIMOS por plan. El admin los edita desde el panel; cada usuario
# podrá ajustar sus variables SIN superar el máximo de su plan (la aplicación de estos
# límites a las conversaciones es una tarea posterior; esto es la tabla editable).
PLAN_LIMITS_DEFAULT = {
    "free":    {"max_rounds": 3,  "openrouter": False, "max_models": 3,  "max_context": 3,  "max_tokens": 800,  "max_creativity": 2},
    "basic":   {"max_rounds": 5,  "openrouter": False, "max_models": 5,  "max_context": 4,  "max_tokens": 1200, "max_creativity": 2},
    "premium": {"max_rounds": 20, "openrouter": True,  "max_models": 10, "max_context": 10, "max_tokens": 2000, "max_creativity": 2},
}
# Campos de la tabla: (clave, etiqueta, tipo). Añadir más filas es solo ampliar esta lista.
PLAN_LIMIT_FIELDS = [
    ("max_rounds",     "Máx. rondas",                                "int"),
    ("openrouter",     "Acceso a OpenRouter",                         "bool"),
    ("max_models",     "Máx. modelos (IAs)",                          "int"),
    ("max_context",    "Máx. contexto (mensajes)",                    "int"),
    ("max_tokens",     "Máx. tokens por respuesta",                   "int"),
    ("max_creativity", "Máx. creatividad (0=enfocada · 2=creativa)",  "int"),
]
PLAN_ORDER = ["free", "basic", "premium"]

# Creatividad: 3 niveles amigables -> temperatura real del modelo.
CREATIVITY_TEMP = {0: 0.2, 1: 0.5, 2: 0.9}
CREATIVITY_LABELS = ["Enfocada", "Equilibrada", "Creativa"]


def get_plan_limits(engine) -> dict:
    """Límites por plan guardados (o los por defecto). Se completa lo que falte con el default."""
    raw = engine.get_setting("plan_limits")
    stored = {}
    if raw:
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            stored = {}
    out = {}
    for plan in PLAN_ORDER:
        out[plan] = dict(PLAN_LIMITS_DEFAULT[plan])
        out[plan].update(stored.get(plan, {}))
    return out


def effective_user_config(engine, user, settings) -> dict:
    """FASE 27: la config que se USA en una conversación = la preferencia del usuario, acotada
    al máximo de su plan; si el usuario no ha elegido, cae al ajuste global. Devuelve los valores
    finales (rondas, tokens, temperatura) + los límites del plan (para que el engranaje los muestre)."""
    plan = (user.get("plan") or "free")
    all_limits = get_plan_limits(engine)
    limits = all_limits.get(plan, all_limits["free"])
    prefs = auth.get_user_prefs(engine, user.get("user_id"))

    rounds = int(prefs.get("rounds", settings.get("orchestrate_rounds", 3)))
    rounds = max(1, min(rounds, int(limits["max_rounds"])))

    tokens = int(prefs.get("max_tokens", settings.get("llm_max_tokens", 800)))
    tokens = max(64, min(tokens, int(limits["max_tokens"])))

    cap = int(limits.get("max_creativity", 2))
    if "creativity" in prefs:
        lvl = max(0, min(int(prefs["creativity"]), cap))
        temperature = CREATIVITY_TEMP.get(lvl, 0.5)
    else:
        temperature = float(settings.get("llm_temperature", 0.4))

    return {"rounds": rounds, "max_tokens": tokens, "temperature": temperature,
            "plan": plan, "limits": limits,
            "system_prompt_extra": (prefs.get("system_prompt_extra") or "")}


@app.post("/api/settings")
def update_settings(settings: dict, request: Request):
    _require_admin(request)  # solo admin/maestro: era un agujero (cualquier usuario reescribia la config global)
    for key, value in settings.items():
        if key in SETTINGS_DEFAULTS:
            v = str(value)
            if key == "bots_config":
                try:
                    parsed = json.loads(v)
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="bots_config no es JSON valido")
                assert_no_free_models(parsed)
            if key in SETTINGS_NUMERIC_LIMITS:
                try:
                    num = float(v)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"{key} debe ser numerico")
                lo, hi = SETTINGS_NUMERIC_LIMITS[key]
                if not (lo <= num <= hi):
                    raise HTTPException(status_code=400, detail=f"{key} fuera de rango ({lo}-{hi})")
            if key == "local_server_url":
                v = v.strip()
                if not (v.startswith("http://") or v.startswith("https://")):
                    raise HTTPException(status_code=400, detail="local_server_url debe empezar por http:// o https://")
            engine.set_setting(key, v)
    return {"success": True}


@app.get("/api/local/test")
def test_local_server(request: Request, url: str = None):
    """FASE 40.1 (T3): comprueba si el servidor de modelos LOCAL responde y lista sus modelos.
    `url` opcional para probar una dirección antes de guardarla; si no, usa el ajuste actual."""
    _require_admin(request)
    base = (url or engine.get_setting("local_server_url") or _default_local_url()).strip()
    if not (base.startswith("http://") or base.startswith("https://")):
        return {"ok": False, "error": "La dirección debe empezar por http:// o https://"}
    try:
        import requests
        r = requests.get(base.rstrip("/") + "/models", timeout=4)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", data if isinstance(data, list) else [])
        models = [m.get("id") for m in rows if isinstance(m, dict) and m.get("id")]
        return {"ok": True, "url": base, "models": models}
    except Exception as e:
        return {"ok": False, "url": base, "error": str(e)[:200]}


@app.post("/api/settings/reset")
def reset_settings(request: Request):
    _require_admin(request)
    conn = engine._get_conn()
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    engine.set_setting("bots_config", json.dumps(BOTS_CONFIG_DEFAULT))
    return {"success": True}


@app.post("/api/settings/profile")
def load_profile(request: Request, profile: str = "opencode"):
    _require_admin(request)
    if profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Perfil desconocido: {profile}. Usa: opencode, openrouter")
    engine.set_setting("bots_config", json.dumps(PROFILES[profile]))
    state = engine.read_state()
    existing = state.get("participants", {})
    new_bots = PROFILES[profile]
    conn = engine._get_conn()
    try:
        conn.execute("BEGIN")
        for bot_id, cfg in new_bots.items():
            conn.execute("INSERT OR REPLACE INTO participants (id, role, type, email, provider, status, registered_at, last_seen) VALUES (?,?,?,?,?,'active',COALESCE((SELECT registered_at FROM participants WHERE id=?),datetime('now')),datetime('now'))",
                         (bot_id, cfg["role"], "bot", cfg["email"], cfg["provider"], bot_id))
        conn.execute("UPDATE participants SET status='inactive' WHERE type='bot' AND id NOT IN ({})".format(','.join('?'*len(new_bots))),
                     list(new_bots.keys()))
        # FASE 31: el moderador ya no es un participante global 'miguel'; se registra por-usuario
        # (su email) en /orchestrate. Aqui no se inserta ningun moderador.
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    engine.clear_all_queues()      # FASE 24: cambio de perfil = reset global de todas las conversaciones
    engine.hard_reset_all()
    return {"success": True, "profile": profile, "bots": list(new_bots.keys())}


@app.post("/api/reset")
def factory_reset(request: Request):
    _require_admin(request)  # destructivo: borra messages/participants/settings
    conn = engine._get_conn()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM turn_history")
    conn.execute("DELETE FROM queue")
    conn.execute("UPDATE turns SET current_turn=NULL, started_at=NULL, state='idle', stop_flag=0")  # FASE 24: soltar FK a participants antes de borrarlos
    conn.execute("DELETE FROM participants")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()
    engine.hard_reset_all()
    engine.set_setting("bots_config", json.dumps(BOTS_CONFIG_DEFAULT))
    return {"success": True, "message": "Sistema reiniciado. Todos los datos borrados."}


@app.get("/api/settings/profiles")
def list_profiles():
    return {"profiles": {name: list(bots.keys()) for name, bots in PROFILES.items()}}


class ImportRequest(BaseModel):
    html: str = Field(..., max_length=5_000_000)

@app.post("/api/import")
def import_conversation(req: ImportRequest, request: Request):
    _require_admin(request)
    import re, json
    match = re.search(r'<script type="application/json" id="messages-data">(.*?)</script>', req.html, re.DOTALL)
    if not match:
        return {"imported": 0, "total": 0, "error": "No se encontro el bloque messages-data en el HTML"}
    try:
        messages = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"imported": 0, "total": 0, "error": "JSON invalido en el bloque messages-data"}
    conn = engine._get_conn()
    imported = 0
    for m in messages:
        try:
            pid = m.get("sender", "")
            if pid and not pid.startswith("msg_"):
                conn.execute("INSERT OR IGNORE INTO participants (id, role, type, email, provider) VALUES (?,?,?,?,?)",
                             (pid, "importado", "bot", f"{pid}@importado.local", "cloud"))
            conn.execute(
                "INSERT OR IGNORE INTO messages (message_id, sender, recipient, body, timestamp, sequence, read, content_type, thread_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (m.get("message_id",""), m.get("sender",""), m.get("recipient",""), m.get("body",""),
                 m.get("timestamp",""), m.get("sequence",0), m.get("read",0), m.get("content_type","text/plain"), m.get("thread_id","general")))
            imported += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return {"imported": imported, "total": len(messages)}


@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    if lang not in TRANSLATIONS:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found")
    return {"lang": lang, "translations": TRANSLATIONS[lang]}


@app.get("/api/languages")
def get_languages():
    return {"languages": [
        {"code": l["code"], "name": l["name"], "flag": l["flag"],
         "available": l["code"] in TRANSLATIONS}
        for l in LANGUAGES
    ]}


@app.post("/orchestrate/stop")
def stop_orchestrate(request: Request, thread_id: str = Query("general")):
    # FASE 24: detener SOLO la conversacion del usuario (su hilo), no la global
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    thread = auth.scope_thread(user, thread_id)
    state = engine.read_state(thread)
    is_orchestrating = state.get("state") == "active"
    if is_orchestrating:
        engine.request_stop(thread)
        return {"success": True, "via": "flag"}
    else:
        engine.hard_reset(thread)
        return {"success": True, "via": "direct"}


def _is_question_to_moderator(text, mod_name=None):
    """Heuristica simple: contiene '?' y menciona al moderador. No usa NLP para evitar dependencias."""
    if "?" not in text:
        return False
    lower = text.lower()
    kws = ["miguel", "moderador", "@miguel", "humano"]
    if mod_name and mod_name.strip():
        kws.append(mod_name.strip().lower())
    return any(kw in lower for kw in kws)


@app.post("/orchestrate")
def orchestrate(req: MessageRequest, request: Request, rounds: int = Query(None), wait: int = Query(0)):
    """FASE 29: lanza el debate en SEGUNDO PLANO y responde al INSTANTE; el chat
    muestra los mensajes por su polling y consulta /api/orchestration-status. Con
    ?wait=1 corre síncrono y devuelve el resultado completo (lo usan los tests)."""
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    # Validaciones síncronas: el error llega al cliente al instante (no en background)
    ok, reason = auth.check_free_limits(engine, user)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)
    ok, reason = auth.check_unverified_limit(engine, user)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)
    # Modo SÍNCRONO (comportamiento clásico, espera el resultado): con ?wait=1 explícito
    # o cuando la peticion viene de TestClient (asi los tests unitarios siguen igual sin tocarlos).
    _is_testclient = request.client is None or request.client.host == "testclient"
    if wait or _is_testclient:
        _orch_enter()
        try:
            return _orchestrate_impl(req, user, rounds)
        finally:
            _orch_exit()
    thread = auth.scope_thread(user, req.thread_id)
    if _orch_is_running(thread):
        return {"started": False, "already_running": True, "thread": thread, "status": "running"}
    if _orch_count_running() >= ORCH_MAX_CONCURRENT:
        raise HTTPException(status_code=429, detail="Demasiados debates a la vez; prueba en un momento.")
    _orch_register(thread, rounds if rounds is not None else 0, 0)

    def _bg():
        _orch_enter()
        try:
            result = _orchestrate_impl(req, user, rounds)
            _orch_finish(thread, "stopped" if result.get("stopped") else "done", result)
        except Exception as e:
            traceback.print_exc()
            _orch_finish(thread, "error", {"error": str(e)[:200]})
        finally:
            _orch_exit()
    _threading.Thread(target=_bg, daemon=True, name=f"orch-{str(thread)[:40]}").start()
    return {"started": True, "thread": thread, "status": "running"}


@app.get("/api/orchestration-status")
def orchestration_status(request: Request, thread_id: str = ""):
    """FASE 29: estado del debate (running/done/stopped/error/stalled/none) + ronda X/Y.
    Lo consulta el chat en su polling para el cartel de espera y el 'terminado'."""
    user = getattr(request.state, "user", None) or dict(auth.DEV_USER)
    thread = auth.scope_thread(user, thread_id)
    t = _orch_get(thread)
    if not t:
        return {"status": "none", "thread": thread}
    out = {"status": t["status"], "round": t["round"], "total_rounds": t["total_rounds"],
           "bots": t["bots"], "thread": thread}
    if t["status"] != "running":
        s = t.get("summary") or {}
        out["budget_reached"] = s.get("budget_reached")
        out["rounds"] = s.get("rounds")
    return out


def _orchestrate_impl(req: MessageRequest, user: dict, rounds):
    """FASE 29: el bucle completo de orquestación. Corre en un HILO DE FONDO (lo
    lanza el handler /orchestrate y responde al instante). Devuelve el resumen o
    lanza; el handler traduce el resultado al estado del debate. `user` ya resuelto."""
    settings = engine.get_all_settings(SETTINGS_DEFAULTS)
    _global_bots = json.loads(settings["bots_config"])  # config global (el usuario puede sustituirla, pieza B)
    # FASE 20.2i: limites free tier + kill-switch de presupuesto global
    limits_ok, limit_reason = auth.check_free_limits(engine, user)
    if not limits_ok:
        raise HTTPException(status_code=429, detail=limit_reason)
    # FASE 20.4d: sin email verificado, 1 debate/dia
    verified_ok, verified_reason = auth.check_unverified_limit(engine, user)
    if not verified_ok:
        raise HTTPException(status_code=429, detail=verified_reason)
    # FASE 27: la conversacion usa la config del USUARIO (su preferencia), acotada al maximo de su plan.
    eff = effective_user_config(engine, user, settings)
    _rounds = rounds if rounds is not None else eff["rounds"]
    _rounds = max(0, min(_rounds, int(eff["limits"]["max_rounds"])))
    # FASE 27 (pieza B): las IAs son las que ELIGIÓ el usuario (de su catálogo, según su plan); si no, el global.
    BOTS_CONFIG = effective_user_bots(engine, user, _global_bots)
    if user.get("plan") == "free":
        # Free JAMAS usa OpenRouter (leccion 25): si el config lo lleva, cae al perfil economico
        BOTS_CONFIG = auth.free_safe_bots_config(BOTS_CONFIG, PROFILE_OPENCODE)
    assert_no_free_models(BOTS_CONFIG)  # defensa RGPD: bloquear modelos 'free' (sobre el config final)
    llm_timeout = int(settings["orchestrate_llm_timeout"])
    orch_max = int(settings.get("orchestrate_max_seconds", 220))  # FASE 26: presupuesto total (< nginx)
    bot_delay = float(settings["orchestrate_bot_delay"])
    context_limit_raw = int(settings["orchestrate_context_limit"])
    moderator_pause = int(settings["moderator_pause_seconds"])
    llm_temperature = eff["temperature"]   # FASE 27: creatividad elegida por el usuario
    llm_max_tokens = eff["max_tokens"]     # FASE 27: max tokens del usuario (acotado al plan)
    lang = (getattr(req, "lang", "es") or "es").strip().lower()[:2]
    # Si la UI esta en ingles, usar el system prompt en ingles para que las IAs respondan en ingles
    llm_system_prompt = settings["llm_system_prompt_en"] if lang == "en" else settings["llm_system_prompt"]
    # Opción A (config de usuario): instrucciones EXTRA por usuario -> se SUMAN al prompt base
    # del sistema (no lo reemplazan, así no se puede romper la orquestación). Vacío = nada.
    _extra = (eff.get("system_prompt_extra") or "").strip()
    if _extra:
        llm_system_prompt = llm_system_prompt + "\n\n" + _extra
    trace = []
    # FASE 25: instrumentación de tiempos. _tr() sella cada evento con t_ms (ms desde el inicio).
    # A=wall total, B=LLM (acumulado), C=espera de lock, D=delays fijos, E=overhead (resta).
    _t_start = _time.time()
    engine.lockwait_reset()
    llm_ms = 0
    delays_ms = 0
    def _tr(ev):
        ev["t_ms"] = int((_time.time() - _t_start) * 1000)
        list.append(trace, ev)
        return ev
    try:
        # FASE 31: el moderador es POR-USUARIO (su email), no el id global 'miguel'.
        mod_id = (user.get("email") or "moderador").strip().lower()
        state = engine.read_state()
        participants = state.get("participants", {})
        # FASE 31: asegurar SIEMPRE que el moderador (el usuario) esté registrado antes de darle el
        # turno. Antes solo se registraba si NO había NINGÚN participante; teniendo bots pero no el
        # moderador, acquire_turn(mod_id) violaba la clave foránea turns.current_turn->participants
        # (SQLite con foreign_keys=ON la caza igual que Postgres).
        if mod_id not in participants:
            engine.register_participant(mod_id, "moderador", "human", user.get("email") or mod_id, provider="local")
        if not participants:
            for bot_id, cfg in BOTS_CONFIG.items():
                engine.register_participant(bot_id, cfg["role"], "bot", cfg["email"], provider=cfg["provider"])
        state = engine.read_state()
        participants = state.get("participants", {})

        if user.get("plan") == "free":
            # Garantizar que los bots economicos existen y restringir la conversacion a ellos
            for bot_id, cfg in BOTS_CONFIG.items():
                if bot_id not in participants:
                    engine.register_participant(bot_id, cfg["role"], "bot", cfg["email"], provider=cfg["provider"])
            state = engine.read_state()
            participants = state.get("participants", {})
            bots = [pid for pid, info in participants.items()
                    if pid in BOTS_CONFIG and info.get("type") == "bot" and info.get("provider") != "openrouter"]
        else:
            # FASE 26: usar SOLO los bots del bots_config configurado (en su orden), NO todos los
            # participantes registrados. Si no, bots "fantasma" de un cambio de perfil anterior
            # (p. ej. qwen/deepseek del perfil OpenCode que nunca se borraron) contaminan la
            # conversacion y rompen la cadena de turnos -> caso PROD: minimax ignorado, solo
            # cyclaban qwen_plus<->deepseek_flash.
            for bot_id, cfg in BOTS_CONFIG.items():
                if bot_id not in participants:
                    engine.register_participant(bot_id, cfg["role"], "bot", cfg["email"], provider=cfg["provider"])
                elif participants[bot_id].get("status") == "inactive":
                    engine.set_participant_active(bot_id)  # FASE 27: el usuario las eligio -> manda su seleccion
            participants = engine.read_state().get("participants", {})
            # BOTS_CONFIG es el set elegido (global o del usuario): se usan TODOS, sin filtrar por
            # el estado 'inactive' global (que es un vestigio del perfil unico).
            bots = [pid for pid in BOTS_CONFIG
                    if pid in participants and participants[pid].get("type") == "bot"]
        context_limit = max(context_limit_raw, len(bots) + 1)  # +1 para que los mensajes del moderador sobrevivan una ronda completa
        _tr({"step": "init", "participants": len(participants), "bots": len(bots)})
        if not bots:
            raise HTTPException(status_code=400, detail="No hay bots registrados")

        thread = auth.scope_thread(user, req.thread_id)  # FASE 20.2e: aislamiento por usuario
        # El moderador se persiste como participante 'miguel', pero los bots deben dirigirse al
        # usuario por SU nombre real, no "Miguel" (bug reportado 2026-06-21).
        # FASE 29: leer el nombre FRESCO de la BD (el JWT puede llevar uno viejo si se acaba de cambiar)
        _uid = user.get("user_id")
        _fresh = auth.get_user(engine, _uid) if _uid else None
        _name = (_fresh.get("name") if _fresh else None) or user.get("name")
        mod_name = (_name or "").strip() or (user.get("email") or "").split("@")[0] or "Moderador"

        # FASE 24: la limpieza de arranque se acota a ESTE hilo (antes era global y
        # saboteaba otras conversaciones en curso). Nunca toca el turno/cola de otros hilos.
        turn_was = engine.get_current_turn(thread)
        queue_was = len(engine.get_queue(thread))
        engine.clear_queue(thread)
        if turn_was:
            engine.force_release_turn(turn_was, thread)
        _tr({"step": "cleanup", "turn_was": turn_was, "queue_was": queue_was, "cleared": True})

        ok = engine.acquire_turn(mod_id, thread)
        _tr({"step": "moderador", "action": "acquire", "ok": ok})
        engine.set_turn_timeout(60, thread)

        recipient = req.recipient_id
        # FASE 26: el destinatario del moderador debe estar entre los bots ACTIVOS de la
        # conversacion, no solo registrado. Si no (p. ej. config OpenRouter -> free cae a
        # qwen/minimax/deepseek, pero el front manda a qwen_plus que sigue registrado), la bola
        # va a un bot fuera de la conversacion -> todos hacen skip_empty -> 0 tokens.
        if recipient not in bots:
            recipient = bots[0] if bots else recipient
            _tr({"step": "moderador", "action": "redirect_recipient", "from": req.recipient_id, "to": recipient})

        try:
            engine.send_message(recipient, req.body, mod_id, thread_id=thread)
            _tr({"step": "moderador", "action": "send", "to": recipient, "ok": True})
        except Exception as e:
            _tr({"step": "moderador", "action": "send", "to": recipient, "ok": False, "error": str(e)[:80]})
            raise
        engine.release_turn(mod_id, thread)
        _tr({"step": "moderador", "action": "release", "ok": True})

        # FASE 40.1: dirección del servidor local configurable (LM Studio / Ollama), la BD manda.
        _local_url = (engine.get_setting("local_server_url") or _default_local_url()).strip()
        lm_local = LMStudioClient(base_url=_local_url)
        go_cloud = OpenCodeGoClient()
        or_client = OpenRouterClient()

        responses = []
        tok = {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0}  # tokens reales del proveedor
        budget_reached = False  # FASE 26: presupuesto de tiempo agotado -> cerrar limpio ANTES del 504 de nginx
        for rnd in range(_rounds):
            if budget_reached:
                break
            _orch_set_progress(thread, rnd + 1, _rounds, len(bots))  # FASE 29: ronda X de Y
            if engine.should_stop(thread):
                _tr({"step": "stop", "round": rnd + 1, "action": "stopped_by_user"})
                engine.hard_reset(thread)
                return {"success": False, "stopped": True, "trace": trace}
            for i, bot_id in enumerate(bots):
                if _time.time() - _t_start > orch_max:  # FASE 26: cerrar antes del timeout de nginx
                    budget_reached = True
                    _tr({"step": "budget", "round": rnd + 1, "i": i, "action": "time_budget_reached", "max_s": orch_max})
                    break
                if engine.should_stop(thread):
                    _tr({"step": "stop", "round": rnd + 1, "i": i, "bot": bot_id, "action": "stopped_by_user"})
                    engine.hard_reset(thread)
                    return {"success": False, "stopped": True, "trace": trace}
                info = participants.get(bot_id, {})
                provider = info.get("provider", "local")
                model = BOTS_CONFIG.get(bot_id, {}).get("model", "qwen2.5-coder-7b-instruct")
                next_recipient = mod_id if (i == len(bots) - 1 and rnd == _rounds - 1) else (bots[(i + 1) % len(bots)])

                ok = engine.acquire_turn(bot_id, thread)
                _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id, "action": "acquire", "ok": ok})
                if not ok:
                    continue

                msgs = engine.get_messages(bot_id, thread_id=thread)
                _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id, "action": "messages", "count": len(msgs)})
                if not msgs:
                    engine.release_turn(bot_id, thread)
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id, "action": "skip_empty"})
                    continue

                bot_system_prompt = llm_system_prompt.replace("{bot_id}", bot_id)
                bots_list = ", ".join(bots)
                if lang == "en":
                    bot_system_prompt += (
                        f"\n\n--- CONVERSATION CONTEXT ---\n"
                        f"Round {rnd + 1} of {_rounds}.\n"
                        f"{len(bots)} agents take part: {bots_list}.\n"
                        f"You are agent {i + 1} of {len(bots)}."
                    )
                else:
                    bot_system_prompt += (
                        f"\n\n--- CONTEXTO DE LA CONVERSACION ---\n"
                        f"Ronda {rnd + 1} de {_rounds}.\n"
                        f"Participais {len(bots)} agentes: {bots_list}.\n"
                        f"Tu eres el bot {i + 1} de {len(bots)}."
                    )
                client = lm_local if provider == "local" else (or_client if provider == "openrouter" else go_cloud)
                bot_max_tokens = BOTS_CONFIG.get(bot_id, {}).get("max_tokens", llm_max_tokens)

                t0 = _time.time()
                # Leer contexto justo antes del LLM, no al adquirir turno: captura mensajes humanos que llegaron durante el turno del bot anterior
                history = engine.get_thread_context(thread, limit=context_limit)
                chat_messages = [{"role": "system", "content": bot_system_prompt}]
                for m in history:
                    label = mod_name if m["sender"] == mod_id else m["sender"]
                    chat_messages.append({"role": "user", "content": f"[{label}]: {m['body']}"})
                # FASE 26: NO usar 'with ...executor' — su __exit__ ESPERA al hilo aunque
                # future.result haya saltado por timeout, lo que dejaba un overrun de ~1 llamada
                # (A=273 con presupuesto 220). Con shutdown(wait=False) el presupuesto es TOPE DURO:
                # la llamada en vuelo se abandona (su HTTP muere solo por el timeout del cliente).
                _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                # FASE: razonamiento bajo/none por bot (solo OpenCode/cloud lo acepta; p. ej. Kimi)
                _re = BOTS_CONFIG.get(bot_id, {}).get("reasoning_effort")
                _kw = {"reasoning_effort": _re} if (_re and provider == "cloud") else {}
                future = _executor.submit(
                    client.chat_completion, chat_messages,
                    model=model, temperature=llm_temperature, max_tokens=bot_max_tokens, **_kw
                )
                _call_to = max(5, min(llm_timeout, int(orch_max - (_time.time() - _t_start))))
                try:
                    result = future.result(timeout=_call_to)
                    _executor.shutdown(wait=False)
                    elapsed = int((_time.time() - t0) * 1000)
                    llm_ms += elapsed  # FASE 25: métrica B (tiempo LLM acumulado)
                    _llm_stat("ok")    # FASE 28.5: salud de LLM
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "llm", "model": model, "ms": elapsed, "ok": True})
                except (concurrent.futures.TimeoutError, Exception) as e:
                    _executor.shutdown(wait=False)  # no esperar al hilo en vuelo (tope duro)
                    elapsed = int((_time.time() - t0) * 1000)
                    llm_ms += elapsed  # FASE 25: métrica B (incluye llamadas que fallan/expiran)
                    # FASE 28.5: clasificar el fallo (timeout / 429 / error)
                    if isinstance(e, concurrent.futures.TimeoutError):
                        _llm_stat("timeout")
                    elif "429" in str(e) or "rate" in str(e).lower():
                        _llm_stat("rate_limited")
                    else:
                        _llm_stat("error")
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "llm", "model": model, "ms": elapsed, "ok": False, "error": str(e)[:80]})
                    ok = engine.force_release_turn(bot_id, thread)
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "release", "ok": ok})
                    # FASE 40.1 (T4): aviso CLARO si el fallo es que el servidor local está apagado.
                    _es_local_caido = provider == "local" and any(
                        s in str(e) for s in ("CONNECTION_FAILED", "Connection", "refused", "Max retries", "ConnectionError"))
                    if _es_local_caido:
                        response_text = (
                            f"[Can't reach your local model server at {_local_url}. Is LM Studio / Ollama running? Skipping {bot_id}.]"
                            if lang == "en" else
                            f"[No encuentro tu servidor de modelos local en {_local_url}. ¿Está encendido LM Studio / Ollama? Salto {bot_id} y sigo.]")
                    else:
                        response_text = f"[{bot_id} no respondio a tiempo, continuamos]"
                    try:
                        engine.send_message(next_recipient, response_text, bot_id, thread_id=thread)
                    except Exception:
                        pass
                    responses.append({"bot": bot_id, "provider": provider, "to": next_recipient, "round": rnd + 1,
                                      "response": response_text})
                    continue

                _u = result.get("usage", {}) or {}
                _cd = _u.get("completion_tokens_details", {}) or {}
                tok["prompt"] += int(_u.get("prompt_tokens", 0) or 0)
                tok["completion"] += int(_u.get("completion_tokens", 0) or 0)
                tok["reasoning"] += int(_cd.get("reasoning_tokens", 0) or 0)
                tok["total"] += int(_u.get("total_tokens", 0) or 0)
                response_text = (result.get("content") or "").strip()
                if not response_text:
                    reasoning = result.get("reasoning_content") or ""
                    lines = [l.strip() for l in reasoning.split("\n") if l.strip() and len(l.strip()) > 20]
                    response_text = lines[-1] if lines else reasoning[-200:].strip()
                if not response_text:
                    response_text = f"[{bot_id} no pudo responder en esta ronda, continuamos]"

                tag_close = f"(/{bot_id})"
                tag_open = f"({bot_id})"
                stripped = response_text.strip()
                aceptable = stripped.endswith(tag_close) or len(stripped) > 200
                if provider != "openrouter":
                    aceptable = True
                if not aceptable and len(stripped) < 50:
                    aceptable = stripped[-1] in ".!?\")"
                if aceptable:
                    if response_text.startswith(tag_open):
                        response_text = response_text[len(tag_open):]
                    if response_text.endswith(tag_close):
                        response_text = response_text[:-len(tag_close)]
                    response_text = response_text.strip()
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "response", "len": len(response_text), "ok": True})
                else:
                    response_text = f"[{bot_id} no pudo responder en esta ronda, continuamos]"
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "response", "len": len(response_text), "ok": False, "truncated": True})

                try:
                    if engine.get_current_turn(thread) != bot_id:
                        engine.acquire_turn(bot_id, thread)
                    engine.send_message(next_recipient, response_text, bot_id, thread_id=thread)
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "send", "to": next_recipient, "ok": True})
                    if _is_question_to_moderator(response_text, mod_name) and moderator_pause > 0:
                        # time.sleep() no bloquea /message/send porque FastAPI ejecuta cada request en su propio hilo del thread pool
                        _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                      "action": "pause", "seconds": moderator_pause})
                        _time.sleep(moderator_pause)
                        delays_ms += int(moderator_pause * 1000)  # FASE 25: métrica D
                except Exception as e:
                    _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                                  "action": "send", "to": next_recipient, "ok": False, "error": str(e)[:80]})

                responses.append({"bot": bot_id, "provider": provider, "to": next_recipient, "round": rnd + 1,
                                  "response": response_text[:150]})
                ok = engine.force_release_turn(bot_id, thread)
                _tr({"step": "bot", "round": rnd + 1, "i": i, "bot": bot_id,
                              "action": "release", "ok": ok})
                _time.sleep(bot_delay)
                delays_ms += int(bot_delay * 1000)  # FASE 25: métrica D

        auth.record_debate(engine, user, _rounds, len(bots), tokens=tok)
        # FASE 25: desglose de tiempos A-E (ver plans/phase_25). A=B+C+D+E (aprox).
        _A = int((_time.time() - _t_start) * 1000)
        _C = int(engine.lockwait_ms())
        _E = max(0, _A - llm_ms - _C - delays_ms)
        tiempos = {"A_wall_ms": _A, "B_llm_ms": llm_ms, "C_lock_ms": _C,
                   "D_delays_ms": delays_ms, "E_overhead_ms": _E}
        # FASE 26: persistir el desglose en el SERVIDOR (sobrevive aunque el cliente reciba 504)
        try:
            auth.record_orch_time(engine, user.get("user_id"), thread, _rounds, len(bots),
                                  tiempos, tok.get("total", 0))
        except Exception:
            traceback.print_exc()
        return {"success": True, "trace": trace, "responses": responses, "rounds": _rounds,
                "thread": thread, "tokens": tok, "tiempos": tiempos, "budget_reached": budget_reached}
    except Exception as e:
        traceback.print_exc()
        _tr({"step": "error", "detail": str(e)[:200]})
        raise HTTPException(status_code=500, detail=str(e))
