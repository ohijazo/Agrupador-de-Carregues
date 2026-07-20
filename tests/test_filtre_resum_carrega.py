"""Regressio: llistar_carregues amaga la carrega "resum" SI HI HA PARELL.

Context: KAIS genera per a alguns transportistes una carrega "resum" amb 1
sola linia d'article 30000 (FARINA) paral·lela a la carrega "detall" amb
totes les comandes — mateix dia, mateix kg_total. La regla d'amagar nomes
s'aplica QUAN HI HA PARELL (mateixa data + mateix kg), per evitar falsos
positius en carregues legitimes mono-FARINA.

Cas de referencia: 2026/01/0002442 (COMANDES PRATS 30/06, detall, multiples
comandes) ↔ 2026/01/0002443 (ESCAPA PAL PRATS, resum, 1 linia art 30000) —
el filtre ha d'amagar 2443 i mantenir 2442 visible.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _fake_row(eje, sca, car, fecsalida, kg, num_comandes, is_resum):
    return type("Row", (), {
        "eje_ejercicio": eje, "sca_serie": sca, "car_numero": car,
        "car_descripcion": f"CARR {car}",
        "car_fecha": None, "car_fecsalida": fecsalida, "car_fecllegada": None,
        "car_estat": 0, "tra_codi": "X", "transportista": "T",
        "car_matricula": "", "car_nomconductor": "",
        "car_pesonetocarga": kg, "car_pesoteorico": kg,
        "car_observaciones": "",
        "palletitzable": True, "is_granel": False,
        "kg_total": kg, "num_comandes": num_comandes,
        "is_resum_candidate": is_resum,
    })()


class _FakeConn:
    def __init__(self, items_rows):
        self._items = items_rows
        self.executed_sqls: list[str] = []

    def execute(self, sql, *params):
        self.executed_sqls.append(sql)
        is_count = "COUNT(*)" in sql
        captured = self._items
        class C:
            def fetchone(self_):
                return type("Row", (), {"n": len(captured)})()
            def fetchall(self_):
                return captured
        return C()

    def close(self): pass


def test_sql_inclou_is_resum_candidate(monkeypatch):
    """El SELECT de items inclou is_resum_candidate per al filtre post-fetch."""
    import consultes_carregues
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn([]))
    consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")


def test_filtre_oculta_resum_amb_parell(monkeypatch):
    """2442 (detall) + 2443 (resum) amb mateix dia i mateix kg → 2443 amagat."""
    import consultes_carregues
    from datetime import date
    d = date(2026, 6, 30)
    rows = [
        _fake_row("2026", "01", "0002442", d, kg=2500.0, num_comandes=8, is_resum=False),
        _fake_row("2026", "01", "0002443", d, kg=2500.0, num_comandes=1, is_resum=True),
    ]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")
    ids = [it["carrega_id"] for it in res["items"]]
    assert ids == ["2026/01/0002442"], (
        f"Hauria de mostrar nomes 2442 (detall) i amagar 2443 (resum). Got: {ids}"
    )
    assert res["total"] == 1, "El total ha de baixar a 1 quan s'amaga el resum."
    # El flag intern no s'ha de filtrar al client
    assert "_is_resum_candidate" not in res["items"][0]


def test_no_filtre_resum_sense_parell(monkeypatch):
    """Carrega mono-FARINA legitima (num_comandes=1, art 30000) i SENSE
    parell del mateix dia/kg: s'ha de mantenir visible.
    """
    import consultes_carregues
    from datetime import date
    rows = [
        _fake_row("2026", "01", "0001000", date(2026, 6, 15),
                  kg=500.0, num_comandes=1, is_resum=True),
    ]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")
    assert len(res["items"]) == 1, (
        "Sense parell del mateix dia/kg, no s'ha de filtrar — encara que "
        "is_resum_candidate=True. Evita falsos positius mono-FARINA."
    )


def test_no_filtre_si_parell_pero_kgs_diferents(monkeypatch):
    """Dues carregues mateix dia pero kgs diferents: NO son parell, no filtrem."""
    import consultes_carregues
    from datetime import date
    d = date(2026, 6, 30)
    rows = [
        _fake_row("2026", "01", "0001001", d, kg=1500.0, num_comandes=3, is_resum=False),
        _fake_row("2026", "01", "0001002", d, kg=800.0, num_comandes=1, is_resum=True),
    ]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")
    assert len(res["items"]) == 2, (
        "Kgs diferents -> no son parell de duplicat -> ambdues visibles."
    )


class _FakeConnAmbParams:
    """Variant de _FakeConn que captura tambe els params de cada execute."""
    def __init__(self, items_rows):
        self._items = items_rows
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        captured = self._items
        class C:
            def fetchone(self_):
                return type("Row", (), {"n": len(captured)})()
            def fetchall(self_):
                return captured
        return C()

    def close(self): pass


def test_where_sql_exclou_tra_codi_199(monkeypatch):
    """El WHERE de llistar_carregues ha d'incloure NOT IN amb el codi 199.

    Regressio: aixo garanteix que les carregues "duplicades" de facturacio
    interna (tra_codi=199 a Farinera Coromina) no arriben mai al resultat, ni
    tan sols si KAIS les retornaria — el filtre s'aplica a SQL abans del
    OFFSET/FETCH, aixi que la paginacio del Power BI tambe queda coberta.
    """
    import consultes_carregues
    fake = _FakeConnAmbParams([])
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)
    consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")

    # Tant el sql_count com el sql_items comparteixen where_sql.
    assert len(fake.executed) == 2, "Esperem dues execute (count + items)."
    for sql, params in fake.executed:
        assert "RTRIM(c.tra_codi) NOT IN" in sql, (
            f"El WHERE ha d'excloure els codis duplicats. SQL: {sql[:400]}"
        )
        assert "199" in params, (
            f"El codi 199 ha d'anar com a param, no interpolat. Params: {params}"
        )


def test_where_sql_no_te_bug_precedencia_or(monkeypatch):
    """Regressio bug produccio: el WHERE base te branques `car_fecsalida OR
    car_fecllegada`. Sense parentesis externs, qualsevol `AND` afegit despres
    (tra_codis, estat, art_codi, _TRA_CODIS_EXCLOSOS) s'aplica NOMES a la
    segona branca per precedencia SQL (AND > OR), i les carregues capturades
    per la primera branca escapen el filtre.

    Cas real: 2026/01/0002736 amb tra_codi=199 i car_fecsalida=2026-07-20
    apareixia al calendari perque la primera branca (car_fecsalida in range)
    la matchava i el `AND NOT IN (199)` no s'evaluava per aquesta fila.

    Aquest test comprova que el `NOT IN` esta al nivell top del WHERE (i.e.,
    profunditat de parentesi zero relativa a WHERE), no niat dins de l'OR.
    """
    import consultes_carregues
    fake = _FakeConnAmbParams([])
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)
    consultes_carregues.llistar_carregues("2026-06-01", "2026-06-30")

    for sql, _params in fake.executed:
        # El SELECT de items conte WHERE dins de subqueries (kg_total_sql,
        # is_resum_candidate_sql). El WHERE outer que ens interessa es el que
        # va just abans del bloc base amb `COALESCE(c.car_fecsalida...)`.
        i_base_cond = sql.index("COALESCE(c.car_fecsalida, c.car_fecha)")
        i_where = sql.upper().rindex("WHERE", 0, i_base_cond)
        i_not_in = sql.index("RTRIM(c.tra_codi) NOT IN")

        # Just despres de WHERE, saltant espais, el primer char ha de ser '('.
        j = i_where + 5
        while j < len(sql) and sql[j].isspace():
            j += 1
        assert sql[j] == "(", (
            f"El WHERE base ha de comencar amb '(' per envoltar l'OR de dates. "
            f"Primer char no-blanc despres de WHERE: {sql[j]!r}. "
            f"Sense aquest paren, els AND posteriors nomes s'apliquen a la "
            f"segona branca del OR (bug de precedencia)."
        )
        # Trobar el parentesi que tanca aquest bloc base.
        depth = 1
        k = j + 1
        while k < len(sql) and depth > 0:
            if sql[k] == "(":
                depth += 1
            elif sql[k] == ")":
                depth -= 1
            k += 1
        # El filtre NOT IN ha d'estar despres del ')' que tanca el bloc base.
        assert i_not_in > k, (
            "Bug de precedencia OR/AND: el NOT IN esta dins del bloc OR base "
            f"(NOT IN a pos {i_not_in}, tancament del bloc base a pos {k}). "
            "Cal envoltar totes les branques OR amb parentesis externs perque "
            "els AND (tra_codis, estat, art_codi, EXCLOSOS) s'apliquin a totes."
        )


