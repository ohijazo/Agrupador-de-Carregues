"""Tests d'agrupacions_store: persistència JSON, índex de càrregues agrupades i reset."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agrupacions_store  # noqa: E402


@pytest.fixture
def store_tmp(tmp_path, monkeypatch):
    """Substitueix el directori de dades per un tmp i invalida el cache d'índex."""
    monkeypatch.setattr(agrupacions_store, "_DIR", str(tmp_path))
    agrupacions_store._invalidar_index()
    yield tmp_path
    agrupacions_store._invalidar_index()


def _resultat(productes=("ART1",)):
    return {
        "productes": [{"art_codi": p, "art_descrip": p} for p in productes],
        "total_palets_fisics": 1,
        "total_sacs": 10,
    }


def _carrega(cid="2026/01/0000001"):
    return {
        "eje_ejercicio": "2026", "sca_serie": "01", "car_numero": "0000001",
        "carrega_id": cid,
    }


# --- guardar / obtenir / eliminar ----------------------------------------

def test_guardar_i_obtenir(store_tmp):
    info = agrupacions_store.guardar("Test", [_carrega()], _resultat())
    assert info["id"] and info["nom"] == "Test"
    obj = agrupacions_store.obtenir(info["id"])
    assert obj is not None
    assert obj["nom"] == "Test"
    assert obj["productes_preparats"] == []


def test_eliminar(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega()], _resultat())
    assert agrupacions_store.eliminar(info["id"]) is True
    assert agrupacions_store.obtenir(info["id"]) is None


# --- index_carregues_agrupades --------------------------------------------

def test_index_buit_quan_no_hi_ha_agrupacions(store_tmp):
    assert agrupacions_store.index_carregues_agrupades() == {}


def test_index_indica_carrega_en_agrupacio_activa(store_tmp):
    info = agrupacions_store.guardar("Activa", [_carrega("2026/01/0000123")], _resultat(("A", "B")))
    idx = agrupacions_store.index_carregues_agrupades()
    entries = idx.get("2026/01/0000123") or []
    assert len(entries) == 1
    assert entries[0]["id"] == info["id"]
    assert entries[0]["finalitzada"] is False


def test_index_marca_finalitzada_quan_tots_preparats(store_tmp):
    info = agrupacions_store.guardar("Acabada", [_carrega("2026/01/0000999")], _resultat(("A", "B")))
    agrupacions_store.marca_producte(info["id"], "A", True)
    agrupacions_store.marca_producte(info["id"], "B", True)
    idx = agrupacions_store.index_carregues_agrupades()
    entries = idx["2026/01/0000999"]
    assert entries[0]["finalitzada"] is True


def test_index_diferencia_activa_de_finalitzada(store_tmp):
    a = agrupacions_store.guardar("Activa", [_carrega("2026/01/0000001")], _resultat(("X",)))
    b = agrupacions_store.guardar("Acabada", [_carrega("2026/01/0000002")], _resultat(("Y",)))
    agrupacions_store.marca_producte(b["id"], "Y", True)
    idx = agrupacions_store.index_carregues_agrupades()
    assert idx["2026/01/0000001"][0]["finalitzada"] is False
    assert idx["2026/01/0000002"][0]["finalitzada"] is True


def test_index_carrega_present_en_dues_agrupacions(store_tmp):
    cid = "2026/01/0000555"
    agrupacions_store.guardar("A1", [_carrega(cid)], _resultat(("X",)))
    agrupacions_store.guardar("A2", [_carrega(cid)], _resultat(("Y",)))
    idx = agrupacions_store.index_carregues_agrupades()
    assert len(idx[cid]) == 2


def test_index_es_recalcula_quan_canvia_directori(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega("2026/01/0000007")], _resultat())
    assert "2026/01/0000007" in agrupacions_store.index_carregues_agrupades()
    agrupacions_store.eliminar(info["id"])
    assert "2026/01/0000007" not in agrupacions_store.index_carregues_agrupades()


def test_index_ignora_fitxers_corruptes(store_tmp):
    # Fitxer JSON invàlid → no peta, només l'ignora.
    bad = store_tmp / "abcdef1234567890.json"
    bad.write_text("not json{}", encoding="utf-8")
    assert agrupacions_store.index_carregues_agrupades() == {}


# --- reset_preparats ------------------------------------------------------

def test_reset_preparats_desfas_tot(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega()], _resultat(("A", "B", "C")))
    agrupacions_store.marca_producte(info["id"], "A", True)
    agrupacions_store.marca_producte(info["id"], "B", True)
    obj = agrupacions_store.reset_preparats(info["id"])
    assert obj is not None
    assert obj["productes_preparats"] == []
    obj2 = agrupacions_store.obtenir(info["id"])
    assert obj2["productes_preparats"] == []


def test_reset_preparats_id_inexistent(store_tmp):
    assert agrupacions_store.reset_preparats("a" * 32) is None


# --- Concurrència (file lock) -------------------------------------------

def test_marca_producte_concurrent_no_perd_dades(store_tmp):
    """Dos threads marquen articles DIFERENTS de la mateixa agrupació alhora.

    Sense lock es perd una marcada (lost update). Amb portalocker tots dos
    han de quedar al productes_preparats final.
    """
    import threading
    info = agrupacions_store.guardar("X", [_carrega()], _resultat(("A", "B", "C", "D")))
    id_ = info["id"]
    barrier = threading.Barrier(2)

    def marca(art):
        barrier.wait()
        agrupacions_store.marca_producte(id_, art, True)

    t1 = threading.Thread(target=marca, args=("A",))
    t2 = threading.Thread(target=marca, args=("B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    obj = agrupacions_store.obtenir(id_)
    assert set(obj["productes_preparats"]) == {"A", "B"}


def test_reset_no_corromp_si_concurrent_amb_marca(store_tmp):
    """Reset + marca simultàniament: el fitxer final ha de quedar consistent
    (no JSON corrupte). L'ordre pot variar però l'objecte ha de ser vàlid.
    """
    import threading
    info = agrupacions_store.guardar("Y", [_carrega()], _resultat(("A", "B")))
    id_ = info["id"]
    agrupacions_store.marca_producte(id_, "A", True)
    barrier = threading.Barrier(2)

    def reset():
        barrier.wait()
        agrupacions_store.reset_preparats(id_)

    def marca():
        barrier.wait()
        agrupacions_store.marca_producte(id_, "B", True)

    t1 = threading.Thread(target=reset)
    t2 = threading.Thread(target=marca)
    t1.start(); t2.start()
    t1.join(); t2.join()

    obj = agrupacions_store.obtenir(id_)
    assert obj is not None
    assert isinstance(obj.get("productes_preparats"), list)
    # Sigui quin sigui l'ordre, el set és subset de {A, B}
    assert set(obj["productes_preparats"]).issubset({"A", "B"})


def test_id_invalid_a_modificar_no_peta(store_tmp):
    """Un id que no compleix el regex ha de retornar None, no llançar."""
    assert agrupacions_store.marca_producte("../etc/passwd", "A", True) is None
    assert agrupacions_store.reset_preparats("../etc/passwd") is None
