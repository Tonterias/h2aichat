#!/usr/bin/env python3
"""FASE 28 — Arnés de prueba de carga "a tope hasta que caiga".

Escala la concurrencia por escalones hasta que el servidor deja de responder,
sondeando la salud (/api/admin/health) cada 1-2 s para capturar la ULTIMA lectura
buena antes del quiebre = las CONDICIONES exactas de la caída. Repite el ciclo N
veces (el PO quiere forzarlo varias veces, no una ni dos).

Dos perillas independientes (como pidió el PO):
  --users   peticiones ligeras concurrentes (polling) ≈ usuarios conectados
  --orch    orquestaciones concurrentes = la carga PESADA real

Modo por defecto GRATIS: rounds=0 (no llama a ningún LLM, 0 coste). Con --rounds>0
y --opencode se hace realista (gasta OpenCode, tarifa plana).

Uso:
  python execution/scripts/load_test.py --base-url http://127.0.0.1:8000 \
      --token <TOKEN> --repeats 3 --max-level 256

NUNCA apuntar a PROD a tope si hay usuarios. Hacer backup antes (lo hace el operador).
"""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# Sin dependencias externas: solo stdlib (urllib). Así corre en cualquier sitio
# (droplet incluido) sin tener que instalar 'requests'.


def _auth(token):
    # El token de operador es el MAESTRO (HUMANIA_TOKEN), NO un JWT: va por la cabecera
    # X-Humania-Token, que da acceso de administracion. Si se mandara por
    # 'Authorization: Bearer' el middleware intentaria decodificarlo como JWT y daria 401.
    return {"X-Humania-Token": token} if token else {}


def _http(method, url, headers, data=None, timeout=30):
    """Devuelve (status, body_bytes). Lanza en errores de red/timeout (code 0 lo
    pone quien llama). Los HTTP 4xx/5xx se devuelven con su código, no como excepción."""
    body = json.dumps(data).encode() if data is not None else None
    h = dict(headers)
    # Imitar a nginx: en produccion la app redirige (301) el HTTP directo a HTTPS si no
    # ve esta cabecera. Sin esto, golpear 127.0.0.1:8000 daria 301 en vez de procesar.
    h["X-Forwarded-Proto"] = "https"
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def fetch_health(base, token, timeout=4):
    """Lee la salud en vivo. Devuelve el sample o None si el server no responde."""
    try:
        status, body = _http("GET", f"{base}/api/admin/health", _auth(token), timeout=timeout)
        if status == 200:
            return json.loads(body).get("sample")
    except Exception:
        return None
    return None


def one_orchestrate(base, token, rounds, thread_id, timeout):
    t0 = time.time()
    try:
        status, _ = _http("POST", f"{base}/orchestrate?rounds={rounds}&wait=1", _auth(token),
                          data={"recipient_id": "qwen_plus", "body": "carga",
                                "sender_id": "miguel", "thread_id": thread_id}, timeout=timeout)
        # OK = SOLO 2xx. Un 401/403/5xx o un fallo de conexion (code 0) cuenta como fallo real.
        return {"ms": (time.time() - t0) * 1000, "code": status, "ok": 200 <= status < 300}
    except Exception as e:
        return {"ms": (time.time() - t0) * 1000, "code": 0, "ok": False, "err": type(e).__name__}


def run_level(base, token, n_orch, n_users, rounds, timeout):
    """Lanza n_orch orquestaciones + n_users peticiones ligeras EN PARALELO.
    Devuelve métricas del escalón y la salud justo después."""
    results = []
    with ThreadPoolExecutor(max_workers=n_orch + n_users + 1) as ex:
        futs = []
        for i in range(n_orch):
            futs.append(ex.submit(one_orchestrate, base, token, rounds, f"load_{i}", timeout))
        for i in range(n_users):
            futs.append(ex.submit(lambda: _light(base, token, timeout)))
        # sondea salud a mitad del escalón (mientras hay carga en vuelo)
        time.sleep(0.5)
        mid_health = fetch_health(base, token)
        for f in as_completed(futs):
            try:
                r = f.result()
                if isinstance(r, dict) and "ms" in r:
                    results.append(r)
            except Exception:
                pass
    orch_res = [r for r in results if r]
    oks = [r for r in orch_res if r.get("ok")]
    lat = [r["ms"] for r in orch_res if r.get("code", 0) > 0]
    return {
        "n_orch": n_orch, "n_users": n_users,
        "sent": len(orch_res), "ok": len(oks),
        "failed": len(orch_res) - len(oks),
        "p50_ms": round(statistics.median(lat), 1) if lat else None,
        "p95_ms": round(_pct(lat, 95), 1) if lat else None,
        "health": mid_health,
    }


