"""Tests del cache de /health.

L'endpoint /health comprova SQL Server + PostgreSQL + motor; cada crida
és ~500ms. Per evitar saturar workers en monitoring repetit, hi ha una
cache curta (TTL configurable per HEALTH_CACHE_TTL_MS, default 5s).
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Stub motor/models abans d'importar app (idèntic a test_endpoints.py)
sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client():
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def _reset_cache():
    import app as app_module
    with app_module._HEALTH_LOCK:
        app_module._HEALTH_CACHE["ts"] = 0.0
        app_module._HEALTH_CACHE["body"] = None
        app_module._HEALTH_CACHE["status"] = 200


def test_health_cacheja_resultats(client, monkeypatch):
    import app as app_module
    _reset_cache()
    calls = {"n": 0}

    def fake_calc():
        calls["n"] += 1
        return ({"ok": True, "db": {"ok": True}, "motor": {"ok": True}, "pg": {"ok": True}}, 200)

    monkeypatch.setattr(app_module, "_calc_health", fake_calc)
    # TTL gran per garantir cache-hit a la segona crida
    monkeypatch.setenv("HEALTH_CACHE_TTL_MS", "60000")

    r1 = client.get("/health")
    assert r1.status_code == 200
    assert r1.get_json()["ok"] is True

    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True

    # Només una crida a _calc_health gràcies al cache
    assert calls["n"] == 1


def test_health_recalcula_quan_ttl_zero(client, monkeypatch):
    import app as app_module
    _reset_cache()
    calls = {"n": 0}

    def fake_calc():
        calls["n"] += 1
        return ({"ok": True, "db": {"ok": True}, "motor": {"ok": True}, "pg": {"ok": True}}, 200)

    monkeypatch.setattr(app_module, "_calc_health", fake_calc)
    # TTL 0 → mai cache-hit; cada petició recalcula
    monkeypatch.setenv("HEALTH_CACHE_TTL_MS", "0")

    client.get("/health")
    client.get("/health")
    assert calls["n"] == 2
