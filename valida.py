"""Validadors d'inputs per als endpoints HTTP.

Cada helper retorna `(valor, error)`. Si `error` no és None, el caller ha de respondre 400.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any


# Format de codi general: alfanumèric + alguns separadors. Configurable amb max_len.
_RE_CODI = re.compile(r"[A-Za-z0-9_\-./]+")


def valida_data(s: str | None, nom: str) -> tuple[date | None, str | None]:
    """Accepta YYYY-MM-DD o YYYY/MM/DD."""
    if not s:
        return None, f"'{nom}' és obligatori (format YYYY-MM-DD)."
    s = s.strip().replace("/", "-")
    try:
        return date.fromisoformat(s), None
    except ValueError:
        return None, f"'{nom}' ha de ser una data vàlida en format YYYY-MM-DD."


def valida_rang_dates(desde: str | None, fins: str | None) -> tuple[tuple[date, date] | None, str | None]:
    d, e = valida_data(desde, "desde")
    if e:
        return None, e
    f, e = valida_data(fins, "fins")
    if e:
        return None, e
    if d > f:
        return None, "El rang és incorrecte: 'desde' és posterior a 'fins'."
    return (d, f), None


def valida_codi(s: str | None, nom: str, max_len: int = 16, obligatori: bool = True) -> tuple[str | None, str | None]:
    if s is None or s == "":
        if obligatori:
            return None, f"'{nom}' és obligatori."
        return None, None
    s = s.strip()
    if len(s) > max_len or not _RE_CODI.fullmatch(s):
        return None, f"'{nom}' té un format invàlid."
    return s, None


def valida_int(v: Any, nom: str, minim: int | None = None, maxim: int | None = None) -> tuple[int | None, str | None]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None, f"'{nom}' ha de ser un enter."
    if minim is not None and n < minim:
        return None, f"'{nom}' ha de ser >= {minim}."
    if maxim is not None and n > maxim:
        return None, f"'{nom}' ha de ser <= {maxim}."
    return n, None


_CAMPS_CARREGA_OBLIGATORIS = ("eje_ejercicio", "sca_serie", "car_numero", "carrega_id")


def valida_llista_carregues(carregues: Any, maxim: int = 50) -> tuple[list[dict] | None, str | None]:
    if not isinstance(carregues, list):
        return None, "'carregues' ha de ser una llista."
    if not carregues:
        return None, "Cap càrrega seleccionada."
    if len(carregues) > maxim:
        return None, f"Màxim {maxim} càrregues per agrupació (actuals: {len(carregues)})."
    for i, c in enumerate(carregues):
        if not isinstance(c, dict):
            return None, f"La càrrega #{i+1} no és un objecte vàlid."
        for camp in _CAMPS_CARREGA_OBLIGATORIS:
            if not c.get(camp):
                return None, f"La càrrega #{i+1} no té el camp '{camp}'."
    return carregues, None
