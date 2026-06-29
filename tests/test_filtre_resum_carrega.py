"""Regressio: el SQL de llistar_carregues exclou les carregues "resum".

Context: KAIS genera per a alguns transportistes una carrega "resum" amb 1
sola linia d'article 30000 (FARINA) paral·lela a la carrega "detall" amb
totes les comandes. Els operaris no l'han de veure ni al calendari ni a
l'agrupador. Si algu reverteix aquest filtre, aquest test ha de fallar
immediatament.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class _FakeCursor:
    """Simula pyodbc cursor amb fetchone/fetchall buits."""

    def __init__(self, kind):
        self._kind = kind

    def fetchone(self):
        # Pyodbc retorna una Row amb atributs accessibles per nom.
        # Per al COUNT(*) cal `.n`. Per als items, no cridem fetchone aqui.
        return type("Row", (), {"n": 0})()

    def fetchall(self):
        return []


class _FakeConn:
    """Captura les SQL strings que llistar_carregues executa."""

    def __init__(self):
        self.executed_sqls: list[str] = []

    def execute(self, sql, *params):
        self.executed_sqls.append(sql)
        # Distingim count vs items pel substring "COUNT(*)"
        kind = "count" if "COUNT(*)" in sql else "items"
        return _FakeCursor(kind)

    def close(self):
        pass


def test_llistar_carregues_exclou_resum_30000(monkeypatch):
    import consultes_carregues

    fake = _FakeConn()
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)

    result = consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")

    # Han d'haver-se executat el count i la query d'items.
    assert len(fake.executed_sqls) >= 2

    # Comprovacio semantica: el SQL ha de contenir les dues branques del
    # filtre (positiva: hi ha art=30000; negativa: no hi ha art<>30000).
    # La sintaxi exacta (NOT EXISTS adjacents) pot variar amb refactors;
    # comprovem nomes el contingut clau.
    assert any("= '30000'" in sql for sql in fake.executed_sqls), (
        "Falta la branca positiva del filtre resum (art_codi = '30000'). "
        "Aixo torna a mostrar el duplicat del transportista. Reaplica el filtre."
    )
    assert any("<> '30000'" in sql for sql in fake.executed_sqls), (
        "Falta la branca negativa del filtre resum (art_codi <> '30000'). "
        "Sense aquesta, també s'excluirien carregues legitimes amb art 30000."
    )
    # Sense la resolucio CPALBARA+SERIEALB, el filtre no troba la linia
    # 30000 quan viu en una serie diferent (cas habitual al ERP).
    assert any("SERIEALB" in sql and "art_codi" in sql.split("SERIEALB", 1)[1]
               for sql in fake.executed_sqls), (
        "El filtre resum no usa la resolucio CPALBARA+SERIEALB: pot perdre "
        "la linia 30000 quan viu en una serie diferent. Cas detectat el 2026-06-29."
    )

    assert result["items"] == []
    assert result["total"] == 0
