"""Migra les agrupacions guardades a `data/agrupacions/*.json` a PostgreSQL.

Ús:
    python migrate_json_to_pg.py
    python migrate_json_to_pg.py --dry-run   # només mostra el que faria
    python migrate_json_to_pg.py --backup    # mou els JSON a data/agrupacions/_migrated/

Requereix que el `.env` tingui les variables PG_* configurades i que el
schema (db/schema.sql) ja s'hagi aplicat a la BD.

Idempotent: si un id ja existeix a la taula, salta. Així es pot tornar a
executar sense duplicar.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

# Windows: força UTF-8 a la consola perquè els ✓ ✗ → no peten amb cp1252
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except OSError:
            pass

# Carrega .env abans d'importar `db`
_HERE = os.path.dirname(os.path.abspath(__file__))


def _carregar_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_carregar_env(os.path.join(_HERE, ".env"))


import db  # noqa: E402


_DIR_DEFAULT = os.path.join(_HERE, "data", "agrupacions")
_DIR_BACKUP = os.path.join(_HERE, "data", "agrupacions", "_migrated")


def _carregar_jsons(dir_: str) -> list[dict]:
    out = []
    if not os.path.isdir(dir_):
        return out
    for fname in sorted(os.listdir(dir_)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(dir_, fname)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
            obj["_fname"] = fname
            obj["_path"] = path
            out.append(obj)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ⚠ Saltant {fname}: {e}", file=sys.stderr)
    return out


def _migrar_un(conn, obj: dict, dry_run: bool) -> str:
    """Insereix una agrupació amb les seves productes_preparats i agrupacio_carregues.

    Retorna: 'inserted', 'skipped' o 'error'.
    """
    id_ = obj.get("id")
    if not id_:
        return "error"
    nom = (obj.get("nom") or "").strip()[:80]
    ts_raw = obj.get("ts")
    try:
        ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now()
    except ValueError:
        ts = datetime.now()
    plantilla = bool(obj.get("plantilla"))
    plantilla_meta = obj.get("plantilla_meta")
    carregues = obj.get("carregues") or []
    resultat = obj.get("resultat") or {}
    productes_prep = obj.get("productes_preparats") or []
    n_carregues = len(carregues)
    n_productes = len((resultat or {}).get("productes") or [])
    total_palets_fisics = int(resultat.get("total_palets_fisics") or 0)
    total_sacs = int(resultat.get("total_sacs") or 0)

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM agrupacions WHERE id = %s", (id_,))
        if cur.fetchone():
            return "skipped"
        if dry_run:
            return "inserted"
        cur.execute(
            """
            INSERT INTO agrupacions
                (id, nom, ts, plantilla,
                 n_carregues, n_productes, total_palets_fisics, total_sacs,
                 carregues, resultat, plantilla_meta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id_, nom, ts, plantilla,
                n_carregues, n_productes, total_palets_fisics, total_sacs,
                json.dumps(carregues), json.dumps(resultat),
                json.dumps(plantilla_meta) if plantilla_meta else None,
            ),
        )
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
        if productes_prep:
            cur.executemany(
                """
                INSERT INTO productes_preparats (agrupacio_id, art_codi, marcat_ts)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [(id_, art, ts) for art in productes_prep],
            )
    return "inserted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=_DIR_DEFAULT, help="Directori amb els JSON")
    parser.add_argument("--dry-run", action="store_true", help="No insereix, només mostra")
    parser.add_argument("--backup", action="store_true",
                        help="Mou els JSON a data/agrupacions/_migrated/ després")
    args = parser.parse_args()

    objs = _carregar_jsons(args.dir)
    if not objs:
        print(f"No hi ha JSON a {args.dir}. Res a fer.")
        return 0

    print(f"Trobades {len(objs)} agrupacions a {args.dir}")
    if args.dry_run:
        print("  (DRY RUN — no s'inserirà res)")

    n_ins = n_skip = n_err = 0
    with db.get_conn() as conn:
        for obj in objs:
            try:
                res = _migrar_un(conn, obj, dry_run=args.dry_run)
            except Exception as e:
                print(f"  ❌ {obj['_fname']}: {e}", file=sys.stderr)
                n_err += 1
                continue
            print(f"  {'✓' if res == 'inserted' else '·'} {obj['_fname']} → {res}")
            if res == "inserted":
                n_ins += 1
            elif res == "skipped":
                n_skip += 1

    print(f"\nResum: {n_ins} insertades, {n_skip} saltades (ja hi eren), {n_err} amb error")

    if args.backup and n_ins > 0 and not args.dry_run:
        os.makedirs(_DIR_BACKUP, exist_ok=True)
        for obj in objs:
            try:
                if obj.get("_path"):
                    shutil.move(obj["_path"], os.path.join(_DIR_BACKUP, obj["_fname"]))
            except OSError as e:
                print(f"  ⚠ no s'ha pogut moure {obj['_fname']}: {e}", file=sys.stderr)
        print(f"Fitxers JSON moguts a {_DIR_BACKUP}")

    db.close_pool()
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
