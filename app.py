"""Flask app — Agrupació de càrregues.

Endpoints:
    GET  /                    interfície principal
    GET  /api/transportistes  llistat transportistes (últim any)
    GET  /api/carregues       llistat càrregues filtrades
    POST /api/agrupar         agrupar càrregues seleccionades
"""
import logging
import os
import sys
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request

# --- Bootstrap .env i sys.path ABANS d'importar agregador ----------------
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


# 1) .env local (si existeix) — pot definir PREPARACIO_PATH i overrides
_carregar_env(os.path.join(_HERE, ".env"))

# 2) Resol PREPARACIO_PATH (env > default)
_PREP_PATH = os.environ.get("PREPARACIO_PATH", r"P:\preparacioComandesVenda")

# 3) Fallback: carrega .env de l'app germana per heretar credencials SQL
#    (evita duplicar secrets en dos directoris)
_carregar_env(os.path.join(_PREP_PATH, ".env"))

if _PREP_PATH and os.path.isdir(_PREP_PATH) and _PREP_PATH not in sys.path:
    sys.path.insert(0, _PREP_PATH)

# Imports locals (després del sys.path)
from agregador import agrupar, serialitzar  # noqa: E402
from consultes_carregues import (  # noqa: E402
    llistar_carregues, llistar_transportistes, resum_carrega,
)

# --- Logging -------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_HERE, "agrupacio.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("agrupacio")

app = Flask(__name__)


@app.route("/")
def index():
    avui = date.today()
    return render_template(
        "index.html",
        data_desde=avui.isoformat(),
        data_fins=(avui + timedelta(days=7)).isoformat(),
    )


@app.route("/api/transportistes")
def api_transportistes():
    try:
        return jsonify(llistar_transportistes())
    except Exception as e:
        log.exception("transportistes")
        return jsonify({"error": str(e)}), 500


@app.route("/api/carregues")
def api_carregues():
    desde = request.args.get("desde", "").strip()
    fins = request.args.get("fins", "").strip()
    tra_codi = (request.args.get("tra_codi") or "").strip() or None
    if not desde or not fins:
        return jsonify({"error": "Paràmetres 'desde' i 'fins' obligatoris (YYYY-MM-DD)."}), 400
    try:
        return jsonify(llistar_carregues(desde, fins, tra_codi))
    except Exception as e:
        log.exception("carregues")
        return jsonify({"error": str(e)}), 500


@app.route("/api/carrega-detall")
def api_carrega_detall():
    eje = (request.args.get("eje") or "").strip()
    sca = (request.args.get("sca") or "").strip()
    car = (request.args.get("car") or "").strip()
    if not (eje and sca and car):
        return jsonify({"error": "Paràmetres 'eje', 'sca' i 'car' obligatoris."}), 400
    try:
        return jsonify(resum_carrega(eje, sca, car))
    except Exception as e:
        log.exception("carrega-detall")
        return jsonify({"error": str(e)}), 500


@app.route("/api/agrupar", methods=["POST"])
def api_agrupar():
    body = request.get_json(silent=True) or {}
    carregues = body.get("carregues") or []
    if not carregues:
        return jsonify({"error": "Cap càrrega seleccionada."}), 400
    if len(carregues) > 50:
        return jsonify({"error": "Màxim 50 càrregues per agrupació."}), 400
    try:
        log.info("agrupar: %d càrregues", len(carregues))
        resultat = agrupar(carregues)
        return jsonify(serialitzar(resultat))
    except Exception as e:
        log.exception("agrupar")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
