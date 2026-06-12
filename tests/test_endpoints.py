"""Tests dels endpoints Flask amb monkeypatch del store i del motor.

Els endpoints que toquen SQL Server (llistar_carregues, etc.) no es proven
aquí — caldria una BD real o mocks més complexos. Aquí cobrim la lògica
HTTP (validació, 404/409, audit log) i la integració amb el store.
"""
import os
import sys
import types
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Stub motor/models abans d'importar app (per evitar import errors si la
# dependència germana no està disponible)
sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agrupacions_store
    monkeypatch.setattr(agrupacions_store, "_DIR", str(tmp_path))
    agrupacions_store._invalidar_index()
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c
    agrupacions_store._invalidar_index()


def _carrega(cid="2026/01/0000001"):
    return {
        "carrega_id": cid,
        "eje_ejercicio": "2026",
        "sca_serie": "01",
        "car_numero": cid.split("/")[-1],
    }


def _resultat(productes=("A",)):
    return {
        "productes": [{"art_codi": p, "art_descrip": p} for p in productes],
        "total_palets_fisics": 1,
        "total_sacs": 5,
    }


# --- /api/agrupacions ----------------------------------------------------
def test_guardar_agrupacio(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Test 1", "carregues": [_carrega()], "resultat": _resultat(),
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["nom"] == "Test 1"
    assert d["n_carregues"] == 1
    assert "id" in d


def test_guardar_sense_nom_es_400(client):
    r = client.post("/api/agrupacions", json={
        "nom": "", "carregues": [_carrega()], "resultat": _resultat(),
    })
    assert r.status_code == 400


def test_guardar_sense_carregues_es_400(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [], "resultat": _resultat(),
    })
    assert r.status_code == 400


def test_obtenir_agrupacio_no_trobada(client):
    r = client.get("/api/agrupacions/" + "a" * 32)
    assert r.status_code == 404


def test_eliminar_agrupacio(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(),
    })
    id_ = r.get_json()["id"]
    r = client.delete(f"/api/agrupacions/{id_}")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    r = client.get(f"/api/agrupacions/{id_}")
    assert r.status_code == 404


def test_eliminar_inexistent(client):
    r = client.delete("/api/agrupacions/" + "b" * 32)
    assert r.status_code == 404


# --- /api/agrupacions/<id>/producte -------------------------------------
def test_marcar_producte(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A", "B")),
    })
    id_ = r.get_json()["id"]
    r = client.patch(f"/api/agrupacions/{id_}/producte",
                     json={"art_codi": "A", "preparat": True})
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 1


def test_desmarcar_producte(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A",)),
    })
    id_ = r.get_json()["id"]
    client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": True})
    r = client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": False})
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 0


def test_reset_preparats(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A", "B", "C")),
    })
    id_ = r.get_json()["id"]
    for art in ("A", "B"):
        client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": art, "preparat": True})
    r = client.post(f"/api/agrupacions/{id_}/reset-preparats")
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 0


def test_reset_preparats_inexistent(client):
    r = client.post("/api/agrupacions/" + "c" * 32 + "/reset-preparats")
    assert r.status_code == 404


# --- /api/agrupar (validació 409 duplicats) -----------------------------
def test_agrupar_409_si_ja_agrupada(client, monkeypatch):
    # Guardem agrupació amb càrrega X
    r = client.post("/api/agrupacions", json={
        "nom": "Activa", "carregues": [_carrega("2026/01/0000777")], "resultat": _resultat(),
    })
    assert r.status_code == 200
    # Provem d'agrupar la mateixa càrrega → 409
    r = client.post("/api/agrupar", json={"carregues": [_carrega("2026/01/0000777")]})
    assert r.status_code == 409
    d = r.get_json()
    assert "duplicats" in d
    assert d["duplicats"][0]["carrega_id"] == "2026/01/0000777"


def test_agrupar_finalitzada_tambe_bloqueja(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Acabada", "carregues": [_carrega("2026/01/0000888")], "resultat": _resultat(("A",)),
    })
    id_ = r.get_json()["id"]
    client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": True})
    # Ara és finalitzada però segueix bloquejant
    r = client.post("/api/agrupar", json={"carregues": [_carrega("2026/01/0000888")]})
    assert r.status_code == 409


def test_agrupar_force_no_existeix(client):
    """Verifica que ?force=1 ha estat eliminat com a via per saltar la regla."""
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega("2026/01/0000999")], "resultat": _resultat(),
    })
    r = client.post("/api/agrupar?force=1", json={"carregues": [_carrega("2026/01/0000999")]})
    assert r.status_code == 409


def test_agrupar_validacio_400(client):
    r = client.post("/api/agrupar", json={"carregues": []})
    assert r.status_code == 400
    r = client.post("/api/agrupar", json={"carregues": [{"carrega_id": "x"}]})
    # falten camps obligatoris
    assert r.status_code == 400


# --- Pages estàtiques i CSP ---------------------------------------------
def test_index_te_csp_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_magatzem_llista_render(client):
    r = client.get("/magatzem")
    assert r.status_code == 200


def test_magatzem_prep_404_si_no_existeix(client):
    r = client.get("/magatzem/" + "d" * 32)
    assert r.status_code == 404


# --- /api/plantilles ----------------------------------------------------
def test_guardar_amb_plantilla(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Test plantilla",
        "carregues": [{**_carrega(), "tra_codi": "T01", "transportista": "Trans1"}],
        "resultat": _resultat(),
        "plantilla": True,
    })
    assert r.status_code == 200


def test_llistar_plantilles_vacia(client):
    r = client.get("/api/plantilles")
    assert r.status_code == 200
    assert r.get_json() == []


def test_llistar_plantilles_amb_dades(client):
    # 1 sense plantilla, 1 amb
    client.post("/api/agrupacions", json={
        "nom": "Sense",
        "carregues": [_carrega("2026/01/0000001")],
        "resultat": _resultat(),
    })
    client.post("/api/agrupacions", json={
        "nom": "Amb plantilla",
        "carregues": [{**_carrega("2026/01/0000002"), "tra_codi": "T01", "transportista": "T1"}],
        "resultat": _resultat(),
        "plantilla": True,
    })
    r = client.get("/api/plantilles")
    assert r.status_code == 200
    d = r.get_json()
    assert len(d) == 1
    assert d[0]["nom"] == "Amb plantilla"
    assert d[0]["transportistes"][0]["tra_codi"] == "T01"
