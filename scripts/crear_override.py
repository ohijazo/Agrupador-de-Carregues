"""Crea un override de data planificada per a una carrega via CLI.

Usage:
    sudo -u www-data /var/www/agrupacio-carregues/venv/bin/python \\
        /var/www/agrupacio-carregues/scripts/crear_override.py \\
        2026/01/0002367 2026-06-25 [HH:MM] [motiu]

Arguments:
    carrega_id   format YYYY/SS/NNNNNNN
    data         YYYY-MM-DD
    hora         HH:MM (opcional, default 08:00)
    motiu        text (opcional)

Pensat per a casos puntuals com el reportat 2026-06-29 (carrega 0002367),
on KAIS va sobreescriure car_fecsalida abans del deploy del snapshot.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    carrega_id = sys.argv[1].strip()
    data = sys.argv[2].strip()
    hora = sys.argv[3].strip() if len(sys.argv) > 3 else "08:00"
    motiu = " ".join(sys.argv[4:]).strip() if len(sys.argv) > 4 else (
        "Correccio manual: KAIS va sobreescriure car_fecsalida en passar a Sortida"
    )

    try:
        dt = datetime.strptime(f"{data} {hora}", "%Y-%m-%d %H:%M")
    except ValueError as e:
        print(f"ERROR format data/hora: {e}", file=sys.stderr)
        return 1

    # Carrega .env (mateix patro que apply_migration.py)
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    import carrega_data_planificada as cdp
    result = cdp.set_override(
        carrega_id=carrega_id,
        car_fecsalida=dt,
        motiu=motiu,
        created_by_id=None,
    )
    print(f"OK: {result['carrega_id']} -> {result['car_fecsalida']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
