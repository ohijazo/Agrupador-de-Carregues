"""Regression del bug 28/06/2026: l'agregador passa `data_carrega` com a string.

`consultes_carregues.py` serialitza les dates de carrega amb `strftime` (línies
349-353), per tant l'agregador rep i propaga la data com a string. Aquests
tests verifiquen el contracte: el motor REP `data_carrega` com a string i
l'agregador no genera incidències amb missatges com "'str' object has no
attribute 'isoformat'" o "AttributeError".

Si algú revertís el fix a `preparacioComandesVenda/consultes.py:365`, el test
`test_agregador_no_genera_incidencia_isoformat` fallaria immediatament.
"""
import os
import sys
import types
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@dataclass
class FakeEstat:
    value: str = "OK"


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
class FakeResultat:
    embalatges: list = field(default_factory=list)
    linies: list = field(default_factory=list)
    palets: list = field(default_factory=list)
    estat: object = field(default_factory=FakeEstat)


def _setup_fake_motor():
    fake_motor = sys.modules.get("motor") or types.ModuleType("motor")
    sys.modules["motor"] = fake_motor
    fake_models = sys.modules.get("models") or types.ModuleType("models")
    fake_models.Estat = FakeEstat
    sys.modules["models"] = fake_models
    return fake_motor


def _carrega_amb_data(cid="2026/01/0002458", car_fecllegada="2026-06-28"):
    """Càrrega tal com la retorna `consultes_carregues.llistar_carregues()`:
    `car_fecllegada` és STRING (strftime '%Y-%m-%d'), no datetime.date.
    """
    return {
        "carrega_id": cid,
        "eje_ejercicio": "2026",
        "sca_serie": "01",
        "car_numero": cid.split("/")[-1],
        "tra_codi": "URBAN",
        "transportista": "URBAN SPICES",
        "car_fecha": "2026-06-28",
        "car_fecsalida": "2026-06-28",
        "car_fecllegada": car_fecllegada,
        "car_matricula": "1234ABC",
        "car_nomconductor": "Conductor",
        "car_observaciones": "",
        "car_descripcion": "Test",
    }


def test_motor_rep_data_carrega_com_a_string():
    """L'agregador propaga `car_fecllegada` (string) al motor sense convertir-lo."""
    fake_motor = _setup_fake_motor()
    crides = []

    def spy(sal, cpa, **kw):
        crides.append(kw)
        return FakeResultat(
            embalatges=[FakeEmbalatge(contingut=[FakeContingut("ART1", sacs=10, sacs_x_base=5)])],
            linies=[FakeLinia("ART1", "Test", "S25")],
            palets=[FakePaletResum("01030", "Palet")],
        )

    fake_motor.calcular_embalatges = spy
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0004790", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        agrupar([_carrega_amb_data(car_fecllegada="2026-06-28")])

    assert len(crides) == 1
    assert crides[0]["data_carrega"] == "2026-06-28"
    assert isinstance(crides[0]["data_carrega"], str)


def test_agregador_no_genera_incidencia_isoformat():
    """Test cor de la regressió: si un motor antic peta amb AttributeError,
    l'agregador NO ha de generar una incidència silenciosa.

    Aquest test passaria si el motor real està arreglat (cas actual). Si el bug
    torna, agreguem un assert explícit per fer-ho saltar amb missatge clar.
    """
    fake_motor = _setup_fake_motor()
    fake_motor.calcular_embalatges = lambda sal, cpa, **kw: FakeResultat(
        embalatges=[FakeEmbalatge(contingut=[FakeContingut("ART1", sacs=5, sacs_x_base=5)])],
        linies=[FakeLinia("ART1", "T", "S25")],
        palets=[FakePaletResum("01030", "P")],
    )
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0004790", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        resultat = agrupar([_carrega_amb_data()])

    incidencies_error = [i for i in resultat.incidencies if i.tipus == "error"]
    assert incidencies_error == [], f"Incidencies inesperades: {incidencies_error}"

    # Vigilància explícita pel patró de l'AttributeError del 28/06
    for inc in resultat.incidencies:
        assert "isoformat" not in inc.missatge, \
            f"Bug del 28/06 reaparegut: {inc.missatge}"
        assert "AttributeError" not in inc.missatge, \
            f"Bug del 28/06 reaparegut: {inc.missatge}"


def test_bug_codi_es_propaga_no_es_amaga_com_incidencia():
    """Política Capa 6: bugs de codi (TypeError/AttributeError/...) NO es poden
    amagar com a incidència silenciosa. L'endpoint ha de petar perquè es vegi
    al log immediatament. Si això hagués estat actiu el 28/06 al motor, el
    bug no hauria arribat a l'operari de matí.
    """
    fake_motor = _setup_fake_motor()

    def motor_amb_bug_de_codi(sal, cpa, **kw):
        raise AttributeError("'str' object has no attribute 'isoformat'")

    fake_motor.calcular_embalatges = motor_amb_bug_de_codi
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0004790", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        with pytest.raises(AttributeError, match="isoformat"):
            agrupar([_carrega_amb_data()])


def test_error_de_dades_segueix_donant_incidencia():
    """Política Capa 6: errors de dades (ValueError, BD, etc.) SÍ segueixen
    sent incidències per no trencar tot el lot per una comanda.
    """
    fake_motor = _setup_fake_motor()

    def motor_error_dades(sal, cpa, **kw):
        raise ValueError("Comanda 01/0004790 no trobada")

    fake_motor.calcular_embalatges = motor_error_dades
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0004790", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        # NO ha de petar; ha de registrar incidència i continuar
        resultat = agrupar([_carrega_amb_data()])
    assert len(resultat.incidencies) == 1
    assert resultat.incidencies[0].tipus == "error"
    assert "no trobada" in resultat.incidencies[0].missatge


def test_data_carrega_cae_a_car_fecsalida_quan_no_hi_ha_fecllegada():
    """Si car_fecllegada és None, l'agregador agafa car_fecsalida com a string."""
    fake_motor = _setup_fake_motor()
    crides = []
    fake_motor.calcular_embalatges = lambda sal, cpa, **kw: (
        crides.append(kw) or FakeResultat(
            embalatges=[FakeEmbalatge(contingut=[FakeContingut("ART1", sacs=1, sacs_x_base=5)])],
            linies=[FakeLinia("ART1", "T", "S25")],
            palets=[FakePaletResum("01030", "P")],
        )
    )
    carrega = _carrega_amb_data(car_fecllegada=None)
    carrega["car_fecsalida"] = "2026-06-27"
    with patch("agregador.obtenir_comandes_carrega", return_value=[
        {"eje_ejercicio": "2026", "sal_codigo": "01", "cpa_albara": "0004790", "det_tipo": "A"}
    ]):
        from agregador import agrupar
        agrupar([carrega])

    assert crides[0]["data_carrega"] == "2026-06-27"
