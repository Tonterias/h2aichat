#!/usr/bin/env python3
"""FASE 28 — Lectura de métricas del sistema (RAM/CPU/swap/disco/carga).

Usa `psutil` si está disponible; si no, degrada con la stdlib (el disco SIEMPRE
se puede leer con shutil; la RAM en Linux via /proc/meminfo). El import de psutil
es tolerante a fallos: aunque no esté instalado, el módulo NO rompe el arranque
del servidor — simplemente devuelve None en lo que no pueda medir.

Funciones puras y sin estado de aplicación: la lógica de "capacidad" recibe los
valores ya leídos, lo que permite inyectar datos en los tests sin psutil real.
"""
import os
import shutil

try:
    import psutil  # noqa: F401
except Exception:  # ImportError u otros (entornos raros)
    psutil = None


def disk_used_pct(path: str = "/"):
    """% de disco USADO (0-100). Siempre disponible (stdlib)."""
    try:
        total, used, _free = shutil.disk_usage(path)
        if total <= 0:
            return None
        return round(used / total * 100, 1)
    except Exception:
        return None


def disk_free_pct(path: str = "/"):
    u = disk_used_pct(path)
    return None if u is None else round(100.0 - u, 1)


def ram_pct():
    """% de RAM usada (0-100)."""
    if psutil:
        try:
            return round(psutil.virtual_memory().percent, 1)
        except Exception:
            pass
    return _meminfo_pct()


def swap_pct():
    if psutil:
        try:
            return round(psutil.swap_memory().percent, 1)
        except Exception:
            return None
    return None


def cpu_pct():
    """% de CPU instantáneo (no bloqueante)."""
    if psutil:
        try:
            # interval=0.1: mide durante 100ms y da un valor REAL. Con interval=None la
            # PRIMERA llamada (o tras una pausa) devuelve 0.0 (no hay linea base) -> CPU=0%.
            return round(psutil.cpu_percent(interval=0.1), 1)
        except Exception:
            return None
    return None


def load1():
    """Carga media a 1 min (solo Unix)."""
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None


def cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _meminfo_pct():
    """Fallback Linux sin psutil: % RAM usada desde /proc/meminfo."""
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.strip().split()[0])  # kB
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        if total <= 0:
            return None
        return round((total - avail) / total * 100, 1)
    except Exception:
        return None


def read_system_metrics(disk_path: str = "/"):
    """Snapshot crudo del sistema (sin lógica de capacidad)."""
    return {
        "ram_pct": ram_pct(),
        "swap_pct": swap_pct(),
        "cpu_pct": cpu_pct(),
        "disk_used_pct": disk_used_pct(disk_path),
        "disk_free_pct": disk_free_pct(disk_path),
        "load1": load1(),
        "cpu_count": cpu_count(),
        "has_psutil": bool(psutil),
    }


def compute_capacity(metrics: dict, inflight_orch: int = 0, orch_cap: int = 8):
    """Capacidad 0-100 = el PEOR de los sub-medidores disponibles.

    Si cualquier recurso está al 99%, el sistema está al borde. Solo cuenta lo
    que se pudo medir (None se ignora). 'load' se normaliza a % sobre núcleos.
    """
    sub = {}
    if metrics.get("ram_pct") is not None:
        sub["ram"] = float(metrics["ram_pct"])
    if metrics.get("disk_used_pct") is not None:
        sub["disk"] = float(metrics["disk_used_pct"])
    if metrics.get("cpu_pct") is not None:
        sub["cpu"] = float(metrics["cpu_pct"])
    if metrics.get("load1") is not None and metrics.get("cpu_count"):
        sub["load"] = round(min(metrics["load1"] / metrics["cpu_count"] * 100.0, 200.0), 1)
    if orch_cap and orch_cap > 0:
        sub["orch"] = round(min(inflight_orch / orch_cap * 100.0, 200.0), 1)
    capacity = max(sub.values()) if sub else 0.0
    worst = max(sub, key=sub.get) if sub else None
    return {"capacity_pct": round(capacity, 1), "worst": worst, "sub": sub}
