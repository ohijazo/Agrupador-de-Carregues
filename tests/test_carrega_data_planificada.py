"""Tests del modul carrega_data_planificada (snapshot + override).

Aquests tests no necessiten PostgreSQL real — mocken el modul `db` per
verificar la logica del modul. Per als tests amb PG real, vegeu
test_carrega_data_planificada_pg.py (no inclos aqui).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_aplicar_no_toca_items_no_sortida():
    import carrega_data_planificada as cdp
    items = [
        {"carrega_id": "2026/01/0000001", "car_estat": 0,
         "car_fecsalida": "2026-07-01", "car_fecsalida_hora": "08:00"},
        {"carrega_id": "2026/01/0000002", "car_estat": 1,
         "car_fecsalida": "2026-07-02", "car_fecsalida_hora": "09:00"},
    ]
    with patch.object(cdp, "get_data_planificada", return_value={}):
        cdp.aplicar(items)
    assert items[0]["car_fecsalida"] == "2026-07-01"
    assert items[1]["car_fecsalida"] == "2026-07-02"
    assert "car_fecsalida_es_planificada" not in items[0]


def test_aplicar_reemplaca_si_sortida_amb_planificada():
    import carrega_data_planificada as cdp
    items = [
        {"carrega_id": "2026/01/0002367", "car_estat": 2,
         "car_fecsalida": "2026-06-26", "car_fecsalida_hora": "09:39"},
    ]
    dt_planif = datetime(2026, 6, 25, 8, 0, 0)
    with patch.object(cdp, "get_data_planificada", return_value={"2026/01/0002367": dt_planif}):
        cdp.aplicar(items)
    assert items[0]["car_fecsalida"] == "2026-06-25"
    assert items[0]["car_fecsalida_hora"] == "08:00"
    assert items[0]["car_fecsalida_es_planificada"] is True


def test_aplicar_no_toca_sortida_sense_planificada():
    """Carrega Sortida sense snapshot/override (cas "pre-deploy"): no toquem."""
    import carrega_data_planificada as cdp
    items = [{"carrega_id": "2026/01/0002367", "car_estat": 2,
              "car_fecsalida": "2026-06-26", "car_fecsalida_hora": "09:39"}]
    with patch.object(cdp, "get_data_planificada", return_value={}):
        cdp.aplicar(items)
    assert items[0]["car_fecsalida"] == "2026-06-26"
    assert "car_fecsalida_es_planificada" not in items[0]


def test_upsert_snapshots_filtra_per_estat():
    """Nomes ha d'enviar a la BD els items amb car_estat != 2 i amb _car_fecsalida_raw."""
    import carrega_data_planificada as cdp
    items = [
        {"carrega_id": "2026/01/0000001", "car_estat": 0,
         "_car_fecsalida_raw": datetime(2026, 7, 1, 8, 0)},
        {"carrega_id": "2026/01/0000002", "car_estat": 1,
         "_car_fecsalida_raw": datetime(2026, 7, 2, 9, 0)},
        # Aquest NO ha d'anar (Sortida): el seu fecsalida ja esta sobreescrit
        {"carrega_id": "2026/01/0002367", "car_estat": 2,
         "_car_fecsalida_raw": datetime(2026, 6, 26, 9, 39)},
        # Aquest NO ha d'anar (manca raw): nul·les sense raw no es captura
        {"carrega_id": "2026/01/0000003", "car_estat": 0,
         "_car_fecsalida_raw": None},
    ]
    fake_cur = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    with patch.object(cdp.db, "get_conn", return_value=fake_conn):
        n = cdp.upsert_snapshots(items)
    assert n == 2, "Nomes 2 items haurien d'anar a la BD"
    # Comprova que executemany s'ha cridat amb 2 rows
    assert fake_cur.executemany.called
    args, _ = fake_cur.executemany.call_args
    rows = args[1]
    assert len(rows) == 2
    ids = [r[0] for r in rows]
    assert "2026/01/0000001" in ids
    assert "2026/01/0000002" in ids
    assert "2026/01/0002367" not in ids
    assert "2026/01/0000003" not in ids


def test_upsert_snapshots_resiste_excepcio_db():
    """Si la BD falla, retornem 0 i no propaguem l'excepcio."""
    import carrega_data_planificada as cdp
    items = [{"carrega_id": "2026/01/0000001", "car_estat": 0,
              "_car_fecsalida_raw": datetime(2026, 7, 1, 8, 0)}]
    with patch.object(cdp.db, "get_conn", side_effect=RuntimeError("BD caiguda")):
        n = cdp.upsert_snapshots(items)
    assert n == 0


def test_get_data_planificada_buit_si_no_ids():
    import carrega_data_planificada as cdp
    assert cdp.get_data_planificada([]) == {}
    assert cdp.get_data_planificada(["", None]) == {}  # type: ignore[list-item]


def test_get_data_planificada_resiste_excepcio_db():
    import carrega_data_planificada as cdp
    with patch.object(cdp.db, "fetch_all", side_effect=RuntimeError("BD caiguda")):
        assert cdp.get_data_planificada(["2026/01/0000001"]) == {}


def test_aplicar_no_fa_lookup_si_no_hi_ha_sortides():
    """Optimitzacio: si no hi ha cap item en estat Sortida, no consultem la BD."""
    import carrega_data_planificada as cdp
    items = [{"carrega_id": "2026/01/0000001", "car_estat": 0,
              "car_fecsalida": "2026-07-01"}]
    with patch.object(cdp, "get_data_planificada") as mock_lookup:
        cdp.aplicar(items)
    assert not mock_lookup.called, "No s'havia de fer lookup sense items Sortida"


def test_set_override_validacio():
    import carrega_data_planificada as cdp
    import pytest
    with pytest.raises(ValueError):
        cdp.set_override("", datetime(2026, 6, 25), None, 1)
    with pytest.raises(TypeError):
        cdp.set_override("2026/01/0002367", "2026-06-25", None, 1)  # type: ignore[arg-type]
