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
from logging.handlers import RotatingFileHandler

import pyodbc
from flask import Flask, jsonify, render_template, request, url_for

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
    cercar_articles, connectar, llistar_carregues, llistar_estats_carregues,
    llistar_transportistes, resum_carrega,
)
from valida import (  # noqa: E402
    valida_codi, valida_int, valida_llista_carregues, valida_rang_dates,
)
import agrupacions_store  # noqa: E402

# --- Logging amb rotació -------------------------------------------------
_log_handler = RotatingFileHandler(
    os.path.join(_HERE, "agrupacio.log"),
    maxBytes=2_000_000, backupCount=5, encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler, _stream_handler])
log = logging.getLogger("agrupacio")

app = Flask(__name__)


# --- Cache-busting d'assets ----------------------------------------------
@app.context_processor
def _inject_static_helper():
    def static_url(filename: str) -> str:
        path = os.path.join(_HERE, "static", *filename.split("/"))
        try:
            v = int(os.path.getmtime(path))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)
    return {"static_url": static_url}


# --- Headers de seguretat ------------------------------------------------
@app.after_request
def secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    return resp


# --- Helpers d'errors estandarditzats ------------------------------------
def _err_validacio(msg: str):
    return jsonify({"error": msg}), 400


def _err_db():
    return jsonify({"error": "Error de connexió amb la base de dades. Torna-ho a provar."}), 503


def _err_motor():
    return jsonify({"error": "El motor d'embalatges no està disponible. Contacta amb administració."}), 503


def _err_genèric():
    return jsonify({"error": "S'ha produït un error inesperat."}), 500


@app.route("/")
def index():
    avui = date.today()
    return render_template(
        "index.html",
        data_desde=avui.isoformat(),
        data_fins=(avui + timedelta(days=7)).isoformat(),
    )


@app.route("/magatzem", strict_slashes=False)
def magatzem_llista():
    return render_template("magatzem_llista.html")


@app.route("/ajuda")
def ajuda():
    return render_template("ajuda.html")


@app.route("/magatzem/<id_>")
def magatzem_prep(id_):
    obj = agrupacions_store.obtenir(id_)
    if not obj:
        return render_template("magatzem_llista.html", error="Agrupació no trobada."), 404
    return render_template("magatzem_prep.html", agrupacio_id=id_, nom=obj.get("nom", ""))


@app.route("/api/transportistes")
def api_transportistes():
    try:
        return jsonify(llistar_transportistes())
    except pyodbc.Error:
        log.exception("DB error a transportistes")
        return _err_db()
    except Exception:
        log.exception("transportistes")
        return _err_genèric()


