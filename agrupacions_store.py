"""Store d'agrupacions desat a PostgreSQL.

API pública mantinguda igual que la versió JSON anterior perquè els
endpoints Flask no hagin de canviar:

  guardar(nom, carregues, resultat, plantilla=False) -> dict (resum)
  llistar() -> list[dict]
  obtenir(id_) -> dict | None
  eliminar(id_) -> bool
  marca_producte(id_, art_codi, preparat, ip=None) -> dict | None
  reset_preparats(id_, ip=None) -> dict | None
  index_carregues_agrupades() -> dict[carrega_id, list[{id, nom, ts, finalitzada}]]
  llistar_plantilles() -> list[dict]

La concurrència es resol a nivell de PostgreSQL (MVCC + transaccions);
ja no cal file lock.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from threading import Lock

import psycopg

import db

_RE_ID = re.compile(r"^[a-f0-9-]{8,40}$")

# Cache de l'índex carrega_id -> [agrupacions]. Es recalcula quan canvia
# l'índex de versió a PG (vegi `bump_index_version`). Thread-safe.
_index_cache: dict[str, list[dict]] | None = None
_index_cache_version: int = -1
_index_lock = Lock()
_local_index_version = 0  # versió incrementada quan aquest procés escriu


def _invalidar_index() -> None:
    """Invalida el cache d'índex per al següent fetch."""
    global _local_index_version
    with _index_lock:
        _local_index_version += 1


def get_version() -> int:
    """Versió actual de l'índex d'agrupacions. Augmenta cada cop que es desa,
    elimina, marca o desmarca un producte preparat. El frontend pot fer
    polling d'aquest valor per detectar canvis sense haver de re-baixar
    la llista sencera."""
    with _index_lock:
        return _local_index_version


def _valida_id(id_: str) -> str:
    if not _RE_ID.fullmatch(id_):
        raise ValueError("id invàlid")
    return id_


# ---------------------------------------------------------------------------
# CRUD bàsic
# ---------------------------------------------------------------------------
def guardar(nom: str, carregues: list[dict], resultat: dict, plantilla: bool = False) -> dict:
    id_ = uuid.uuid4().hex
    nom = (nom or "").strip() or f"Agrupació {datetime.now().isoformat(timespec='seconds')}"
    nom = nom[:80]
    n_carregues = len(carregues or [])
    n_productes = len((resultat or {}).get("productes") or [])
    total_palets_fisics = int((resultat or {}).get("total_palets_fisics") or 0)
    total_sacs = int((resultat or {}).get("total_sacs") or 0)
    plantilla_meta = _calcular_plantilla_meta(carregues) if plantilla else None

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agrupacions
                    (id, nom, plantilla, n_carregues, n_productes,
                     total_palets_fisics, total_sacs,
                     carregues, resultat, plantilla_meta)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING ts
                """,
                (
                    id_, nom, plantilla, n_carregues, n_productes,
                    total_palets_fisics, total_sacs,
                    json.dumps(carregues), json.dumps(resultat),
                    json.dumps(plantilla_meta) if plantilla_meta else None,
                ),
            )
            ts_row = cur.fetchone()
            # Index desnormalitzat de càrregues
            if carregues:
                cur.executemany(
                    """
                    INSERT INTO agrupacio_carregues (agrupacio_id, carrega_id, tra_codi)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (id_, c.get("carrega_id"), (c.get("tra_codi") or "").strip() or None)
                        for c in carregues
                        if c.get("carrega_id")
                    ],
                )
    _invalidar_index()
    return {
        "id": id_,
        "nom": nom,
        "ts": _format_ts(ts_row["ts"] if ts_row else datetime.now()),
        "n_carregues": n_carregues,
        "n_productes": n_productes,
        "total_palets_fisics": total_palets_fisics,
        "total_sacs": total_sacs,
        "n_preparats": 0,
    }


def llistar() -> list[dict]:
    sql = """
        SELECT id, nom, ts, n_carregues, n_productes,
               total_palets_fisics, total_sacs,
               (SELECT COUNT(*) FROM productes_preparats p
                WHERE p.agrupacio_id = a.id) AS n_preparats
        FROM agrupacions a
        ORDER BY ts DESC
    """
    out = []
    for r in db.fetch_all(sql):
        out.append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "n_carregues": r["n_carregues"],
            "n_productes": r["n_productes"],
            "total_palets_fisics": r["total_palets_fisics"],
            "total_sacs": r["total_sacs"],
            "n_preparats": int(r["n_preparats"] or 0),
        })
    return out


def obtenir(id_: str) -> dict | None:
    try:
        _valida_id(id_)
    except ValueError:
        return None
    sql = """
        SELECT id, nom, ts, plantilla, carregues, resultat, plantilla_meta,
               (SELECT array_agg(art_codi ORDER BY art_codi)
                FROM productes_preparats p
                WHERE p.agrupacio_id = a.id) AS productes_preparats
        FROM agrupacions a
        WHERE id = %s
    """
    r = db.fetch_one(sql, (id_,))
    if not r:
        return None
    return {
        "id": _id_to_hex(r["id"]),
        "nom": r["nom"],
        "ts": _format_ts(r["ts"]),
        "plantilla": r["plantilla"],
        "carregues": r["carregues"] or [],
        "resultat": r["resultat"] or {},
        "plantilla_meta": r["plantilla_meta"],
        "productes_preparats": list(r["productes_preparats"] or []),
    }


