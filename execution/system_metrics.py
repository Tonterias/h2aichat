#!/usr/bin/env python3
"""Reads system metrics: RAM, CPU, swap, disk and load.

Uses `psutil` when available and degrades to the standard library otherwise: disk can
ALWAYS be read with shutil, and RAM on Linux through /proc/meminfo. Importing psutil
is fault-tolerant: even when it is missing, this module does NOT break the server's
start-up; it simply returns None for whatever it cannot measure.

Pure functions with no application state: the "capacity" logic takes values that have
already been read, which lets tests inject data without a real psutil.
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
    """Instantaneous CPU percentage, non-blocking."""
    if psutil:
        try:
            # interval=0.1 measures for 100 ms and gives a REAL value. With interval=None the
            # FIRST call (or one after a pause) returns 0.0, because there is no baseline yet.
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
    """Linux fallback without psutil: percentage of RAM used, from /proc/meminfo."""
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
    """Raw system snapshot, with no capacity logic applied."""
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
    """Capacity from 0 to 100: the WORST of the available sub-gauges.

    If any resource sits at 99%, the system is on the edge. Only what could be measured
    counts (None is ignored). 'load' is normalised to a percentage over the core count.
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
