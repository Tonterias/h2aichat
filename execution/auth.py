#!/usr/bin/env python3
"""
HumanIA - Autenticacion de usuarios (FASE 20.2)

Usuarios, sesiones JWT, limites del free tier y presupuesto global.
Opera sobre la misma BD SQLite del engine (memory/humania.db).
"""
import os
import re
import json
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7

# Limites del free tier (decision PO 2026-06-11, ver plans/phase_20/PHASE_20_2.md 20.2i)
FREE_DEBATES_PER_MONTH = 10  # subido de 3 a 10 para la fase de pruebas (PO 2026-06-13)
FREE_MAX_ROUNDS = 3
FREE_BUDGET_EUR_DEFAULT = "30"
# FASE 20.4d: sin email verificado, 1 debate/dia
UNVERIFIED_DEBATES_PER_DAY = 1
VERIFICATION_EXPIRY_HOURS = 24
RESET_EXPIRY_HOURS = 1
# FASE 20.8b: version vigente de terminos y politica de privacidad
# 2026-06-13: añadida limitacion de responsabilidad y refuerzo del disclaimer de IA
TERMS_VERSION = "2026-06-13"
# Estimacion conservadora por debate economico (OpenCode Go): rondas x bots x 0.005 EUR
EST_COST_PER_BOT_ROUND_EUR = 0.005

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Usuario implicito en modo dev (sin token): comportamiento identico al sistema pre-auth
DEV_USER = {"user_id": 0, "email": "dev@local", "name": "dev", "plan": "premium"}


