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

    # AL MENYS UNA SQL ha de contenir el filtre que NEGA els resums.
    # La regla és: hi ha línia amb art 30000 AND no hi ha línia amb altre art.
    has_clausula_30000 = any(
        "art_codi" in sql and "'30000'" in sql and "NOT EXISTS" in sql
        for sql in fake.executed_sqls
    )
    assert has_clausula_30000, (
        "ATENCIO: el filtre de carrega 'resum' (art_codi=30000) s'ha eliminat "
        "del WHERE de llistar_carregues. Aixo torna a mostrar el duplicat del "
        "transportista. Reaplica el filtre."
    )

    # Verificació explicita per ambdues vessants (positiva i negativa).
    assert any("= '30000'" in sql for sql in fake.executed_sqls), \
        "Falta la branca positiva (alguna línia és art 30000)"
    assert any("<> '30000'" in sql for sql in fake.executed_sqls), \
        "Falta la branca negativa (cap línia és art != 30000)"

    assert result["items"] == []
    assert result["total"] == 0
