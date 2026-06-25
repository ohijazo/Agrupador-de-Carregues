"""Tests d'agregador.agrupar — el flux que crida el motor d'embalatges.

Es mockeja `motor.calcular_embalatges` i `obtenir_comandes_carrega` perquè
els tests no requereixin DB ni l'app germana.
"""
import os
import sys
import types
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# --- Fake motor i models per evitar dependència de l'app germana --------
@dataclass
class FakeContingut:
    art_codi: str
    art_descrip: str = ""
    sacs: int = 0
    sacs_x_base: int = 0


@dataclass
class FakeEmbalatge:
    tipus_palet: str = "01030"
    sacs_x_base: int = 5
    max_sacs: int = 50
    es_embalatge_propi: bool = False
    contingut: list = field(default_factory=list)


@dataclass
class FakeLinia:
    art_codi: str
    art_descrip: str = ""
    tunitat: str = "S25"


@dataclass
class FakePaletResum:
    art_codi: str
    art_descrip: str = ""


@dataclass
class FakeEstat:
    value: str = "OK"


@dataclass
class FakeResultat:
    embalatges: list = field(default_factory=list)
    linies: list = field(default_factory=list)
    palets: list = field(default_factory=list)
    estat: object = field(default_factory=FakeEstat)


def _setup_fake_motor():
    """Injecta (o reutilitza) moduls 'motor' i 'models' fake.

    `agregador.agrupar` fa `from motor import calcular_embalatges` cada
    cop que s'executa, així que canviar l'atribut a sys.modules['motor']
    abans de cridar agrupar és suficient.
    """
    fake_motor = sys.modules.get("motor") or types.ModuleType("motor")
    sys.modules["motor"] = fake_motor
    fake_models = sys.modules.get("models") or types.ModuleType("models")
    fake_models.Estat = FakeEstat
    sys.modules["models"] = fake_models
    return fake_motor


# --- Helpers de fixture --------------------------------------------------
def _carrega(cid="2026/01/0000001", tra="TR1"):
    return {
        "carrega_id": cid,
        "eje_ejercicio": "2026",
        "sca_serie": "01",
        "car_numero": cid.split("/")[-1],
        "tra_codi": tra,
        "transportista": "Transportes Test",
        "car_fecsalida": "2026-06-12",
        "car_matricula": "1234ABC",
        "car_nomconductor": "Conductor",
        "car_observaciones": "",
        "car_descripcion": "Test",
    }


# --- Tests ---------------------------------------------------------------
def test_agrupar_amb_resultat_normal():
    """Una comanda torna 1 palet → resultat amb 1 producte i 1 palet físic."""
    fake_motor = _setup_fake_motor()
    fake_motor.calcular_embalatges = lambda sal, cpa, **kw: FakeResultat(
        embalatges=[FakeEmbalatge(contingut=[FakeContingut("ART1", "Article test", sacs=10, sacs_x_base=5)])],
        linies=[FakeLinia("ART1", "Article test", "S25")],
        palets=[FakePaletResum("01030", "Palet test")],
    )
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0000100", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        r = agrupar([_carrega()])
    assert len(r.productes) == 1
    assert r.productes[0].art_codi == "ART1"
    assert r.productes[0].total_sacs == 10
    assert r.total_palets_fisics == 1
    assert r.incidencies == []


def test_agrupar_motor_torna_none_no_peta():
    """Si calcular_embalatges retorna None, registra incidència i continua."""
    fake_motor = _setup_fake_motor()
    fake_motor.calcular_embalatges = lambda sal, cpa, **kw: None
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0000100", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        r = agrupar([_carrega()])
    assert r.productes == []
    assert len(r.incidencies) == 1
    assert r.incidencies[0].tipus == "warning"


def test_agrupar_motor_peta_amb_excepcio():
    """Excepció del motor → incidència 'error' i no peta tot el lot."""
    fake_motor = _setup_fake_motor()
    def boom(sal, cpa, **kw):
        raise RuntimeError("BD timeout")
    fake_motor.calcular_embalatges = boom
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0000100", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        r = agrupar([_carrega()])
    assert r.productes == []
    assert len(r.incidencies) == 1
    assert r.incidencies[0].tipus == "error"
    assert "BD timeout" in r.incidencies[0].missatge


def test_agrupar_carrega_sense_comandes():
    """Càrrega sense cap comanda a Detcargas → incidència warning."""
    _setup_fake_motor()
    with patch("agregador.obtenir_comandes_carrega", return_value=[]):
        from agregador import agrupar
        r = agrupar([_carrega()])
    assert r.productes == []
    assert len(r.incidencies) == 1
    assert "no té comandes" in r.incidencies[0].missatge


def test_agrupar_motor_torna_embalatges_buit():
    """Motor OK però sense embalatges → incidència warning."""
    fake_motor = _setup_fake_motor()
    fake_motor.calcular_embalatges = lambda sal, cpa, **kw: FakeResultat(embalatges=[])
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0000100", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        r = agrupar([_carrega()])
    assert r.productes == []
    assert len(r.incidencies) == 1
    assert r.incidencies[0].tipus == "warning"


def test_agrupar_cache_comanda_reutilitza_resultat():
    """La mateixa comanda compartida per 2 càrregues només es calcula 1 vegada."""
    fake_motor = _setup_fake_motor()
    crides = []
    def comptar(sal, cpa, **kw):
        crides.append((sal, cpa))
        return FakeResultat(
            embalatges=[FakeEmbalatge(contingut=[FakeContingut("ART1", sacs=5, sacs_x_base=5)])],
            linies=[FakeLinia("ART1", "T", "S25")],
            palets=[FakePaletResum("01030", "P")],
        )
    fake_motor.calcular_embalatges = comptar
    comanda = {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0000100", "det_tipo": "A"}
    with patch("agregador.obtenir_comandes_carrega", return_value=[comanda]):
        from agregador import agrupar
        agrupar([_carrega("2026/01/0000001"), _carrega("2026/01/0000002")])
    assert len(crides) == 1
