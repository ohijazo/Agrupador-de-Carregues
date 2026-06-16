"""Fixtures compartides de pytest.

La majoria de tests del store i dels endpoints necessiten una BD PostgreSQL
de test. Si no hi ha `PG_HOST` definit a l'entorn, els tests es marquen com
`skip` automàticament.

Per executar els tests:
    1) Tenir un Postgres local
    2) Crear una BD `agrupaciocarregues_test` (separada de la real!)
    3) Aplicar `db/schema.sql`
    4) export PG_HOST=localhost PG_DATABASE=agrupaciocarregues_test PG_USER=... PG_PASSWORD=...
    5) pytest tests/
"""
from __future__ import annotations

import os
import sys

import pytest

# Permet importar des de l'arrel del repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


_NEEDS_PG = pytest.mark.skipif(
    not os.environ.get("PG_HOST"),
    reason="Cal PG_HOST configurat per a tests amb PostgreSQL"
)


@pytest.fixture
def store_tmp(monkeypatch):
    """Neteja les taules abans i després de cada test.

    Manté el nom 'store_tmp' per compatibilitat amb els tests existents,
    encara que ara no usa un directori tmp.
    """
    if not os.environ.get("PG_HOST"):
        pytest.skip("PG_HOST no configurat")
    import db
    import agrupacions_store

    # Reseteja el cache d'índex en memòria
    agrupacions_store._invalidar_index()

    # Buida les taules (CASCADE neteja les filles automàticament)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE agrupacions CASCADE")

    yield

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE agrupacions CASCADE")
    agrupacions_store._invalidar_index()


# Marca tot el mòdul tests/test_agrupacions_store i tests/test_endpoints com a NEEDS_PG
def pytest_collection_modifyitems(config, items):
    if os.environ.get("PG_HOST"):
        return
    needs_pg_modules = {"test_agrupacions_store", "test_endpoints", "test_csrf", "test_admin", "test_polling"}
    skip_marker = pytest.mark.skip(reason="PG_HOST no configurat")
    for item in items:
        module = item.module.__name__.rsplit(".", 1)[-1] if hasattr(item, "module") else ""
        if module in needs_pg_modules:
            item.add_marker(skip_marker)