def _jwt_secret() -> str:
    secret = os.environ.get("HUMANIA_JWT_SECRET", "humania-dev-jwt-secret")
    if os.environ.get("HUMANIA_ENV", "dev") == "production" and secret == "humania-dev-jwt-secret":
        raise RuntimeError("HUMANIA_JWT_SECRET must be set in production. "
                           "Generate one: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    return secret


def auth_enforced() -> bool:
    """La proteccion JWT se exige en produccion o si HUMANIA_AUTH=on (tests)."""
    if os.environ.get("HUMANIA_AUTH", "").lower() == "on":
        return True
    return os.environ.get("HUMANIA_ENV", "dev") == "production"


def init_auth_tables(engine):
    conn = engine._get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            plan TEXT DEFAULT 'free',
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            debates INTEGER DEFAULT 0,
            est_cost_eur REAL DEFAULT 0,
            PRIMARY KEY (user_id, month)
        );
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti TEXT PRIMARY KEY,
            revoked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS email_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            kind TEXT NOT NULL,
            user_id INTEGER,
            conversation_id TEXT,
            vote TEXT,
            comment TEXT,
            contact_type TEXT,
            contact_email TEXT
        );
        CREATE TABLE IF NOT EXISTS trial_log (
            email_hash TEXT NOT NULL,
            month TEXT NOT NULL,
            debates INTEGER DEFAULT 0,
            PRIMARY KEY (email_hash, month)
        );
        CREATE TABLE IF NOT EXISTS conversation_share (
            thread_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            consented_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS shared_conversation (
            token TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            revoked INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS startups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT DEFAULT (datetime('now')),
            env TEXT,
            version TEXT
        );
        CREATE TABLE IF NOT EXISTS orch_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            user_id INTEGER, thread_id TEXT, rounds INTEGER, bots INTEGER,
            wall_ms INTEGER, llm_ms INTEGER, lock_ms INTEGER,
            delays_ms INTEGER, overhead_ms INTEGER, total_tokens INTEGER
        );
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id INTEGER PRIMARY KEY,
            prefs TEXT
        );
        CREATE TABLE IF NOT EXISTS system_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            ram_pct REAL, swap_pct REAL, cpu_pct REAL,
            disk_used_pct REAL, disk_free_pct REAL, load1 REAL,
            inflight_orch INTEGER, inflight_requests INTEGER,
            capacity_pct REAL, worst TEXT
        );
    """)
    # Migraciones idempotentes (FASES 20.4 y 20.8)
    for ddl in ("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0",
                "ALTER TABLE usage ADD COLUMN last_debate_date TEXT",
                "ALTER TABLE usage ADD COLUMN debates_today INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN accepted_terms_at TEXT",
                "ALTER TABLE users ADD COLUMN terms_version TEXT",
                "ALTER TABLE users ADD COLUMN confirmed_adult_at TEXT",
                "ALTER TABLE usage ADD COLUMN prompt_tokens INTEGER DEFAULT 0",
                "ALTER TABLE usage ADD COLUMN completion_tokens INTEGER DEFAULT 0",
                "ALTER TABLE usage ADD COLUMN reasoning_tokens INTEGER DEFAULT 0",
                "ALTER TABLE usage ADD COLUMN total_tokens INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN sessions_invalid_before TEXT"):
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_feedback(engine, kind, user_id=None, conversation_id=None, vote=None,
                  comment=None, contact_type=None, contact_email=None):
    """Guarda una entrada de feedback (conversation / contact / public). Devuelve su id."""
    conn = engine._get_conn()
    cur = conn.execute(
        "INSERT INTO feedback (created_at, kind, user_id, conversation_id, vote, comment, contact_type, contact_email) "
        "VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
        (kind, user_id, conversation_id, vote, comment, contact_type, contact_email))
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def list_conversation_comments(engine, limit: int = 100):
    """Comentarios de TEXTO que la gente deja al terminar una conversacion (kind='conversation'
    con comment no vacio). Para el panel /admin, solo lectura. Sin paginacion aun (Fase 37.x):
    devuelve los ultimos `limit`, mas reciente primero. Los pulgares sueltos sin texto NO entran
    (ya se cuentan en la tarjeta de feedback)."""
    conn = engine._get_conn()
    try:
        rows = conn.execute("""
            SELECT f.created_at, f.conversation_id, f.vote, f.comment,
                   u.name AS user_name, u.email AS user_email,
                   (SELECT sc.token FROM shared_conversation sc
                     WHERE sc.thread_id = f.conversation_id AND sc.revoked=0
                     ORDER BY sc.updated_at DESC LIMIT 1) AS share_token
            FROM feedback f
            LEFT JOIN users u ON u.id = f.user_id
            WHERE f.kind='conversation' AND f.comment IS NOT NULL AND TRIM(f.comment) <> ''
            ORDER BY f.id DESC
            LIMIT ?
        """, (int(limit),)).fetchall()
    except Exception:
        rows = []
    conn.close()
    out = []
    for r in rows:
        usuario = (r["user_name"] or r["user_email"] or "").strip() or None
        token = r["share_token"]
        out.append({
            "fecha": r["created_at"],
            "conversacion": r["conversation_id"],
            "usuario": usuario,        # None -> el front muestra "anonimo"
            "comentario": r["comment"],
            "pulgar": r["vote"],       # 'up' | 'down' | None
            "url_publica": ("/c/" + token) if token else None,  # enlace si esta publicada (opcion A)
        })
    return {"comments": out}


def admin_stats(engine):
    """Métricas del panel /admin (todo desde la BD). Robusto: cada consulta tolera fallos."""
    conn = engine._get_conn()
    def one(sql):
        try:
            r = conn.execute(sql).fetchone()
            return r[0] if r and r[0] is not None else 0
        except Exception:
            return 0
    stats = {
        "users_total": one("SELECT COUNT(*) FROM users"),
        "users_today": one("SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')"),
        "users_7d": one("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')"),
        "users_verified": one("SELECT COUNT(*) FROM users WHERE email_verified=1"),
        "users_free": one("SELECT COUNT(*) FROM users WHERE plan='free'"),
        "users_pro": one("SELECT COUNT(*) FROM users WHERE plan!='free'"),
        "orq_total": one("SELECT COALESCE(SUM(debates),0) FROM usage"),
        "orq_today": one("SELECT COALESCE(SUM(debates_today),0) FROM usage WHERE last_debate_date=date('now')"),
        "tokens_total": one("SELECT COALESCE(SUM(total_tokens),0) FROM usage"),
        "tokens_reasoning": one("SELECT COALESCE(SUM(reasoning_tokens),0) FROM usage"),
        "tokens_prompt": one("SELECT COALESCE(SUM(prompt_tokens),0) FROM usage"),
        "tokens_completion": one("SELECT COALESCE(SUM(completion_tokens),0) FROM usage"),
        "conversaciones": one("SELECT COUNT(DISTINCT thread_id) FROM messages WHERE thread_id LIKE 'user_%'"),
        "mensajes": one("SELECT COUNT(*) FROM messages"),
        "fb_up": one("SELECT COUNT(*) FROM feedback WHERE vote='up'"),
        "fb_down": one("SELECT COUNT(*) FROM feedback WHERE vote='down'"),
        "fb_neutral": one("SELECT COUNT(*) FROM feedback WHERE vote='neutral'"),
        "fb_contacts": one("SELECT COUNT(*) FROM feedback WHERE kind='contact'"),
        "last_startup": one("SELECT started_at FROM startups ORDER BY id DESC LIMIT 1"),
        "startups_24h": one("SELECT COUNT(*) FROM startups WHERE started_at >= datetime('now','-1 day')"),
    }
    recientes = []
    try:
        for row in conn.execute("SELECT email, created_at, email_verified FROM users ORDER BY id DESC LIMIT 10"):
            recientes.append({"email": row[0], "created_at": row[1], "verified": bool(row[2])})
    except Exception:
        pass
    conn.close()
    stats["recientes"] = recientes
    return stats


def set_share_consent(engine, user_id, thread_id, consent):
    """Opt-in de publicación por conversación (consentimiento explícito y revocable). Default: privado."""
    conn = engine._get_conn()
    if consent:
        conn.execute("INSERT OR REPLACE INTO conversation_share (thread_id, user_id, consented_at) VALUES (?,?,datetime('now'))",
                     (thread_id, user_id))
    else:
        conn.execute("DELETE FROM conversation_share WHERE thread_id=? AND user_id=?", (thread_id, user_id))
    conn.commit()
    conn.close()


def get_share_consent(engine, thread_id) -> bool:
    conn = engine._get_conn()
    r = conn.execute("SELECT 1 FROM conversation_share WHERE thread_id=?", (thread_id,)).fetchone()
    conn.close()
    return bool(r)


def list_shared_threads(engine, user_id):
    conn = engine._get_conn()
    try:
        rows = conn.execute("SELECT thread_id FROM conversation_share WHERE user_id=?", (user_id,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ── Enlace público por conversación (Fase 34) ────────────────────────────────
# DISTINTO de conversation_share (galeria de la home): esto es un enlace publico,
# inadivinable y revocable, con un SNAPSHOT inmutable de la conversacion en el
# momento de compartir. 'Actualizar enlace' re-congela el snapshot sobre el MISMO
# token; revocar lo apaga y un nuevo compartir genera un token nuevo.

def _new_share_token():
    return secrets.token_urlsafe(8)


def create_or_update_share_link(engine, user_id, thread_id, snapshot):
    """Crea el enlace publico de una conversacion o, si ya hay uno activo, re-congela su
    snapshot SOBRE EL MISMO token ('Actualizar enlace'). Devuelve el token."""
    conn = engine._get_conn()
    try:
        row = conn.execute(
            "SELECT token FROM shared_conversation WHERE user_id=? AND thread_id=? AND revoked=0",
            (user_id, thread_id)).fetchone()
        if row:
            token = row[0]
            conn.execute("UPDATE shared_conversation SET snapshot=?, updated_at=datetime('now') WHERE token=?",
                         (snapshot, token))
        else:
            token = _new_share_token()
            conn.execute(
                "INSERT INTO shared_conversation (token, thread_id, user_id, snapshot) VALUES (?,?,?,?)",
                (token, thread_id, user_id, snapshot))
        conn.commit()
        return token
    finally:
        conn.close()


def get_share_link(engine, token):
    """Devuelve el enlace (dict con snapshot) por su token si existe y NO esta revocado;
    si no, None. Lo usa la pagina publica /c/<token>."""
    conn = engine._get_conn()
    try:
        r = conn.execute(
            "SELECT token, thread_id, user_id, snapshot, created_at, updated_at "
            "FROM shared_conversation WHERE token=? AND revoked=0", (token,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_share_link_for_thread(engine, user_id, thread_id):
    """Estado del enlace de una conversacion para la UI (token activo o None)."""
    conn = engine._get_conn()
    try:
        r = conn.execute(
            "SELECT token, updated_at FROM shared_conversation WHERE user_id=? AND thread_id=? AND revoked=0",
            (user_id, thread_id)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def revoke_share_link(engine, user_id, thread_id):
    """Apaga el enlace de una conversacion. La URL deja de mostrarla. Reactivar dara uno nuevo."""
    conn = engine._get_conn()
    try:
        conn.execute("UPDATE shared_conversation SET revoked=1 WHERE user_id=? AND thread_id=?",
                     (user_id, thread_id))
        conn.commit()
    finally:
        conn.close()


# ── Passwords ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────

def create_token(user_id: int, email: str, name: str, plan: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name or "",
        "plan": plan,
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRY_DAYS),
        "jti": f"{user_id}_{int(now.timestamp() * 1000)}",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(engine, token: str):
    """Devuelve el payload del token o None si es invalido, expirado o revocado."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    conn = engine._get_conn()
    revoked = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (payload.get("jti", ""),)).fetchone()
    # FASE 23: sesiones invalidadas en bloque (baneo/borrado de cuenta). Si el usuario tiene
    # un sello sessions_invalid_before posterior al iat del token, el token deja de valer.
    inv = None
    sub = payload.get("sub")
    if sub is not None:
        r = conn.execute("SELECT sessions_invalid_before FROM users WHERE id=?", (sub,)).fetchone()
        inv = r[0] if r else None
    conn.close()
    if revoked:
        return None
    if inv:
        try:
            if float(payload.get("iat", 0)) < datetime.fromisoformat(inv).timestamp():
                return None
        except Exception:
            pass
    return payload


