"""Tests de l'endpoint /api/pbi/carregues (Power BI).

L'endpoint llegeix de SQL Server (no PG), però la lògica d'autenticació via
X-Api-Key i de rate-limit no necessita la BD. Aquests tests cobreixen la
seguretat i la forma de resposta sense haver de simular les dades reals.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client_no_key(monkeypatch):
    """Client amb PBI_API_KEY sense definir. Posem explícitament a buit per
    garantir el comportament independentment del que tingui .env / setdefault."""
    monkeypatch.setenv("PBI_API_KEY", "")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import app as app_module
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def client_with_key(monkeypatch):
    """Client amb PBI_API_KEY configurada (key="testkey123")."""
    monkeypatch.setenv("PBI_API_KEY", "testkey123")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    # Reset el rate-limit bucket entre tests (in-memory, comparteix entre tests)
    import app as app_module
    app_module._rate_buckets.clear()
    with app_module.app.test_client() as c:
        yield c


# --- Sense PBI_API_KEY configurada → 503 ---------------------------------
def test_pbi_sense_api_key_configurada(client_no_key):
    r = client_no_key.get("/api/pbi/carregues")
    assert r.status_code == 503
    assert "PBI_API_KEY" in r.get_json().get("error", "")


# --- Amb PBI_API_KEY configurada ---------------------------------------
def test_pbi_sense_header(client_with_key):
    r = client_with_key.get("/api/pbi/carregues")
    assert r.status_code == 401
    assert "API key" in r.get_json().get("error", "")


def test_pbi_header_dolent(client_with_key):
    r = client_with_key.get("/api/pbi/carregues", headers={"X-Api-Key": "wrong"})
    assert r.status_code == 401


def test_pbi_header_buit(client_with_key):
    r = client_with_key.get("/api/pbi/carregues", headers={"X-Api-Key": ""})
    assert r.status_code == 401


# --- Rate-limit ----------------------------------------------------------
def test_pbi_rate_limit_dispara_a_30(client_with_key, monkeypatch):
    """30 peticions ràpides amb key correcta i la 31a hauria de retornar 429.
    Nota: les peticions toquen SQL Server, si no és disponible (en CI o local
    sense l'ERP) retorna 5xx — però el rate-limit es comprova ABANS de la
    consulta, així que les primeres 30 acaben amb 5xx o 200, i la 31a 429."""
    # Reset del bucket per garantir comptador zero
    import app as app_module
    app_module._rate_buckets.clear()
    headers = {"X-Api-Key": "testkey123"}
    # Fem 30 peticions. Si SQL Server no respon, retorna 503 — però NO 429
    statuses = []
    for _ in range(30):
        r = client_with_key.get("/api/pbi/carregues", headers=headers)
        statuses.append(r.status_code)
        # Important: si la primera ja és 429, alguna cosa està malament
        if r.status_code == 429:
            break
    assert all(s != 429 for s in statuses), "Cap de les primeres 30 hauria d'estar rate-limitada"
    # La 31a ha de ser 429
    r31 = client_with_key.get("/api/pbi/carregues", headers=headers)
    assert r31.status_code == 429, f"31a hauria de ser 429, ha sigut {r31.status_code}"
    assert "Massa peticions" in r31.get_json().get("error", "")


# --- compare_digest contra timing attack -------------------------------
def test_pbi_compara_amb_compare_digest(client_with_key):
    """No és un test funcional real (Python compare_digest no es pot detectar
    des de fora), però sí podem verificar que keys d'igual longitud però
    diferents valors retornen 401 (no triggers timing-related)."""
    r1 = client_with_key.get("/api/pbi/carregues", headers={"X-Api-Key": "testkey122"})
    r2 = client_with_key.get("/api/pbi/carregues", headers={"X-Api-Key": "AAAAAAAAAA"})
    assert r1.status_code == 401
    assert r2.status_code == 401
