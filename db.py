"""Capa d'accés a PostgreSQL — pool de connexions i helpers.

Configuració via variables d'entorn (vegi `.env.example`):
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
    PG_POOL_MIN (default 1), PG_POOL_MAX (default 5).

Si `PG_HOST` no està definit, el pool no s'inicialitza — l'app pot funcionar
sense BD a nivells de import, però qualsevol accés llança un error explícit
("PG_HOST no està configurat al .env").
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("agrupacio.db")

_pool: ConnectionPool | None = None


def _conn_str() -> str:
    host = os.environ.get("PG_HOST")
    if not host:
        raise RuntimeError(
            "PG_HOST no està configurat. Defineix les variables PG_HOST, "
            "PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD al fitxer .env."
        )
    parts = [
        f"host={host}",
        f"port={os.environ.get('PG_PORT', '5432')}",
        f"dbname={os.environ.get('PG_DATABASE', 'agrupaciocarregues')}",
    ]
    if os.environ.get("PG_USER"):
        parts.append(f"user={os.environ['PG_USER']}")
    if os.environ.get("PG_PASSWORD"):
        parts.append(f"password={os.environ['PG_PASSWORD']}")
    # connect_timeout petit per fallar ràpid si la BD no respon
    parts.append("connect_timeout=5")
    return " ".join(parts)


def init_pool() -> ConnectionPool:
    """Inicialitza i retorna el pool global. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool
    min_size = int(os.environ.get("PG_POOL_MIN", "1"))
    max_size = int(os.environ.get("PG_POOL_MAX", "5"))
    _pool = ConnectionPool(
        conninfo=_conn_str(),
        min_size=min_size,
        max_size=max_size,
        timeout=10,
        kwargs={"row_factory": dict_row},
        open=True,
    )
    log.info("PostgreSQL pool obert (min=%d, max=%d)", min_size, max_size)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Context manager: agafa una connexió del pool, fa commit al final.

    Si hi ha alguna excepció, es fa rollback abans de retornar la connexió.
    """
    pool = init_pool()
    with pool.connection() as conn:
        yield conn


def execute(sql: str, params: tuple | dict | None = None) -> int:
    """Executa un INSERT/UPDATE/DELETE i retorna files afectades."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def health_ok() -> tuple[bool, str]:
    """Comprova que la BD respon. Retorna (ok, missatge)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True, ""
    except Exception as e:
        return False, str(e)[:200]