@app.route("/api/carregues")
def api_carregues():
    rang, err = valida_rang_dates(request.args.get("desde"), request.args.get("fins"))
    if err:
        return _err_validacio(err)
    desde_d, fins_d = rang

    # Multi-transportista: accepta CSV o múltiples query params `tra_codi`
    tra_param = request.args.getlist("tra_codi")
    tra_codis: list[str] = []
    for raw in tra_param:
        for part in (raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            v, err = valida_codi(part, "tra_codi", max_len=5)
            if err:
                return _err_validacio(err)
            tra_codis.append(v)

    estat_raw = request.args.get("estat")
    estat = None
    if estat_raw not in (None, ""):
        estat, err = valida_int(estat_raw, "estat", minim=0, maxim=99)
        if err:
            return _err_validacio(err)

    art_codi, err = valida_codi(request.args.get("art_codi"), "art_codi", max_len=20, obligatori=False)
    if err:
        return _err_validacio(err)

    limit, err = valida_int(request.args.get("limit", "500"), "limit", minim=1, maxim=1000)
    if err:
        return _err_validacio(err)
    offset, err = valida_int(request.args.get("offset", "0"), "offset", minim=0)
    if err:
        return _err_validacio(err)
    try:
        resp = llistar_carregues(
            desde_d.isoformat(), fins_d.isoformat(),
            tra_codis=tra_codis or None,
            estat=estat,
            art_codi=art_codi,
            limit=limit, offset=offset,
        )
        # Enriqueix cada càrrega amb les agrupacions desades on apareix.
        index = agrupacions_store.index_carregues_agrupades()
        for item in resp.get("items", []):
            item["agrupacions"] = index.get(item["carrega_id"], [])
        return jsonify(resp)
    except pyodbc.Error:
        log.exception("DB error a carregues")
        return _err_db()
    except Exception:
        log.exception("carregues")
        return _err_genèric()


@app.route("/api/estats-carregues")
def api_estats_carregues():
    try:
        return jsonify(llistar_estats_carregues())
    except pyodbc.Error:
        log.exception("DB error a estats-carregues")
        return _err_db()
    except Exception:
        log.exception("estats-carregues")
        return _err_genèric()


@app.route("/api/articles")
def api_articles():
    q, err = valida_codi(request.args.get("q"), "q", max_len=40, obligatori=False)
    # `valida_codi` rebutja espais; per a la cerca d'articles deixem accents/espais. Provem directament.
    q = (request.args.get("q") or "").strip()
    if len(q) > 40:
        return _err_validacio("'q' té un format invàlid.")
    try:
        return jsonify(cercar_articles(q))
    except pyodbc.Error:
        log.exception("DB error a articles")
        return _err_db()
    except Exception:
        log.exception("articles")
        return _err_genèric()


@app.route("/api/agrupacions", methods=["GET"])
def api_agrupacions_llista():
    try:
        return jsonify(agrupacions_store.llistar())
    except Exception:
        log.exception("agrupacions llistar")
        return _err_genèric()


@app.route("/api/agrupacions", methods=["POST"])
def api_agrupacions_guardar():
    body = request.get_json(silent=True) or {}
    nom = (body.get("nom") or "").strip()
    if not nom:
        return _err_validacio("'nom' és obligatori.")
    if len(nom) > 80:
        return _err_validacio("'nom' té un format invàlid (màx 80 caràcters).")
    carregues, err = valida_llista_carregues(body.get("carregues"))
    if err:
        return _err_validacio(err)
    resultat = body.get("resultat")
    if not isinstance(resultat, dict):
        return _err_validacio("'resultat' és obligatori.")
    plantilla = bool(body.get("plantilla"))
    try:
        info = agrupacions_store.guardar(nom, carregues, resultat, plantilla=plantilla)
        log.info(
            "audit guardar agrupacio=%s nom=%s ip=%s n_carregues=%d plantilla=%s",
            info.get("id"), info.get("nom"), request.remote_addr, info.get("n_carregues", 0), plantilla,
        )
        return jsonify(info)
    except Exception:
        log.exception("agrupacions guardar")
        return _err_genèric()


@app.route("/api/plantilles", methods=["GET"])
def api_plantilles_llista():
    try:
        return jsonify(agrupacions_store.llistar_plantilles())
    except Exception:
        log.exception("plantilles llistar")
        return _err_genèric()


@app.route("/api/agrupacions/<id_>", methods=["GET"])
def api_agrupacions_obtenir(id_):
    obj = agrupacions_store.obtenir(id_)
    if not obj:
        return jsonify({"error": "Agrupació no trobada."}), 404
    return jsonify(obj)


@app.route("/api/agrupacions/<id_>", methods=["DELETE"])
def api_agrupacions_eliminar(id_):
    if agrupacions_store.eliminar(id_):
        log.info("audit eliminar agrupacio=%s ip=%s", id_, request.remote_addr)
        return jsonify({"ok": True})
    return jsonify({"error": "Agrupació no trobada."}), 404


@app.route("/api/agrupacions/<id_>/producte", methods=["PATCH"])
def api_agrupacions_producte(id_):
    body = request.get_json(silent=True) or {}
    art_codi, err = valida_codi(body.get("art_codi"), "art_codi", max_len=20)
    if err:
        return _err_validacio(err)
    preparat = bool(body.get("preparat"))
    obj = agrupacions_store.marca_producte(id_, art_codi, preparat, ip=request.remote_addr)
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info(
        "audit marca agrupacio=%s art=%s preparat=%s ip=%s",
        id_, art_codi, preparat, request.remote_addr,
    )
    return jsonify({"ok": True, "n_preparats": len(obj.get("productes_preparats") or [])})


@app.route("/api/agrupacions/<id_>/reset-preparats", methods=["POST"])
def api_agrupacions_reset_preparats(id_):
    obj = agrupacions_store.reset_preparats(id_, ip=request.remote_addr)
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info("reset preparats agrupacio=%s ip=%s", id_, request.remote_addr)
    return jsonify({"ok": True, "n_preparats": 0})


@app.route("/api/carrega-detall")
def api_carrega_detall():
    eje, err = valida_codi(request.args.get("eje"), "eje", max_len=4)
    if err:
        return _err_validacio(err)
    sca, err = valida_codi(request.args.get("sca"), "sca", max_len=2)
    if err:
        return _err_validacio(err)
    car, err = valida_codi(request.args.get("car"), "car", max_len=7)
    if err:
        return _err_validacio(err)
    try:
        return jsonify(resum_carrega(eje, sca, car))
    except pyodbc.Error:
        log.exception("DB error a carrega-detall")
        return _err_db()
    except Exception:
        log.exception("carrega-detall")
        return _err_genèric()


@app.route("/api/agrupar", methods=["POST"])
def api_agrupar():
    body = request.get_json(silent=True) or {}
    carregues, err = valida_llista_carregues(body.get("carregues"))
    if err:
        return _err_validacio(err)

    # Validació duplicats: una càrrega només pot estar en una agrupació.
    # Si ja és en qualsevol agrupació (activa o finalitzada), bloca amb 409.
    index = agrupacions_store.index_carregues_agrupades()
    duplicats = []
    for c in carregues:
        cid = c.get("carrega_id")
        existents = index.get(cid, [])
        if existents:
            duplicats.append({"carrega_id": cid, "agrupacions": existents})
    if duplicats:
        log.info("agrupar: bloquejat per duplicats — %d càrregues afectades", len(duplicats))
        return jsonify({
            "error": "Algunes càrregues ja són en una agrupació.",
            "duplicats": duplicats,
        }), 409

    try:
        log.info("agrupar: %d càrregues", len(carregues))
        resultat = agrupar(carregues)
        out = serialitzar(resultat)
        log.info(
            "audit agrupar ip=%s carregues=%d productes=%d palets=%d",
            request.remote_addr, len(carregues), len(out.get("productes", [])),
            out.get("total_palets_fisics", 0),
        )
        return jsonify(out)
    except pyodbc.Error:
        log.exception("DB error a agrupar")
        return _err_db()
    except ModuleNotFoundError:
        log.exception("App germana no disponible")
        return _err_motor()
    except Exception:
        log.exception("agrupar")
        return _err_genèric()


@app.route("/health")
def health():
    ok_db = ok_motor = ok_pg = False
    msg_db = msg_motor = msg_pg = ""
    try:
        conn = connectar()
        try:
            conn.execute("SELECT 1").fetchone()
            ok_db = True
        finally:
            conn.close()
    except Exception as e:
        msg_db = str(e)[:200]
    try:
        import db as _db
        ok_pg, msg_pg = _db.health_ok()
    except Exception as e:
        msg_pg = str(e)[:200]
    try:
        import motor  # noqa: F401
        ok_motor = hasattr(motor, "calcular_embalatges")
        if not ok_motor:
            msg_motor = "motor sense calcular_embalatges"
    except Exception as e:
        msg_motor = str(e)[:200]
    status = 200 if (ok_db and ok_motor and ok_pg) else 503
    return jsonify({
        "db": {"ok": ok_db, "msg": msg_db},
        "motor": {"ok": ok_motor, "msg": msg_motor},
        "pg": {"ok": ok_pg, "msg": msg_pg},
    }), status


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