def eliminar(id_: str) -> bool:
    try:
        _valida_id(id_)
    except ValueError:
        return False
    rows = db.execute("DELETE FROM agrupacions WHERE id = %s", (id_,))
    if rows:
        _invalidar_index()
        return True
    return False


# ---------------------------------------------------------------------------
# Productes preparats (magatzem)
# ---------------------------------------------------------------------------
def marca_producte(id_: str, art_codi: str, preparat: bool, ip: str | None = None) -> dict | None:
    try:
        _valida_id(id_)
    except ValueError:
        return None
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Comprovem que l'agrupació existeix abans de tocar res
            cur.execute("SELECT 1 FROM agrupacions WHERE id = %s", (id_,))
            if not cur.fetchone():
                return None
            if preparat:
                cur.execute(
                    """
                    INSERT INTO productes_preparats (agrupacio_id, art_codi, marcat_ip)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (agrupacio_id, art_codi) DO NOTHING
                    """,
                    (id_, art_codi, ip),
                )
            else:
                cur.execute(
                    "DELETE FROM productes_preparats WHERE agrupacio_id = %s AND art_codi = %s",
                    (id_, art_codi),
                )
    _invalidar_index()
    return obtenir(id_)


def reset_preparats(id_: str, ip: str | None = None) -> dict | None:
    try:
        _valida_id(id_)
    except ValueError:
        return None
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM agrupacions WHERE id = %s", (id_,))
            if not cur.fetchone():
                return None
            cur.execute("DELETE FROM productes_preparats WHERE agrupacio_id = %s", (id_,))
    _invalidar_index()
    return obtenir(id_)


# ---------------------------------------------------------------------------
# Índex carrega_id -> agrupacions actives/finalitzades
# ---------------------------------------------------------------------------
def index_carregues_agrupades() -> dict[str, list[dict]]:
    """Per a cada carrega_id, retorna les agrupacions on apareix."""
    global _index_cache, _index_cache_version
    with _index_lock:
        if _index_cache is not None and _index_cache_version == _local_index_version:
            return _index_cache

    sql = """
        SELECT ac.carrega_id, v.id, v.nom, v.ts, v.finalitzada,
               v.n_productes, v.n_preparats
        FROM agrupacio_carregues ac
        JOIN v_agrupacions_estat v ON v.id = ac.agrupacio_id
        ORDER BY v.ts DESC
    """
    index: dict[str, list[dict]] = {}
    for r in db.fetch_all(sql):
        index.setdefault(r["carrega_id"], []).append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "finalitzada": bool(r["finalitzada"]),
            "n_productes": int(r["n_productes"] or 0),
            "n_preparats": int(r["n_preparats"] or 0),
        })
    with _index_lock:
        _index_cache = index
        _index_cache_version = _local_index_version
    return index


# ---------------------------------------------------------------------------
# Plantilles
# ---------------------------------------------------------------------------
def _calcular_plantilla_meta(carregues: list[dict]) -> dict:
    """Extreu els atributs comuns d'una plantilla a partir de les seves càrregues."""
    transportistes: dict[str, str] = {}
    for c in carregues or []:
        tc = (c.get("tra_codi") or "").strip()
        if tc:
            transportistes.setdefault(tc, (c.get("transportista") or "").strip())
    return {
        "transportistes": [
            {"tra_codi": tc, "tra_nom": nm} for tc, nm in sorted(transportistes.items())
        ],
        "n_carregues_tipic": len(carregues or []),
    }


def llistar_plantilles() -> list[dict]:
    sql = """
        SELECT id, nom, ts, plantilla_meta, n_carregues
        FROM agrupacions
        WHERE plantilla = TRUE
        ORDER BY ts DESC
    """
    out = []
    for r in db.fetch_all(sql):
        meta = r["plantilla_meta"] or {}
        out.append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "transportistes": meta.get("transportistes", []),
            "n_carregues_tipic": meta.get("n_carregues_tipic", r["n_carregues"]),
        })
    return out


# ---------------------------------------------------------------------------
# Helpers de format (per mantenir compatibilitat amb la API existent)
# ---------------------------------------------------------------------------
def _id_to_hex(value) -> str:
    """psycopg torna UUID; el codi existing espera hex string."""
    if value is None:
        return ""
    if isinstance(value, uuid.UUID):
        return value.hex
    return str(value).replace("-", "")


def _format_ts(value) -> str:
    """Tornar timestamp en isoformat segons (sense microsegons) per compatibilitat."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


# Manté `_es_finalitzada` per compatibilitat amb tests antics que el cridessin
def _es_finalitzada(obj: dict) -> bool:
    n_prods = len((obj.get("resultat") or {}).get("productes") or [])
    n_prep = len(obj.get("productes_preparats") or [])
    return n_prods > 0 and n_prep >= n_prods
