"""Regressio: un pedido ('P') no s'ha de resoldre a l'albara homonim.

Cas Farinera Coromina 2026-11-09: carregues ESCAPA PAL PRATS
    2026/01/0004422 (dv 06/11)  A 2026 06 0000485 -> 06/0000485   6.059 kg
    2026/01/0004445 (dl 09/11)  P 2026 06 0000485 -> 56/0000485  16.436 kg
Les dues files CPALBARA (06 i 56) empaten en client, tra_codi i
cpa_fechaservir. El desempat per "sal directa" feia que el pedido de dilluns
agafes l'albara de divendres: carrega duplicada i kg erronis.

La sal directa de det_documento es la serie d'albarans; els pedidos viuen a
la serie de comandes mapejada per SERIEALB (56 -> 06).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from consultes_carregues import _ordre_resolucio_sal_sql


def _ordre():
    return _ordre_resolucio_sal_sql(
        tra_carrega="@tra", data_sortida="@s", data_ref="@r",
        det_tipo="d.det_tipo", sal_doc="d.sal_doc",
    )


def test_pedido_prefereix_serie_seriealb():
    sql = _ordre()
    assert "d.det_tipo = 'P' AND cp.sal_codigo <> d.sal_doc THEN 0" in sql


def test_albara_prefereix_serie_directa():
    sql = _ordre()
    assert "d.det_tipo <> 'P' AND cp.sal_codigo = d.sal_doc THEN 0" in sql


def test_no_queda_desempat_directe_incondicional():
    # El criteri antic (directe per a tothom) es el que causava el bug.
    assert "CASE WHEN cp.sal_codigo = d.sal_doc THEN 0 ELSE 1 END" not in _ordre()
