"""Diagnostic per al filtre de carregues resum.

Llanca'l des del directori del repo desplegat:
    sudo -u www-data /var/www/agrupacio-carregues/venv/bin/python \\
        /var/www/agrupacio-carregues/scripts/diagnostic_resum.py 0002442 0002443

Mostra, per a cada car_numero:
  - capcalera (descripcio, estat, dates)
  - num_comandes (Detcargas)
  - linies via JOIN directe a ALBLINIA (sense SERIEALB)
  - linies via resolucio CPALBARA+SERIEALB
  - is_resum_candidate calculat (segons la regla del filtre actual)

Aixo permet veure exactament per que el filtre marca o no marca una carrega
com a resum, sense dependre del codi de produccio.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from consultes_carregues import connectar


SQL_HEAD = """
SELECT c.car_numero, c.car_descripcion, c.car_estat,
       c.car_fecha, c.car_fecsalida, c.car_fecllegada, c.tra_codi
FROM Cargas c WITH (NOLOCK)
WHERE c.eje_ejercicio='2026' AND c.sca_serie='01' AND c.car_numero=?
"""

SQL_NUM_COMANDES = """
SELECT COUNT(DISTINCT d.det_documento) AS n
FROM Detcargas d WITH (NOLOCK)
WHERE d.eje_ejercicio='2026' AND d.sca_serie='01' AND d.car_numero=?
  AND d.det_tipo IN ('A','P')
"""

SQL_DETCARGAS = """
SELECT d.det_documento, d.det_tipo
FROM Detcargas d WITH (NOLOCK)
WHERE d.eje_ejercicio='2026' AND d.sca_serie='01' AND d.car_numero=?
  AND d.det_tipo IN ('A','P')
"""

SQL_DIRECT = """
SELECT d.det_documento, l.art_codi, l.lin_unit, l.lin_quan
FROM Detcargas d WITH (NOLOCK)
LEFT JOIN ALBLINIA l WITH (NOLOCK)
  ON l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
 AND l.sal_codigo    = SUBSTRING(d.det_documento, 5, 2)
 AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
WHERE d.eje_ejercicio='2026' AND d.sca_serie='01' AND d.car_numero=?
  AND d.det_tipo IN ('A','P')
ORDER BY d.det_documento, l.art_codi
"""

SQL_RESOLT = """
SELECT d.det_documento, sal_resolt.sal_codigo AS sal_real,
       l.art_codi, l.lin_unit, l.lin_quan
FROM Cargas c WITH (NOLOCK)
JOIN Detcargas d WITH (NOLOCK)
  ON d.eje_ejercicio = c.eje_ejercicio
 AND d.sca_serie     = c.sca_serie
 AND d.car_numero    = c.car_numero
OUTER APPLY (
    SELECT TOP 1 cp.sal_codigo
    FROM CPALBARA cp WITH (NOLOCK)
    WHERE cp.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
      AND cp.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
      AND (cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2)
           OR EXISTS (SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                      WHERE s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                        AND s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                        AND s.sal_codigo       = cp.sal_codigo))
    ORDER BY CASE WHEN RTRIM(cp.tra_codi) = RTRIM(c.tra_codi) THEN 0 ELSE 1 END,
             COALESCE(ABS(DATEDIFF(day, cp.cpa_fechaservir,
                                  COALESCE(c.car_fecllegada, c.car_fecsalida, c.car_fecha))), 999999),
             CASE WHEN cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2) THEN 0 ELSE 1 END,
             cp.cpa_estat ASC
) sal_resolt
LEFT JOIN ALBLINIA l WITH (NOLOCK)
  ON l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
 AND l.sal_codigo    = sal_resolt.sal_codigo
 AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
WHERE c.eje_ejercicio='2026' AND c.sca_serie='01' AND c.car_numero=?
  AND d.det_tipo IN ('A','P')
ORDER BY d.det_documento, l.art_codi
"""


def diag(conn, car):
    print()
    print("=" * 70)
    print(f"Carrega 2026/01/{car}")
    print("=" * 70)

    head = conn.execute(SQL_HEAD, car).fetchone()
    if not head:
        print("  (NO EXISTEIX a Cargas)")
        return
    print(f"  descripcio   : {head.car_descripcion!r}")
    print(f"  car_estat    : {head.car_estat}")
    print(f"  car_fecha    : {head.car_fecha}")
    print(f"  car_fecsalida: {head.car_fecsalida}")
    print(f"  car_fecllegada: {head.car_fecllegada}")
    print(f"  tra_codi     : {head.tra_codi}")

    nc = conn.execute(SQL_NUM_COMANDES, car).fetchone().n
    print(f"  num_comandes : {nc}")

    print()
    print("  --- Detcargas (raw) ---")
    detc = list(conn.execute(SQL_DETCARGAS, car))
    if not detc:
        print("    (cap)")
    for r in detc:
        print(f"    det_doc={r.det_documento}  tipo={r.det_tipo}")

    print()
    print("  --- ALBLINIA via JOIN directe (sense SERIEALB) ---")
    direct = list(conn.execute(SQL_DIRECT, car))
    if not direct:
        print("    (cap linia)")
    arts_direct = set()
    for r in direct:
        print(f"    det_doc={r.det_documento}  art={r.art_codi}  unit={r.lin_unit}  quan={r.lin_quan}")
        if r.art_codi:
            arts_direct.add(r.art_codi.strip() if isinstance(r.art_codi, str) else r.art_codi)

    print()
    print("  --- ALBLINIA via resolucio CPALBARA+SERIEALB ---")
    resolt = list(conn.execute(SQL_RESOLT, car))
    if not resolt:
        print("    (cap linia)")
    for r in resolt:
        print(f"    det_doc={r.det_documento}  sal_real={r.sal_real}  art={r.art_codi}  unit={r.lin_unit}  quan={r.lin_quan}")

    print()
    print("  --- Veredicte del filtre actual ---")
    cond1 = (nc == 1)
    cond2 = ("30000" in arts_direct)
    cond3 = (len(arts_direct) > 0 and arts_direct.issubset({"30000"}))
    is_candidate = cond1 and cond2 and cond3
    print(f"    num_comandes==1                : {cond1}")
    print(f"    EXISTS art_codi='30000' directe: {cond2}")
    print(f"    NO arts !=30000 directe        : {cond3}")
    print(f"    is_resum_candidate             : {is_candidate}")


def main():
    cars = sys.argv[1:] or ["0002442", "0002443"]
    conn = connectar()
    try:
        for car in cars:
            diag(conn, car)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
