"""Regressio: un pedido ('P') ja servit no s'ha de comptar dues vegades.

Context (Farinera Coromina, 2026-09): KAIS no esborra la comanda de Detcargas
quan la converteix en albara. Si la comanda i els seus albarans conviuen a la
mateixa carrega, l'app compta la mercaderia dos cops.

Cas de referencia reportat per un usuari des del calendari: carrega
2026/01/0003498 (ESCAPA-PAL-SALZADELA, tra 064). Detcargas hi te 3 files:

    2026 06 0000375  P   -> resol a sal=56  982 sacs  24.275 kg
    2026 06 0000389  A   -> resol a sal=06  939 sacs  23.200 kg
    2026 06 0000391  A   -> resol a sal=06   40 sacs   1.000 kg

Les linies dels dos albarans porten Lin_P_Serie='06' / Lin_P_Numero='0000375':
son la materialitzacio del pedido. El pedido te lin_unit_ser=979 = 939+40.
Abans del fix la carrega sortia amb 3 comandes i 48.475 kg (el doble).

El filtre viu al SQL (`_exclou_pedido_ja_servit_sql`) perque tots els
consumidors — calendari, llistat d'oficina, detall, agrupacio i Power BI —
quedin coberts en un sol lloc, igual que `_TRA_CODIS_EXCLOSOS`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Els blocs SQL de `llistar_carregues` que filtren per det_tipo IN ('A','P') i
# que per tant han de portar l'exclusio. L'alias es el de la fila Detcargas.
_ALIES_AMB_FILTRE = ["d", "d2", "d3", "d_rc", "d_rc0", "d_rc2"]

_NEEDS_KAIS = pytest.mark.skipif(
    not os.environ.get("SQL_USER"),
    reason="Cal SQL_USER configurat per a tests contra KAIS",
)


class _FakeConn:
    """Captura el SQL generat sense tocar la BD."""

    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed: list[str] = []

    def execute(self, sql, *params):
        self.executed.append(sql)
        captured = self._rows

        class C:
            def fetchone(self_):
                return type("Row", (), {"n": len(captured)})()

            def fetchall(self_):
                return captured

        return C()

    def close(self):
        pass


def _fila(eje="2026", sal="06", alb="0000375", tipo="P", servit=False):
    return type("Row", (), {
        "eje_doc": eje, "sal_codigo": sal, "cpa_albara": alb,
        "det_tipo": tipo, "det_ordencarga": 0, "pedido_servit": servit,
    })()


# --- Estructurals: el filtre esta a tots els blocs SQL ------------------------

def test_tots_els_blocs_de_llistar_carregues_exclouen_el_pedido_servit(monkeypatch):
    """Cada `det_tipo IN ('A','P')` de llistar_carregues ha d'anar seguit de
    l'exclusio. Si algu afegeix un bloc nou sense el filtre, aquest test peta.

    Comptem per alias: el bloc que filtra per `d2.det_tipo` ha de portar tambe
    un `NOT ( d2.det_tipo = 'P' AND EXISTS ...)`, i aixi per a cadascun.
    """
    import consultes_carregues
    fake = _FakeConn([])
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)
    # `art_codi` activa el bloc del filtre per article, que altrament no es genera.
    consultes_carregues.llistar_carregues("2026-09-01", "2026-09-30", art_codi="30000")

    sql = max(fake.executed, key=len)
    for alias in _ALIES_AMB_FILTRE:
        n_tipus = sql.count(alias + ".det_tipo      IN (")
        n_excl = sql.count("NOT ( " + alias + ".det_tipo = 'P'")
        assert n_tipus > 0, "No trobo cap bloc amb alias %s; s'ha renombrat?" % alias
        assert n_excl == n_tipus, (
            "L'alias %s te %d filtres det_tipo pero nomes %d exclusions de "
            "pedido servit. Tot bloc que llegeixi Detcargas ha de descartar "
            "els pedidos ja materialitzats en albarans." % (alias, n_tipus, n_excl)
        )


def test_exclusio_usa_el_vincle_lin_p_numero(monkeypatch):
    """El discriminador ha de ser Lin_P_Serie/Lin_P_Numero, no el numero de
    document ni cpa_estat: es l'unic camp que lliga l'albara al seu pedido."""
    import consultes_carregues
    fake = _FakeConn([])
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)
    consultes_carregues.llistar_carregues("2026-09-01", "2026-09-30")

    sql = max(fake.executed, key=len)
    assert "Lin_P_Numero" in sql and "Lin_P_Serie" in sql
    # La restriccio de serie evita enganxar linies d'un altre document amb el
    # mateix numero en una altra serie (mateix perill que a exists_granel_sql).
    assert "s_ps.sal_SerAlbDefPed" in sql, (
        "L'EXISTS ha de restringir la serie de les linies via SERIEALB."
    )


def test_obtenir_comandes_carrega_calcula_el_flag(monkeypatch):
    """El SELECT ha de retornar `pedido_servit` per poder filtrar i diagnosticar."""
    import consultes_carregues
    fake = _FakeConn([])
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: fake)
    consultes_carregues.obtenir_comandes_carrega("2026", "01", "0003498")

    sql = fake.executed[0]
    assert "AS pedido_servit" in sql
    assert "NOT ( d.det_tipo" not in sql, (
        "Aqui el filtre es fa en Python (cal el flag per al diagnostic), "
        "no amb un AND NOT al WHERE."
    )


# --- Comportament de obtenir_comandes_carrega --------------------------------

def test_descarta_els_pedidos_servits_per_defecte(monkeypatch):
    import consultes_carregues
    rows = [_fila(alb="0000375", tipo="P", servit=True),
            _fila(alb="0000389", tipo="A", servit=False),
            _fila(alb="0000391", tipo="A", servit=False)]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.obtenir_comandes_carrega("2026", "01", "0003498")
    assert [c["cpa_albara"] for c in res] == ["0000389", "0000391"]
    assert all(c["pedido_servit"] is False for c in res)


def test_incloure_pedidos_servits_els_mante_marcats(monkeypatch):
    """`debug_resolucio_sal` els necessita per explicar per que han desaparegut."""
    import consultes_carregues
    rows = [_fila(alb="0000375", tipo="P", servit=True),
            _fila(alb="0000389", tipo="A", servit=False)]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.obtenir_comandes_carrega(
        "2026", "01", "0003498", incloure_pedidos_servits=True
    )
    assert [c["cpa_albara"] for c in res] == ["0000375", "0000389"]
    assert res[0]["pedido_servit"] is True


def test_un_pedido_no_servit_es_mante(monkeypatch):
    """Cas de control: una comanda pendent legitima (sense albara a la carrega)
    no s'ha de perdre. P. ex. 2026/01/0003606 (COMANDES PRATS) son 10 'P'."""
    import consultes_carregues
    rows = [_fila(alb="0002641", tipo="P", servit=False),
            _fila(alb="0002650", tipo="P", servit=False)]
    monkeypatch.setattr(consultes_carregues, "connectar", lambda: _FakeConn(rows))

    res = consultes_carregues.obtenir_comandes_carrega("2026", "01", "0003606")
    assert len(res) == 2


# --- Integracio contra KAIS --------------------------------------------------

@_NEEDS_KAIS
def test_carrega_3498_no_duplica_kg():
    """El cas reportat: 3 documents / 48.475 kg -> 2 documents / 24.200 kg."""
    from consultes_carregues import resum_carrega
    r = resum_carrega("2026", "01", "0003498")
    assert len(r["comandes"]) == 2, [c["comanda"] for c in r["comandes"]]
    assert [c["det_tipo"] for c in r["comandes"]] == ["A", "A"]
    assert r["total_kg"] == 24200.0
    assert r["total_sacs"] == 979


@_NEEDS_KAIS
def test_carrega_amb_pedidos_legitims_no_canvia():
    """Control: 2026/01/0003606 son 10 comandes 'P' sense albara a la carrega."""
    from consultes_carregues import resum_carrega
    r = resum_carrega("2026", "01", "0003606")
    assert len(r["comandes"]) == 10
    assert r["total_kg"] == 8829.0
