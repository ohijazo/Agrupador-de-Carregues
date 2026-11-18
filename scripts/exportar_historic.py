"""Exporta l'historic de KAIS per a l'app de SAP (agrupacio-carregues-sap).

El 23/11/2026 l'app passa a llegir de SAP. Perque l'usuari no noti el canvi,
l'app de SAP hereta d'aquesta:
  - els usuaris (amb el mateix hash de contrasenya),
  - les agrupacions desades (amb els productes preparats i les carregues),
  - les carregues del calendari (el mateix que retorna /api/carregues) i el
    detall de cadascuna (el mateix que retorna /api/carrega-detall).

Nomes llegeix: a KAIS (SQL Server) i a PostgreSQL. Escriu un fitxer JSON que
importa `scripts/importar_historic_kais.py` de l'app de SAP.

Us (al servidor, des de /var/www/agrupacio-carregues):
    venv/bin/python scripts/exportar_historic.py --sortida /var/tmp/historic_kais.json
    venv/bin/python scripts/exportar_historic.py --desde 2026-08-23 --fins 2026-11-22 --sortida f.json
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

# `import app` carrega el .env, posa PREPARACIO_PATH al sys.path i deixa a
# punt el pool de PostgreSQL, exactament com quan corre el servei.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import app  # noqa: F401,E402
import db  # noqa: E402
from consultes_carregues import llistar_carregues, resum_carrega  # noqa: E402

DESDE_DEFECTE = "2026-08-23"   # tres mesos abans de l'entrada a SAP
FINS_DEFECTE = "2026-11-22"    # l'ultim dia de KAIS


def _rangs_mensuals(desde: date, fins: date):
    """Trossos de com a molt un mes: /api/carregues no en dona mes de 1000."""
    ini = desde
    while ini <= fins:
        seg = (ini.replace(day=1) + timedelta(days=32)).replace(day=1)
        fi = min(seg - timedelta(days=1), fins)
        yield ini, fi
        ini = fi + timedelta(days=1)


def _carregues(desde: date, fins: date) -> list[dict]:
    items: dict[str, dict] = {}
    for ini, fi in _rangs_mensuals(desde, fins):
        offset = 0
        while True:
            r = llistar_carregues(ini.isoformat(), fi.isoformat(), limit=1000, offset=offset)
            for it in r["items"]:
                items[it["carrega_id"]] = it
            n = len(r["items"])
            offset += n
            if n < 1000:
                break
        print(f"  {ini} .. {fi}: {len(items)} carregues acumulades", flush=True)
    return list(items.values())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", default=DESDE_DEFECTE)
    p.add_argument("--fins", default=FINS_DEFECTE)
    p.add_argument("--sortida", required=True)
    args = p.parse_args()
    desde = date.fromisoformat(args.desde)
    fins = date.fromisoformat(args.fins)
    t0 = time.monotonic()

    print(f"Carregues de KAIS {desde} .. {fins}", flush=True)
    items = _carregues(desde, fins)
    carregues, errors = [], 0
    for i, it in enumerate(items, 1):
        eje, sca, car = it["carrega_id"].split("/")
        try:
            detall = resum_carrega(eje, sca, car)
        except Exception as e:  # una carrega sense detall no ha d'aturar-ho tot
            print(f"  AVIS: sense detall per a {it['carrega_id']}: {e}", flush=True)
            detall, errors = None, errors + 1
        carregues.append({"item": it, "detall": detall})
        if i % 200 == 0:
            print(f"  detall {i}/{len(items)}", flush=True)

    usuaris = db.fetch_all("SELECT * FROM usuaris ORDER BY id")
    ids = [c["item"]["carrega_id"] for c in carregues]
    # Agrupacions dels tres mesos: les creades en el periode o les que
    # contenen alguna de les carregues exportades.
    agrupacions = db.fetch_all(
        """SELECT * FROM agrupacions a
            WHERE a.ts >= %s
               OR EXISTS (SELECT 1 FROM agrupacio_carregues ac
                           WHERE ac.agrupacio_id = a.id AND ac.carrega_id = ANY(%s))
            ORDER BY a.ts""",
        (desde, ids),
    )
    ids_agr = [a["id"] for a in agrupacions]
    productes = db.fetch_all(
        "SELECT * FROM productes_preparats WHERE agrupacio_id = ANY(%s)", (ids_agr,))
    agr_carr = db.fetch_all(
        "SELECT * FROM agrupacio_carregues WHERE agrupacio_id = ANY(%s)", (ids_agr,))

    dades = {
        "generat": datetime.now().isoformat(timespec="seconds"),
        "desde": desde.isoformat(),
        "fins": fins.isoformat(),
        "usuaris": usuaris,
        "agrupacions": agrupacions,
        "productes_preparats": productes,
        "agrupacio_carregues": agr_carr,
        "carregues": carregues,
    }
    tmp = args.sortida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dades, f, ensure_ascii=False, default=str)
    os.replace(tmp, args.sortida)
    print(f"OK - {len(usuaris)} usuaris, {len(agrupacions)} agrupacions, "
          f"{len(carregues)} carregues ({errors} sense detall) en "
          f"{time.monotonic() - t0:.0f} s -> {args.sortida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