def revoke_token(engine, token: str) -> bool:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return False
    conn = engine._get_conn()
    conn.execute("INSERT OR IGNORE INTO revoked_tokens (jti, revoked_at) VALUES (?, ?)",
                 (payload.get("jti", ""), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return True


# ── Registro y login ─────────────────────────────────────────────────────────

def validate_registration(email: str, password: str, name: str):
    """Devuelve un mensaje de error o None si todo es valido."""
    if not email or not EMAIL_RE.match(email):
        return "Email no valido"
    if not password or len(password) < 8:
        return "La contrasena debe tener al menos 8 caracteres"
    if name and len(name) > 100:
        return "El nombre no puede superar 100 caracteres"
    return None


def register_user(engine, email: str, password: str, name: str = "", accept_terms: bool = False,
                  confirm_adult: bool = False):
    """Crea el usuario y devuelve (token, user_dict). Lanza ValueError si falla la validacion."""
    if not accept_terms:
        raise ValueError("Debes aceptar los terminos y la politica de privacidad")
    if not confirm_adult:
        raise ValueError("Debes confirmar que eres mayor de 18 anios")
    error = validate_registration(email, password, name)
    if error:
        raise ValueError(error)
    email = email.strip().lower()
    conn = engine._get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        conn.close()
        raise ValueError("Ya existe una cuenta con ese email")
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, name, plan, created_at, last_login, accepted_terms_at, terms_version, confirmed_adult_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (email, hash_password(password), (name or "").strip(), "free", now, now, now, TERMS_VERSION, now))
    user_id = cur.lastrowid
    # Anti-abuso: si este email ya consumio free este mes (borrarse + re-registrarse),
    # restaurar el consumo para que NO se reinicien los creditos gratuitos.
    _tl = conn.execute("SELECT debates FROM trial_log WHERE email_hash=? AND month=?",
                       (_email_hash(email), _current_month())).fetchone()
    if _tl and _tl["debates"]:
        conn.execute("INSERT OR REPLACE INTO usage (user_id, month, debates, est_cost_eur, debates_today) VALUES (?,?,?,0,0)",
                     (user_id, _current_month(), _tl["debates"]))
    conn.commit()
    conn.close()
    user = {"user_id": user_id, "email": email, "name": (name or "").strip(), "plan": "free"}
    return create_token(user_id, email, user["name"], "free"), user


def login_user(engine, email: str, password: str):
    """Devuelve (token, user_dict) o None si las credenciales no son validas."""
    email = (email or "").strip().lower()
    conn = engine._get_conn()
    row = conn.execute("SELECT * FROM users WHERE email=? AND status='active'", (email,)).fetchone()
    if not row or not verify_password(password or "", row["password_hash"]):
        conn.close()
        return None
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (now, row["id"]))
    conn.commit()
    conn.close()
    user = {"user_id": row["id"], "email": row["email"], "name": row["name"] or "", "plan": row["plan"]}
    return create_token(row["id"], row["email"], user["name"], row["plan"]), user


