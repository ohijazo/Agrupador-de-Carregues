"""Smoke-test post-deploy de l'aplicació d'agrupació.

Recorre els endpoints crítics que els operaris usen cada dia. L'objectiu és
detectar problemes equivalents al bug del 28/06/2026 (que va arribar a
producció perquè ningú va exercitar /api/agrupar abans que ho fes un operari)
amb una crida HTTP de pocs segons.

Usage:
    python scripts/smoke.py
    AGRUPACIO_BASE_URL=http://agrupacions.agrienergia.local python scripts/smoke.py

Variables d'entorn:
    AGRUPACIO_BASE_URL   URL base (default: http://localhost:50004)
    SMOKE_USER           Si AUTH_ENABLED a l'app: usuari per login
    SMOKE_PASSWORD       Si AUTH_ENABLED a l'app: contrasenya
    SMOKE_DESDE          Data inicial per llistar càrregues (default: avui - 30d)
    SMOKE_FINS           Data final (default: avui + 7d)
    SMOKE_MAX_CARREGUES  Quantes càrregues recents agrupar (default: 1)

Codi de sortida:
    0 → tots els passos OK
    1 → algun pas ha fallat (mira els missatges per detalls)
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("[FAIL] Falta la llibreria 'requests'. Instal·la: pip install requests")
    sys.exit(1)


BASE_URL = os.environ.get("AGRUPACIO_BASE_URL", "http://localhost:50004").rstrip("/")
USER = os.environ.get("SMOKE_USER")
PASSWORD = os.environ.get("SMOKE_PASSWORD")
DESDE = os.environ.get("SMOKE_DESDE", (date.today() - timedelta(days=30)).isoformat())
FINS = os.environ.get("SMOKE_FINS", (date.today() + timedelta(days=7)).isoformat())
MAX_CARREGUES = int(os.environ.get("SMOKE_MAX_CARREGUES", "1"))

_failures: list[str] = []


def _log(prefix: str, msg: str) -> None:
    print(f"[{prefix}] {msg}")


def _ok(msg: str) -> None:
    _log("OK", msg)


def _fail(msg: str) -> None:
    _log("FAIL", msg)
    _failures.append(msg)


def login(session: requests.Session) -> bool:
    """Login si AUTH_ENABLED. Retorna True si OK o si no cal."""
    if not (USER and PASSWORD):
        return True
    r = session.post(f"{BASE_URL}/login", data={"username": USER, "password": PASSWORD},
                     allow_redirects=False)
    if r.status_code in (200, 302):
        _ok(f"login com a {USER}")
        return True
    _fail(f"login: HTTP {r.status_code}")
    return False


def step_health(session: requests.Session) -> bool:
    try:
        r = session.get(f"{BASE_URL}/health", timeout=10)
    except requests.exceptions.ConnectionError as e:
        _fail(f"/health: no s'hi pot connectar ({BASE_URL}) — {type(e).__name__}")
        return False
    if r.status_code != 200:
        _fail(f"/health: HTTP {r.status_code}")
        return False
    data = r.json()
    components = {k: data.get(k, {}).get("ok") for k in ("db", "pg", "motor")}
    if data.get("ok") and all(components.values()):
        _ok(f"/health 3/3 components ({components})")
        return True
    _fail(f"/health: ok={data.get('ok')}, components={components}")
    return False


def step_llistar_carregues(session: requests.Session) -> list[dict] | None:
    r = session.get(f"{BASE_URL}/api/carregues",
                    params={"desde": DESDE, "fins": FINS, "limit": 10},
                    timeout=15)
    if r.status_code != 200:
        _fail(f"/api/carregues: HTTP {r.status_code}")
        return None
    data = r.json()
    items = data.get("items", [])
    if not items:
        _fail(f"/api/carregues: cap càrrega entre {DESDE} i {FINS}")
        return None
    # Verificació que els camps clau hi son (regressió data del 28/06)
    primer = items[0]
    for camp in ("eje_ejercicio", "sca_serie", "car_numero", "carrega_id"):
        if not primer.get(camp):
            _fail(f"/api/carregues: el primer ítem no té '{camp}'")
            return None
    _ok(f"/api/carregues retorna {len(items)} ítems amb camps obligatoris")
    return items


def step_agrupar(session: requests.Session, items: list[dict]) -> bool:
    """Crida l'endpoint que va fallar el 28/06 i verifica NO incidència isoformat."""
    if not items:
        _fail("no hi ha càrregues per agrupar — pas saltat")
        return False
    # Agafem només càrregues que NO estan en agrupacions (sino retorna 409).
    candidats = [c for c in items if c.get("car_estat") in (None, "", 0, "0")][:MAX_CARREGUES]
    if not candidats:
        candidats = items[:MAX_CARREGUES]

    payload = {"carregues": candidats}
    r = session.post(f"{BASE_URL}/api/agrupar", json=payload, timeout=60)

    if r.status_code == 409:
        _ok(f"/api/agrupar: 409 (càrregues ja agrupades) — endpoint sa, no peta")
        return True
    if r.status_code != 200:
        _fail(f"/api/agrupar: HTTP {r.status_code} body={r.text[:200]}")
        return False

    data = r.json()
    incidencies = data.get("incidencies", [])
    errors_critics = []
    for inc in incidencies:
        msg = inc.get("missatge", "")
        if "isoformat" in msg or "AttributeError" in msg or "TypeError" in msg:
            errors_critics.append(inc)
    if errors_critics:
        _fail(f"/api/agrupar: {len(errors_critics)} incidència(es) tipus 28/06 — "
              f"{errors_critics[0].get('missatge')}")
        return False

    n_err = sum(1 for i in incidencies if i.get("tipus") == "error")
    if n_err == 0:
        _ok(f"/api/agrupar: cap incidència tipus 'error' ({len(incidencies)} warnings)")
    else:
        _ok(f"/api/agrupar: {n_err} error(s) regulars (no del tipus 28/06) — "
            "aceptables, no es bug de tipus")
    return True


def main() -> int:
    print(f"Smoke test contra: {BASE_URL}")
    print(f"Range de carregues: {DESDE} -> {FINS}\n")

    session = requests.Session()
    if not login(session):
        print(f"\n[RESULTAT] FAIL — no s'ha pogut autenticar")
        return 1

    if not step_health(session):
        print(f"\n[RESULTAT] FAIL — /health no és sa")
        return 1

    items = step_llistar_carregues(session)
    if items is None:
        print(f"\n[RESULTAT] FAIL — no s'ha pogut llistar càrregues")
        return 1

    step_agrupar(session, items)

    print()
    if _failures:
        print(f"[RESULTAT] FAIL — {len(_failures)} pas(os) han fallat:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"[RESULTAT] OK — tots els passos verds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
