"""Data planificada de càrrega: protecció contra la sobreescriptura de KAIS.

Context: quan un operari canvia l'estat d'una càrrega a "Sortida" (car_estat=2),
KAIS sobreescriu `car_fecsalida` amb la data/hora exactes del canvi d'estat.
Això fa que la càrrega "salti" de dia al calendari (bug reportat 2026-06-29).

Solució: dues taules locals a PostgreSQL.
  - `kais_carrega_snapshot`: captura automàtica de `car_fecsalida` la primera
    vegada que veiem la càrrega amb `car_estat != 2`. S'actualitza mentre
    l'estat segueix sent != 2.
  - `kais_carrega_override`: override manual (admin) per a casos en què el
    snapshot no es va captar a temps.

Lookup precedència: override > snapshot > valor live de KAIS.

API:
    upsert_snapshots(items)              — bulk upsert dels que estan != Sortida
    get_data_planificada(carrega_ids)    — bulk lookup, retorna {id: datetime}
    aplicar(items)                       — modifica items in-place
    set_override(carrega_id, dt, motiu)  — admin only
    delete_override(carrega_id)          — admin only
    llistar_overrides()                  — admin UI
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import db

log = logging.getLogger("agrupacio.data_planificada")

CAR_ESTAT_SORTIDA = 2


def _carrega_id(item: dict) -> str:
    return item.get("carrega_id") or (
        f"{item.get('eje_ejercicio')}/{item.get('sca_serie')}/{item.get('car_numero')}"
    )


def upsert_snapshots(items: Iterable[dict]) -> int:
    """Per a cada item amb car_estat != Sortida i car_fecsalida no null,
    fa upsert (insert o actualitzacio) del snapshot. Silencia errors de BD
    per evitar trencar el llistat principal si Postgres està caigut.

    Retorna el nombre d'items processats (no necessariament els que han
    insertat — depèn de l'ON CONFLICT).
    """
    rows: list[tuple[str, datetime, int]] = []
    for it in items:
        estat = it.get("car_estat")
        if estat is None or int(estat) == CAR_ESTAT_SORTIDA:
            continue
        fec = it.get("_car_fecsalida_raw")
        if fec is None:
            continue
        rows.append((_carrega_id(it), fec, int(estat)))
    if not rows:
        return 0
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO kais_carrega_snapshot
                        (carrega_id, car_fecsalida_original, car_estat_snapshot)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (carrega_id) DO UPDATE
                       SET car_fecsalida_original = EXCLUDED.car_fecsalida_original,
                           car_estat_snapshot     = EXCLUDED.car_estat_snapshot,
                           updated_at             = NOW()
                    """,
                    rows,
                )
        return len(rows)
    except Exception:
        log.exception("upsert_snapshots fallit (no bloqueja el llistat)")
        return 0


def get_data_planificada(carrega_ids: Iterable[str]) -> dict[str, datetime]:
    """Per als IDs donats, retorna la millor data planificada disponible.
    Precedència: override > snapshot. Si no n'hi ha cap, l'ID no apareix
    al diccionari retornat (el caller manté el valor live de KAIS).
    """
    ids = list({i for i in carrega_ids if i})
    if not ids:
        return {}
    try:
        # Query unica amb LEFT JOIN/UNION per agafar tots dos sources d'un cop
        rows = db.fetch_all(
            """
            SELECT s.carrega_id,
                   COALESCE(o.car_fecsalida_override, s.car_fecsalida_original) AS dt
            FROM   kais_carrega_snapshot s
            LEFT JOIN kais_carrega_override o ON o.carrega_id = s.carrega_id
            WHERE  s.carrega_id = ANY(%s)
            UNION
            SELECT o.carrega_id, o.car_fecsalida_override AS dt
            FROM   kais_carrega_override o
            WHERE  o.carrega_id = ANY(%s)
              AND  NOT EXISTS (
                  SELECT 1 FROM kais_carrega_snapshot s
                  WHERE s.carrega_id = o.carrega_id
              )
            """,
            (ids, ids),
        )
        return {r["carrega_id"]: r["dt"] for r in rows}
    except Exception:
        log.exception("get_data_planificada fallit (caiem al valor live KAIS)")
        return {}