def get_user(engine, user_id: int):
    conn = engine._get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row["id"], "email": row["email"], "name": row["name"] or "",
            "plan": row["plan"], "status": row["status"], "created_at": row["created_at"],
            "email_verified": int(row["email_verified"] or 0)}


# ── Threads por usuario (20.2e) ──────────────────────────────────────────────

def user_thread_prefix(user_id: int) -> str:
    return f"user_{user_id}_"


def scope_thread(user: dict, thread_id: str) -> str:
    """Prefija el thread con el id del usuario. El usuario dev (id 0) no se aisla."""
    thread_id = thread_id or "general"
    if not user or user.get("user_id", 0) == 0:
        return thread_id
    prefix = user_thread_prefix(user["user_id"])
    return thread_id if thread_id.startswith(prefix) else prefix + thread_id


def visible_to_user(user: dict, thread_id: str) -> bool:
    """El usuario dev ve todo; un usuario real solo sus threads."""
    if not user or user.get("user_id", 0) == 0:
        return True
    return (thread_id or "general").startswith(user_thread_prefix(user["user_id"]))


# ── Limites free tier y presupuesto global (20.2i) ──────────────────────────

def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _email_hash(email: str) -> str:
    """Hash del email para el registro anti-abuso (pseudonimizado, sobrevive al borrado)."""
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def get_usage(engine, user_id: int):
    conn = engine._get_conn()
    row = conn.execute("SELECT * FROM usage WHERE user_id=? AND month=?",
                       (user_id, _current_month())).fetchone()
    conn.close()
    if not row:
        return {"debates": 0, "est_cost_eur": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                "reasoning_tokens": 0, "total_tokens": 0}
    keys = row.keys()
    return {"debates": row["debates"], "est_cost_eur": row["est_cost_eur"],
            "prompt_tokens": row["prompt_tokens"] if "prompt_tokens" in keys else 0,
            "completion_tokens": row["completion_tokens"] if "completion_tokens" in keys else 0,
            "reasoning_tokens": row["reasoning_tokens"] if "reasoning_tokens" in keys else 0,
            "total_tokens": row["total_tokens"] if "total_tokens" in keys else 0}


def estimate_debate_cost(rounds: int, n_bots: int) -> float:
    return round(rounds * n_bots * EST_COST_PER_BOT_ROUND_EUR, 4)


def _free_budget_state(engine):
    """Devuelve (gastado, presupuesto) del mes en curso, reseteando si cambio el mes."""
    month = _current_month()
    if engine.get_setting("free_spent_month") != month:
        engine.set_setting("free_spent_month", month)
        engine.set_setting("free_spent_eur", "0")
    spent = float(engine.get_setting("free_spent_eur", "0"))
    budget = float(engine.get_setting("free_budget_eur", FREE_BUDGET_EUR_DEFAULT))
    return spent, budget


def check_free_limits(engine, user: dict):
    """Para usuarios free: devuelve (ok, motivo). Premium y dev pasan siempre."""
    if not user or user.get("plan") != "free":
        return True, ""
    spent, budget = _free_budget_state(engine)
    if spent >= budget:
        return False, "Demanda desbordada este mes — vuelve el dia 1 o pasate a Pro"
    usage = get_usage(engine, user["user_id"])
    if usage["debates"] >= FREE_DEBATES_PER_MONTH:
        return False, f"Has alcanzado tus {FREE_DEBATES_PER_MONTH} conversaciones gratuitas de este mes — pasate a Pro"
    return True, ""


