"""Aplica una migracio SQL idempotent del directori db/migrations/.

Usage:
    sudo -u www-data /var/www/agrupacio-carregues/venv/bin/python \\
        /var/www/agrupacio-carregues/scripts/apply_migration.py 005

L'argument es el prefix numeric (es busca db/migrations/<num>_*.sql).
Les migracions han de ser idempotents (CREATE IF NOT EXISTS, DO blocks),
aixi es poden re-aplicar sense risc.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: apply_migration.py <numero>", file=sys.stderr)
        print("Exemple: apply_migration.py 005", file=sys.stderr)
        return 2
    num = sys.argv[1].strip()
    mig_dir = os.path.join(ROOT, "db", "migrations")
    if not os.path.isdir(mig_dir):
        print(f"ERROR: directori no trobat: {mig_dir}", file=sys.stderr)
        return 1
    matches = sorted(
        f for f in os.listdir(mig_dir)
        if f.startswith(f"{num}_") and f.endswith(".sql")
    )
    if not matches:
        print(f"ERROR: cap migracio amb prefix '{num}_' a {mig_dir}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"ERROR: multiples migracions amb prefix '{num}_': {matches}", file=sys.stderr)
        return 1
    path = os.path.join(mig_dir, matches[0])
    print(f"Aplicant {matches[0]} ...")
    with open(path, encoding="utf-8") as f:
        sql = f.read()

    # Carrega .env si existeix (mateix patro que consultes_carregues.py)
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"OK: {matches[0]} aplicada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
