"""Audit log a PostgreSQL: registre d'accions importants per a traçabilitat.

Cada `log()` insereix una fila a la taula `audit_logs`. Captura automàticament
la IP de la petició Flask actual (si n'hi ha) i, més endavant, l'usuari de la
sessió un cop la Phase D introdueixi autenticació.

Failure mode: si l'INSERT falla per qualsevol motiu (PG caigut, taula no
existeix, etc.) emetem un warning al log i seguim — l'acció principal (desar
una agrupació, marcar un producte) MAI ha de fallar per culpa de l'audit.
"""
from __future__ import annotations

import json
import logging

import db

log = logging.getLogger("agrupacio.audit")


def _request_context() -> tuple[str | None, int | None, str | None]:
    """Extreu IP, user_id, user_name de la petició Flask actual.
    Retorna (None, None, None) si no estem dins d'una petició HTTP.
    """
    try:
        from flask import request, session
    except Exception:
        return None, None, None
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr) or None
        if ip and "," in ip:
            ip = ip.split(",", 1)[0].strip()
        user_id = session.get("user_id") if session else None
        user_name = session.get("user_name") if session else None
        return ip, user_id, user_name
    except Exception:
        return None, None, None


def log(accio: str, target: str | None = None, detall: dict | None = None) -> None:
    """Insereix una fila a `audit_logs`. No llança mai excepcions."""
    if not accio:
        return
    ip, user_id, user_name = _request_context()
    try:
        db.execute(
            """
            INSERT INTO audit_logs (user_id, user_name, ip, accio, target, detall)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                user_name,
                ip,
                accio,
                target,
                json.dumps(detall) if detall is not None else None,
            ),
        )
    except Exception as e:
        log.warning("audit.log fallit (accio=%s, target=%s): %s", accio, target, str(e)[:200])
