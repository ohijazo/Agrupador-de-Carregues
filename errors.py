"""Helpers per a respostes HTTP d'error estandarditzades.

Aquest mòdul desacobla els helpers d'errors de `app.py` perquè es puguin
reutilitzar des d'altres mòduls (admin routes, PBI routes, etc.) sense
imports circulars amb el `app` Flask.
"""
from __future__ import annotations

from flask import jsonify


def err_validacio(msg: str):
    """400: error de validació d'entrada."""
    return jsonify({"error": msg}), 400


def err_db():
    """503: error de connexió amb la base de dades (SQL Server o PG)."""
    return jsonify({"error": "Error de connexió amb la base de dades. Torna-ho a provar."}), 503


def err_motor():
    """503: el motor d'embalatges (app germana) no és disponible."""
    return jsonify({"error": "El motor d'embalatges no està disponible. Contacta amb administració."}), 503


def err_generic():
    """500: error genèric. El detall queda al log, mai s'exposa al client."""
    return jsonify({"error": "S'ha produït un error inesperat."}), 500