def _light(base, token, timeout):
    try:
        _http("GET", f"{base}/api/all-messages", _auth(token), timeout=timeout)
    except Exception:
        pass
    return None


def _pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    k = int(round((p / 100) * (len(s) - 1)))
    return s[k]


def ramp(base, token, rounds, max_level, users_ratio, timeout, fail_threshold=0.5):
    """Sube la concurrencia (2,4,8,...) hasta que >50% de las orquestaciones fallan
    o el server deja de responder. Devuelve los escalones y el QUIEBRE con condiciones."""
    steps, level, last_good_health = [], 2, None
    while level <= max_level:
        n_users = int(level * users_ratio)
        st = run_level(base, token, level, n_users, rounds, timeout)
        steps.append(st)
        alive = fetch_health(base, token, timeout=4)
        fail_ratio = st["failed"] / st["sent"] if st["sent"] else 1.0
        print(f"  nivel orq={level:4} usr={n_users:4} | ok={st['ok']:4}/{st['sent']:<4} "
              f"fail={fail_ratio*100:4.0f}% p95={st['p95_ms']} "
              f"cap={(st['health'] or {}).get('capacity_pct')} ram={(st['health'] or {}).get('ram_pct')}")
        if st["health"]:
            last_good_health = st["health"]
        # QUIEBRE = las orquestaciones empiezan a fallar de verdad (>=50%): 5xx o conexiones
        # rechazadas (server saturado). Que no se pueda leer la salud NO cuenta como caida
        # por si sola (puede ser solo permisos); se usa como dato informativo.
        if fail_ratio >= fail_threshold:
            return {"broke_at_level": level, "fail_ratio": round(fail_ratio, 2),
                    "server_down": alive is None, "conditions": last_good_health or st["health"], "steps": steps}
        level *= 2
    return {"broke_at_level": None, "note": "no cayó hasta max_level",
            "conditions": last_good_health, "steps": steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--rounds", type=int, default=0, help="0 = gratis (sin LLM)")
    ap.add_argument("--repeats", type=int, default=3, help="cuántas veces forzar la caída")
    ap.add_argument("--max-level", type=int, default=256)
    ap.add_argument("--users-ratio", type=float, default=1.5, help="peticiones ligeras por cada orquestación")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--cooldown", type=float, default=8, help="segundos de descanso entre repeticiones")
    args = ap.parse_args()

    print(f"== Prueba de carga -> {args.base_url} (rounds={args.rounds}, repeats={args.repeats}) ==")
    h0 = fetch_health(args.base_url, args.token)
    if h0 is None:
        print("AVISO: no se pudo leer /api/admin/health (¿token admin? ¿server arriba?). Sigo igual.")
    breaks = []
    for rep in range(1, args.repeats + 1):
        print(f"\n--- Repetición {rep}/{args.repeats} ---")
        res = ramp(args.base_url, args.token, args.rounds, args.max_level, args.users_ratio, args.timeout)
        breaks.append(res)
        c = res.get("conditions") or {}
        print(f"  >> QUIEBRE: nivel={res.get('broke_at_level')} server_down={res.get('server_down')} | "
              f"CONDICIONES: cap={c.get('capacity_pct')}% ram={c.get('ram_pct')}% cpu={c.get('cpu_pct')}% "
              f"disco={c.get('disk_used_pct')}% orquestando={c.get('inflight_orch')} peticiones={c.get('inflight_requests')}")
        if rep < args.repeats:
            print(f"  (descanso {args.cooldown}s para que el server se recupere)")
            time.sleep(args.cooldown)

    print("\n== INFORME ==")
    levels = [b.get("broke_at_level") for b in breaks if b.get("broke_at_level")]
    if levels:
        print(f"Niveles de quiebre: {levels}  (mediana {int(statistics.median(levels))})")
    for i, b in enumerate(breaks, 1):
        c = b.get("conditions") or {}
        print(f"  Rep {i}: rompió a orq={b.get('broke_at_level')} | RAM {c.get('ram_pct')}% "
              f"orquestando {c.get('inflight_orch')} peticiones {c.get('inflight_requests')}")
    return breaks


if __name__ == "__main__":
    main()
