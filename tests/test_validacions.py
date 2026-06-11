"""Tests del mòdul valida.py — verifica formats acceptats i errors retornats."""
import os
import sys
from datetime import date

# Permet importar des de l'arrel del repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from valida import (  # noqa: E402
    valida_codi,
    valida_data,
    valida_int,
    valida_llista_carregues,
    valida_rang_dates,
)


# ---- valida_data --------------------------------------------------------

def test_data_iso_ok():
    d, err = valida_data("2026-06-11", "desde")
    assert err is None
    assert d == date(2026, 6, 11)


def test_data_amb_barra_normalitzada():
    d, err = valida_data("2026/06/11", "desde")
    assert err is None
    assert d == date(2026, 6, 11)


def test_data_buida_es_error():
    d, err = valida_data("", "desde")
    assert d is None
    assert err and "obligatori" in err


def test_data_none_es_error():
    d, err = valida_data(None, "desde")
    assert d is None
    assert err is not None


def test_data_format_invalid():
    d, err = valida_data("11-06-2026", "desde")
    assert d is None
    assert err and "format" in err


def test_data_text_invalid():
    d, err = valida_data("xyz", "desde")
    assert d is None
    assert err is not None


# ---- valida_rang_dates --------------------------------------------------

def test_rang_ok():
    r, err = valida_rang_dates("2026-06-01", "2026-06-11")
    assert err is None
    assert r == (date(2026, 6, 1), date(2026, 6, 11))


def test_rang_invertit_es_error():
    r, err = valida_rang_dates("2026-06-11", "2026-06-01")
    assert r is None
    assert err and "rang" in err.lower()


def test_rang_mateixa_data_ok():
    r, err = valida_rang_dates("2026-06-11", "2026-06-11")
    assert err is None
    assert r is not None


def test_rang_propaga_error_desde():
    r, err = valida_rang_dates("invalid", "2026-06-11")
    assert r is None
    assert err is not None


# ---- valida_codi --------------------------------------------------------

def test_codi_alfanumeric_ok():
    v, err = valida_codi("ABC123", "tra_codi", max_len=5)
    # max_len=5, "ABC123" té 6 → error
    assert v is None and err is not None


def test_codi_max_len_respectat():
    v, err = valida_codi("ABC12", "tra_codi", max_len=5)
    assert err is None
    assert v == "ABC12"


def test_codi_opcional_buit_ok():
    v, err = valida_codi("", "tra_codi", obligatori=False)
    assert v is None and err is None


def test_codi_opcional_none_ok():
    v, err = valida_codi(None, "tra_codi", obligatori=False)
    assert v is None and err is None


def test_codi_obligatori_buit_es_error():
    v, err = valida_codi("", "eje", obligatori=True)
    assert v is None and err is not None


def test_codi_amb_caracters_invalids():
    v, err = valida_codi("ABC;DROP", "tra_codi", max_len=20)
    assert v is None
    assert err is not None


def test_codi_amb_guio_i_barra():
    v, err = valida_codi("A-B/C", "id", max_len=10)
    assert err is None
    assert v == "A-B/C"


# ---- valida_int ---------------------------------------------------------

def test_int_ok():
    n, err = valida_int("500", "limit", minim=1, maxim=1000)
    assert err is None and n == 500


def test_int_text_no_numeric():
    n, err = valida_int("abc", "limit")
    assert n is None and err is not None


def test_int_per_sota_minim():
    n, err = valida_int("0", "limit", minim=1)
    assert n is None and err and ">=" in err


def test_int_per_sobre_maxim():
    n, err = valida_int("2000", "limit", maxim=1000)
    assert n is None and err and "<=" in err


def test_int_zero_amb_minim_zero_ok():
    n, err = valida_int("0", "offset", minim=0)
    assert err is None and n == 0


# ---- valida_llista_carregues --------------------------------------------

def _fer_carrega(carrega_id="2026/01/0000001"):
    return {
        "eje_ejercicio": "2026",
        "sca_serie": "01",
        "car_numero": "0000001",
        "carrega_id": carrega_id,
    }


def test_llista_ok():
    items, err = valida_llista_carregues([_fer_carrega(), _fer_carrega("2026/01/0000002")])
    assert err is None
    assert items and len(items) == 2


def test_llista_no_es_llista():
    items, err = valida_llista_carregues({"x": 1})
    assert items is None and err is not None


def test_llista_buida_es_error():
    items, err = valida_llista_carregues([])
    assert items is None and err is not None


def test_llista_amb_element_no_dict():
    items, err = valida_llista_carregues([_fer_carrega(), "no és un dict"])
    assert items is None and err and "#2" in err


def test_llista_camp_obligatori_falta():
    bad = _fer_carrega()
    del bad["car_numero"]
    items, err = valida_llista_carregues([bad])
    assert items is None and err and "car_numero" in err


def test_llista_supera_maxim():
    items, err = valida_llista_carregues([_fer_carrega(f"2026/01/{i:07d}") for i in range(51)])
    assert items is None and err and "Màxim" in err