def record_debate(engine, user: dict, rounds: int, n_bots: int, tokens: dict = None):
    """Registra una orquestacion, su coste estimado y los tokens reales consumidos.
    El usuario dev (id 0) no consume. `tokens` = {prompt, completion, reasoning, total}."""
    if not user or user.get("user_id", 0) == 0:
        return
    cost = estimate_debate_cost(rounds, n_bots)
    t = tokens or {}
    pt, ct, rt, tt = (int(t.get("prompt", 0)), int(t.get("completion", 0)),
                      int(t.get("reasoning", 0)), int(t.get("total", 0)))
    month = _current_month()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = engine._get_conn()
    conn.execute("""INSERT INTO usage (user_id, month, debates, est_cost_eur, last_debate_date, debates_today,
                                       prompt_tokens, completion_tokens, reasoning_tokens, total_tokens)
                    VALUES (?,?,1,?,?,1,?,?,?,?)
                    ON CONFLICT(user_id, month) DO UPDATE SET
                    debates = debates + 1, est_cost_eur = est_cost_eur + ?,
                    debates_today = CASE WHEN last_debate_date = ? THEN debates_today + 1 ELSE 1 END,
                    last_debate_date = ?,
                    prompt_tokens = prompt_tokens + ?, completion_tokens = completion_tokens + ?,
                    reasoning_tokens = reasoning_tokens + ?, total_tokens = total_tokens + ?""",
                 (user["user_id"], month, cost, today, pt, ct, rt, tt,
                  cost, today, today, pt, ct, rt, tt))
    conn.commit()
    conn.close()
    if user.get("plan") == "free":
        spent, _ = _free_budget_state(engine)
        engine.set_setting("free_spent_eur", str(round(spent + cost, 4)))


def free_safe_bots_config(bots_config: dict, fallback: dict) -> dict:
    """Para usuarios free: jamas OpenRouter (leccion 25). Si el config global lo usa, cae al fallback economico."""
    if any(cfg.get("provider") == "openrouter" for cfg in bots_config.values()):
        return dict(fallback)
    return bots_config


# ── Tokens de un solo uso: verificacion de email (20.4) y reset de password (20.3) ──

