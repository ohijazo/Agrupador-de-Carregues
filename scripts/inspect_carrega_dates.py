"""Dump totes les columnes de tipus data de la taula Cargas per a una
carrega concreta. Util per diagnosticar quin camp de KAIS conserva la
data planificada quan KAIS sobreescriu car_fecsalida al canvi d'estat.

Usage:
    sudo -u www-data /var/www/agrupacio-carregues/venv/bin/python \\
        /var/www/agrupacio-carregues/scripts/inspect_carrega_dates.py 0002367

Per defecte assumeix ejercici=2026, serie=01. Si cal, passa-ho com a
arguments addicionals:
    python inspect_carrega_dates.py 0002367 2026 01
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from consultes_carregues import connectar


SQL_COLS = """
SELECT COLUMN_NAME, DATA_TYPE
FROM   INFORMATION_SCHEMA.COLUMNS
WHERE  TABLE_NAME = 'Cargas'
  AND  DATA_TYPE IN ('datetime', 'date', 'smalldatetime', 'datetime2', 'time')
ORDER  BY ORDINAL_POSITION
"""


def main() -> int:
    car = sys.argv[1] if len(sys.argv) > 1 else "0002367"
    eje = sys.argv[2] if len(sys.argv) > 2 else "2026"
    sca = sys.argv[3] if len(sys.argv) > 3 else "01"

    conn = connectar()
    try:
        cols = list(conn.execute(SQL_COLS))
        if not cols:
            print("(no s'han trobat columnes de data a Cargas)")
            return 1

        col_list = ", ".join(f"[{r.COLUMN_NAME}]" for r in cols)
        sql = (
            f"SELECT TOP 1 {col_list} FROM Cargas WITH (NOLOCK) "
            "WHERE eje_ejercicio=? AND sca_serie=? AND car_numero=?"
        )
        row = conn.execute(sql, eje, sca, car).fetchone()
        if not row:
            print(f"(NO EXISTEIX carrega {eje}/{sca}/{car})")
            return 1

        print(f"Carrega {eje}/{sca}/{car} — columnes de data:")
        print("=" * 60)
        for i, r in enumerate(cols):
            val = row[i]
            print(f"  {r.COLUMN_NAME:<30} ({r.DATA_TYPE:<14}) = {val}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