def aplicar(items: list[dict]) -> None:
    """Modifica `items` in-place: per als que estan en estat Sortida (2) i
    tenen un override/snapshot, reemplaça `car_fecsalida` (i la hora) pel
    valor planificat. Afegeix `car_fecsalida_es_planificada=True` per al
    frontend si vol diferenciar-ho visualment.

    Els no-Sortida no es toquen — el seu `car_fecsalida` ja és el planificat
    de KAIS.
    """
    if not items:
        return
    ids_sortida = [
        _carrega_id(it) for it in items
        if it.get("car_estat") is not None and int(it["car_estat"]) == CAR_ESTAT_SORTIDA
    ]
    if not ids_sortida:
        return
    planif = get_data_planificada(ids_sortida)
    if not planif:
        return
    for it in items:
        if it.get("car_estat") is None or int(it["car_estat"]) != CAR_ESTAT_SORTIDA:
            continue
        cid = _carrega_id(it)
        dt = planif.get(cid)
        if dt is None:
            continue
        it["car_fecsalida"] = dt.strftime("%Y-%m-%d")
        it["car_fecsalida_hora"] = dt.strftime("%H:%M")
        it["car_fecsalida_es_planificada"] = True


# --------------------------------------------------------------------------
# Override manual (admin)
# --------------------------------------------------------------------------
def set_override(
    carrega_id: str,
    car_fecsalida: datetime,
    motiu: str | None,
    created_by_id: int | None,
) -> dict:
    """Crea o actualitza un override per a la càrrega. Retorna la fila."""
    if not carrega_id:
        raise ValueError("carrega_id buit")
    if not isinstance(car_fecsalida, datetime):
        raise TypeError("car_fecsalida ha de ser datetime")
    row = db.fetch_one(
        """
        INSERT INTO kais_carrega_override
            (carrega_id, car_fecsalida_override, motiu, created_by_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (carrega_id) DO UPDATE
           SET car_fecsalida_override = EXCLUDED.car_fecsalida_override,
               motiu                  = EXCLUDED.motiu,
               updated_at             = NOW(),
               created_by_id          = EXCLUDED.created_by_id
        RETURNING carrega_id, car_fecsalida_override, motiu, updated_at
        """,
        (carrega_id, car_fecsalida, motiu, created_by_id),
    )
    if not row:
        raise RuntimeError("override upsert no ha retornat fila")
    return _serialitzar_override(row)


def delete_override(carrega_id: str) -> bool:
    if not carrega_id:
        return False
    n = db.execute(
        "DELETE FROM kais_carrega_override WHERE carrega_id = %s",
        (carrega_id,),
    )
    return n > 0


def llistar_overrides() -> list[dict]:
    rows = db.fetch_all(
        """
        SELECT o.carrega_id, o.car_fecsalida_override, o.motiu,
               o.updated_at, o.created_at,
               u.username AS created_by_username,
               u.nom      AS created_by_nom
        FROM   kais_carrega_override o
        LEFT JOIN usuaris u ON u.id = o.created_by_id
        ORDER  BY o.updated_at DESC
        """
    )
    return [_serialitzar_override(r) for r in rows]


def get_override(carrega_id: str) -> dict | None:
    row = db.fetch_one(
        """
        SELECT o.carrega_id, o.car_fecsalida_override, o.motiu,
               o.updated_at, o.created_at,
               u.username AS created_by_username,
               u.nom      AS created_by_nom
        FROM   kais_carrega_override o
        LEFT JOIN usuaris u ON u.id = o.created_by_id
        WHERE  o.carrega_id = %s
        """,
        (carrega_id,),
    )
    return _serialitzar_override(row) if row else None


def _serialitzar_override(row: dict) -> dict:
    dt = row.get("car_fecsalida_override")
    updated_at = row.get("updated_at")
    created_at = row.get("created_at")
    return {
        "carrega_id": row["carrega_id"],
        "car_fecsalida": dt.strftime("%Y-%m-%d %H:%M") if dt else None,
        "motiu": row.get("motiu"),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "created_by_username": row.get("created_by_username"),
        "created_by_nom": row.get("created_by_nom"),
    }