def _create_one_time_token(engine, table: str, user_id: int, expiry_hours: int) -> str:
    """Genera un token nuevo e invalida los anteriores del usuario en esa tabla."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=expiry_hours)).isoformat()
    conn = engine._get_conn()
    conn.execute(f"UPDATE {table} SET used=1 WHERE user_id=?", (user_id,))
    conn.execute(f"INSERT INTO {table} (user_id, token, expires_at) VALUES (?,?,?)",
                 (user_id, token, expires))
    conn.commit()
    conn.close()
    return token


def _consume_one_time_token(engine, table: str, token: str):
    """Valida y consume un token. Devuelve user_id o None si es invalido/expirado/usado."""
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    conn = engine._get_conn()
    row = conn.execute(f"SELECT * FROM {table} WHERE token=? AND used=0 AND expires_at > ?",
                       (token, now)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute(f"UPDATE {table} SET used=1 WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    return row["user_id"]


def create_verification(engine, user_id: int) -> str:
    return _create_one_time_token(engine, "email_verifications", user_id, VERIFICATION_EXPIRY_HOURS)


def verify_email(engine, token: str) -> bool:
    user_id = _consume_one_time_token(engine, "email_verifications", token)
    if user_id is None:
        return False
    conn = engine._get_conn()
    conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def create_password_reset(engine, email: str):
    """Devuelve (token, user) o None si el email no existe. La API nunca revela cual fue."""
    conn = engine._get_conn()
    row = conn.execute("SELECT id, email FROM users WHERE email=? AND status='active'",
                       ((email or "").strip().lower(),)).fetchone()
    conn.close()
    if not row:
        return None
    token = _create_one_time_token(engine, "password_resets", row["id"], RESET_EXPIRY_HOURS)
    return token, {"user_id": row["id"], "email": row["email"]}


def reset_password(engine, token: str, new_password: str) -> bool:
    if not new_password or len(new_password) < 8:
        raise ValueError("La contrasena debe tener al menos 8 caracteres")
    user_id = _consume_one_time_token(engine, "password_resets", token)
    if user_id is None:
        return False
    conn = engine._get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
    conn.commit()
    conn.close()
    return True


# ── Limite diario para emails no verificados (20.4d) ────────────────────────

# ── GDPR (FASE 20.8): acceso, portabilidad, supresion y minimizacion ─────────

def export_user_data(engine, user_id: int) -> dict:
    """Art. 15/20 RGPD: todos los datos del usuario en JSON portable."""
    conn = engine._get_conn()
    user_row = conn.execute(
        "SELECT id, email, name, plan, status, created_at, last_login, email_verified, accepted_terms_at, terms_version "
        "FROM users WHERE id=?", (user_id,)).fetchone()
    usage_rows = conn.execute("SELECT month, debates, est_cost_eur FROM usage WHERE user_id=?", (user_id,)).fetchall()
    msg_rows = conn.execute(
        "SELECT message_id, sender, recipient, body, timestamp, thread_id FROM messages WHERE thread_id LIKE ? ORDER BY timestamp",
        (user_thread_prefix(user_id) + "%",)).fetchall()
    conn.close()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": dict(user_row) if user_row else None,
        "usage": [dict(r) for r in usage_rows],
        "messages": [dict(r) for r in msg_rows],
    }


def verify_user_password(engine, user_id: int, password: str) -> bool:
    conn = engine._get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row) and verify_password(password or "", row["password_hash"])


def delete_account(engine, user_id: int) -> bool:
    """Art. 17 RGPD: supresion completa del usuario y todos sus datos."""
    conn = engine._get_conn()
    if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        conn.close()
        return False
    # Anti-abuso (interes legitimo): conservar el consumo free por HASH del email (sobrevive
    # al borrado) para que re-registrarse no reinicie los creditos del mes. Sin PII, solo el hash.
    _u = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    if _u:
        _eh = _email_hash(_u["email"])
        for _r in conn.execute("SELECT month, debates FROM usage WHERE user_id=? AND debates>0", (user_id,)).fetchall():
            conn.execute("INSERT INTO trial_log (email_hash, month, debates) VALUES (?,?,?) "
                         "ON CONFLICT(email_hash, month) DO UPDATE SET debates=MAX(debates, excluded.debates)",
                         (_eh, _r["month"], _r["debates"]))
    conn.execute("DELETE FROM messages WHERE thread_id LIKE ?", (user_thread_prefix(user_id) + "%",))
    conn.execute("DELETE FROM usage WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM conversation_share WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM shared_conversation WHERE user_id=?", (user_id,))  # Fase 34: mata los enlaces publicos
    conn.execute("DELETE FROM email_verifications WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def cleanup_expired(engine):
    """Minimizacion (20.8e): purga tokens caducados hace >30 dias y revocaciones cuyo JWT ya expiro."""
    now = datetime.now(timezone.utc)
    cutoff_tokens = (now - timedelta(days=30)).isoformat()
    cutoff_revoked = (now - timedelta(days=JWT_EXPIRY_DAYS)).isoformat()
    conn = engine._get_conn()
    conn.execute("DELETE FROM email_verifications WHERE expires_at < ?", (cutoff_tokens,))
    conn.execute("DELETE FROM password_resets WHERE expires_at < ?", (cutoff_tokens,))
    conn.execute("DELETE FROM revoked_tokens WHERE revoked_at < ?", (cutoff_revoked,))
    # Anti-abuso: el registro de consumo free por hash se conserva 12 meses (decision PO) y
    # luego se purga (minimizacion RGPD: el hash no se guarda mas de lo necesario).
    conn.execute("DELETE FROM trial_log WHERE month < strftime('%Y-%m','now','-12 months')")
    conn.commit()
    conn.close()


# ── Limite diario para emails no verificados (20.4d) ────────────────────────

def check_unverified_limit(engine, user: dict):
    """Sin email verificado: 1 debate/dia. Dev (id 0) y verificados pasan."""
    if not user or user.get("user_id", 0) == 0:
        return True, ""
    fresh = get_user(engine, user["user_id"])
    if fresh is None or fresh.get("email_verified"):
        return True, ""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = engine._get_conn()
    row = conn.execute("SELECT debates_today, last_debate_date FROM usage WHERE user_id=? AND month=?",
                       (user["user_id"], _current_month())).fetchone()
    conn.close()
    if row and row["last_debate_date"] == today and (row["debates_today"] or 0) >= UNVERIFIED_DEBATES_PER_DAY:
        return False, "Verifica tu email para seguir conversando hoy (revisa tu bandeja de entrada)"
    return True, ""


# ── Admin: gestion de usuarios (FASE 23) ─────────────────────────────────────

VALID_PLANS = ("free", "basic", "premium")  # FASE 27: añadido 'basic'
VALID_STATUS = ("active", "suspended")


def list_users(engine, query: str = None, limit: int = 50, offset: int = 0):
    """Listado paginado de usuarios para el panel admin, con su uso del mes en curso.
    Devuelve {users:[...], total:int}. `query` filtra por email o nombre."""
    month = _current_month()
    where, params = "", []
    if query and query.strip():
        where = "WHERE u.email LIKE ? OR u.name LIKE ?"
        like = f"%{query.strip()}%"
        params = [like, like]
    conn = engine._get_conn()
    rows = conn.execute(f"""
        SELECT u.id, u.email, u.name, u.plan, u.status, u.email_verified,
               u.created_at, u.last_login,
               COALESCE(us.debates, 0) AS debates_month,
               COALESCE(us.est_cost_eur, 0) AS cost_month
        FROM users u
        LEFT JOIN usage us ON us.user_id = u.id AND us.month = ?
        {where}
        ORDER BY u.id DESC LIMIT ? OFFSET ?
    """, [month] + params + [int(limit), int(offset)]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM users u {where}", params).fetchone()[0]
    conn.close()
    users = [{
        "user_id": r["id"], "email": r["email"], "name": r["name"] or "",
        "plan": r["plan"], "status": r["status"],
        "email_verified": int(r["email_verified"] or 0),
        "created_at": r["created_at"], "last_login": r["last_login"],
        "debates_month": r["debates_month"], "cost_month": round(r["cost_month"] or 0, 4),
    } for r in rows]
    return {"users": users, "total": total}


def get_user_detail(engine, user_id: int):
    """Ficha completa de un usuario: datos, uso actual e historico, y su feedback."""
    u = get_user(engine, user_id)
    if u is None:
        return None
    conn = engine._get_conn()
    u["last_login"] = (conn.execute("SELECT last_login FROM users WHERE id=?", (user_id,)).fetchone() or [None])[0]
    u["usage_current"] = get_usage(engine, user_id)
    u["usage_history"] = [dict(r) for r in conn.execute(
        "SELECT month, debates, est_cost_eur, total_tokens FROM usage WHERE user_id=? ORDER BY month DESC LIMIT 24",
        (user_id,)).fetchall()]
    u["feedback"] = [dict(r) for r in conn.execute(
        "SELECT created_at, kind, conversation_id, vote, comment FROM feedback WHERE user_id=? ORDER BY id DESC LIMIT 50",
        (user_id,)).fetchall()]
    conn.close()
    return u


def _user_exists(conn, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is not None


def set_user_name(engine, user_id: int, name: str) -> str:
    """FASE 29: cambia el nombre del usuario (con el que las IAs le llaman en los debates).
    Devuelve el nombre guardado (recortado a 60 chars)."""
    name = (name or "").strip()[:60]
    conn = engine._get_conn()
    conn.execute("UPDATE users SET name=? WHERE id=?", (name, int(user_id)))
    conn.commit()
    conn.close()
    return name


def set_plan(engine, user_id: int, plan: str) -> bool:
    """Cambia la tarifa (free/premium). Devuelve False si el usuario no existe."""
    if plan not in VALID_PLANS:
        raise ValueError(f"plan invalido: {plan}")
    conn = engine._get_conn()
    if not _user_exists(conn, user_id):
        conn.close()
        return False
    conn.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))
    conn.commit()
    conn.close()
    return True


def set_status(engine, user_id: int, status: str) -> bool:
    """Activa/suspende un usuario. Al suspender, invalida TODAS sus sesiones vivas
    (sella sessions_invalid_before=now), no solo los logins futuros."""
    if status not in VALID_STATUS:
        raise ValueError(f"status invalido: {status}")
    conn = engine._get_conn()
    if not _user_exists(conn, user_id):
        conn.close()
        return False
    if status == "suspended":
        conn.execute("UPDATE users SET status=?, sessions_invalid_before=? WHERE id=?",
                     (status, datetime.now(timezone.utc).isoformat(), user_id))
    else:
        conn.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
    conn.commit()
    conn.close()
    return True


def reset_usage(engine, user_id: int) -> bool:
    """Borra el consumo del mes en curso de un usuario (cortesia / correccion)."""
    conn = engine._get_conn()
    if not _user_exists(conn, user_id):
        conn.close()
        return False
    conn.execute("DELETE FROM usage WHERE user_id=? AND month=?", (user_id, _current_month()))
    conn.commit()
    conn.close()
    return True


def admin_verify_email(engine, user_id: int) -> bool:
    """Marca el email como verificado a mano (usuario que no recibio el correo)."""
    conn = engine._get_conn()
    if not _user_exists(conn, user_id):
        conn.close()
        return False
    conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def admin_create_verification(engine, user_id: int):
    """Genera un token de verificacion para reenviar el correo. Devuelve (token, email) o None."""
    conn = engine._get_conn()
    row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return create_verification(engine, user_id), row[0]


def admin_create_password_reset(engine, user_id: int):
    """Genera un token de reset de contrasena para enviarlo. Devuelve (token, email) o None."""
    conn = engine._get_conn()
    row = conn.execute("SELECT email FROM users WHERE id=? AND status='active'", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _create_one_time_token(engine, "password_resets", user_id, RESET_EXPIRY_HOURS), row[0]


# ── Monitor de arranques del sistema (FASE 23) ───────────────────────────────

def record_startup(engine, env: str = None, version: str = None, keep: int = 200):
    """Registra un arranque del proceso. Conserva solo los ultimos `keep`."""
    conn = engine._get_conn()
    conn.execute("INSERT INTO startups (started_at, env, version) VALUES (?,?,?)",
                 (datetime.now(timezone.utc).isoformat(),
                  env or os.environ.get("HUMANIA_ENV", "dev"), version or ""))
    conn.execute("DELETE FROM startups WHERE id NOT IN "
                 "(SELECT id FROM startups ORDER BY id DESC LIMIT ?)", (int(keep),))
    conn.commit()
    conn.close()


def list_startups(engine, limit: int = 50):
    """Ultimos arranques (mas reciente primero) para detectar reinicios/caidas."""
    conn = engine._get_conn()
    rows = conn.execute("SELECT started_at, env, version FROM startups ORDER BY id DESC LIMIT ?",
                        (int(limit),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Tiempos de orquestacion (FASE 25 / 26): desglose A-E persistido ──────────
# Se guarda en el SERVIDOR al terminar la orquestacion, asi sobrevive aunque el
# cliente reciba un 504 (la orquestacion termina en backend aunque nginx corte).

def record_orch_time(engine, user_id, thread_id, rounds, bots, tiempos, total_tokens, keep: int = 500):
    """Persiste el desglose A-E de una orquestacion. Conserva las ultimas `keep`."""
    conn = engine._get_conn()
    conn.execute(
        "INSERT INTO orch_times (created_at, user_id, thread_id, rounds, bots, wall_ms, llm_ms, "
        "lock_ms, delays_ms, overhead_ms, total_tokens) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), user_id, thread_id, rounds, bots,
         tiempos.get("A_wall_ms"), tiempos.get("B_llm_ms"), tiempos.get("C_lock_ms"),
         tiempos.get("D_delays_ms"), tiempos.get("E_overhead_ms"), total_tokens))
    conn.execute("DELETE FROM orch_times WHERE id NOT IN "
                 "(SELECT id FROM orch_times ORDER BY id DESC LIMIT ?)", (int(keep),))
    conn.commit()
    conn.close()


def list_orch_times(engine, limit: int = 50):
    """Ultimas orquestaciones con su desglose A-E (mas reciente primero) + medias."""
    conn = engine._get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT created_at, user_id, thread_id, rounds, bots, wall_ms, llm_ms, lock_ms, "
        "delays_ms, overhead_ms, total_tokens FROM orch_times ORDER BY id DESC LIMIT ?",
        (int(limit),)).fetchall()]
    avg = dict(conn.execute(
        "SELECT COUNT(*) n, AVG(wall_ms) wall, AVG(llm_ms) llm, AVG(lock_ms) lock, "
        "AVG(delays_ms) delays, AVG(overhead_ms) overhead, AVG(total_tokens) tokens "
        "FROM orch_times").fetchone())
    conn.close()
    return {"items": rows, "avg": avg}


# ── Salud del sistema (FASE 28): muestras periódicas RAM/CPU/disco/capacidad ──

def record_system_health(engine, sample: dict, keep: int = 5000):
    """Persiste una muestra de salud del sistema. Conserva las últimas `keep`."""
    conn = engine._get_conn()
    conn.execute(
        "INSERT INTO system_health (created_at, ram_pct, swap_pct, cpu_pct, disk_used_pct, "
        "disk_free_pct, load1, inflight_orch, inflight_requests, capacity_pct, worst) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(),
         sample.get("ram_pct"), sample.get("swap_pct"), sample.get("cpu_pct"),
         sample.get("disk_used_pct"), sample.get("disk_free_pct"), sample.get("load1"),
         sample.get("inflight_orch"), sample.get("inflight_requests"),
         sample.get("capacity_pct"), sample.get("worst")))
    conn.execute("DELETE FROM system_health WHERE id NOT IN "
                 "(SELECT id FROM system_health ORDER BY id DESC LIMIT ?)", (int(keep),))
    conn.commit()
    conn.close()


def list_system_health(engine, hours: int = 24, limit: int = 2000):
    """Muestras de las últimas `hours` horas (más antigua primero, para graficar)."""
    conn = engine._get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT created_at, ram_pct, swap_pct, cpu_pct, disk_used_pct, disk_free_pct, "
        "load1, inflight_orch, inflight_requests, capacity_pct, worst FROM system_health "
        "WHERE created_at >= datetime('now', ?) ORDER BY id DESC LIMIT ?",
        (f"-{int(hours)} hours", int(limit))).fetchall()]
    rows.reverse()
    conn.close()
    return {"items": rows}


def reset_observability_stats(engine):
    """Vacía las métricas de OBSERVABILIDAD para empezar una medición limpia (botón
    'Reiniciar' del panel). Vacía la gráfica de salud + el RÉCORD DE PICO + los tiempos,
    y limpia los mensajes basura del arnés de carga (threads 'load_%').
    NO toca: cuentas, planes, conversaciones reales ('user_%'), feedback ni settings.
    Devuelve cuántas filas borró de cada cosa."""
    conn = engine._get_conn()
    n_health = conn.execute("DELETE FROM system_health").rowcount
    n_times = conn.execute("DELETE FROM orch_times").rowcount
    n_load = conn.execute("DELETE FROM messages WHERE thread_id LIKE 'load_%'").rowcount
    conn.commit()
    conn.close()
    return {"system_health": n_health, "orch_times": n_times, "load_messages": n_load}


def get_system_peak(engine):
    """La muestra de MÁXIMA capacidad alcanzada, con sus condiciones y fecha-hora."""
    conn = engine._get_conn()
    row = conn.execute(
        "SELECT created_at, ram_pct, swap_pct, cpu_pct, disk_used_pct, disk_free_pct, "
        "load1, inflight_orch, inflight_requests, capacity_pct, worst FROM system_health "
        "WHERE capacity_pct IS NOT NULL ORDER BY capacity_pct DESC, id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


# ── Preferencias por usuario (FASE 27): rondas, tokens, creatividad ──────────
# Cada usuario guarda SUS valores; la orquestacion los aplica acotados a su plan.

def get_user_prefs(engine, user_id) -> dict:
    if not user_id:
        return {}
    conn = engine._get_conn()
    row = conn.execute("SELECT prefs FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}


def set_user_prefs(engine, user_id, prefs: dict):
    conn = engine._get_conn()
    conn.execute("INSERT INTO user_prefs (user_id, prefs) VALUES (?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET prefs=excluded.prefs",
                 (user_id, json.dumps(prefs)))
    conn.commit()
    conn.close()
