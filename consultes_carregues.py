"""Consultes específiques de càrregues per a l'app d'agrupacions.

Mòdul autònom (no comparteix connexió amb motor.py de l'app germana
perquè el seu semàfor és per a procés). Una connexió per request.
"""
import os
from datetime import datetime, timedelta

import pyodbc

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SERVER = os.environ.get("SQL_SERVER", r"vkais\kais")
DATABASE = os.environ.get("SQL_DATABASE", "GWSV_AGRI")
USER = os.environ.get("SQL_USER", "")
PASSWORD = os.environ.get("SQL_PASSWORD", "")

_CONN_STR = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};DATABASE={DATABASE};UID={USER};PWD={PASSWORD};"
    f"TrustServerCertificate=yes;APP=AgrupacioCarregues;"
    f"ApplicationIntent=ReadOnly;"
)


def connectar():
    conn = pyodbc.connect(_CONN_STR, timeout=10, autocommit=True)
    conn.timeout = 15
    conn.execute("SET NOCOUNT ON")
    return conn


def llistar_carregues(
    desde: str,
    fins: str,
    tra_codis: list[str] | str | None = None,
    estat: int | None = None,
    art_codi: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict:
    """Q1: Llistar càrregues filtrant per data sortida i criteris addicionals.

    desde / fins: 'YYYY-MM-DD'
    tra_codis: codi sol, llista de codis, o None per 'tots'.
    estat: si està definit, filtra c.car_estat = ?.
    art_codi: si està definit, només càrregues amb una línia amb aquest art_codi.
    Retorna {"items": [...], "total": N, "limit": L, "offset": O}.
    """
    desde_d = datetime.strptime(desde, "%Y-%m-%d").date()
    fins_d = datetime.strptime(fins, "%Y-%m-%d").date() + timedelta(days=1)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    # Normalitza tra_codis: accepta string simple o llista
    if isinstance(tra_codis, str):
        tra_codis = [c.strip() for c in tra_codis.split(",") if c.strip()]
    elif tra_codis is None:
        tra_codis = []

    # Una càrrega és "palettzable" si té com a mínim una línia d'albarà amb
    # tunitat != UNI/GRA i sacs > 0 (mateixes regles que aplica el motor
    # d'embalatges). Si no n'hi ha cap, no apareix a la llista per evitar
    # mostrar càrregues "fantasma" que sortirien amb "0 sacs · 0 kg".
    where_sql = """
        WHERE  COALESCE(c.car_fecsalida, c.car_fecha) >= ?
          AND  COALESCE(c.car_fecsalida, c.car_fecha) <  ?
          AND  EXISTS (
              SELECT 1
              FROM   Detcargas d  WITH (NOLOCK)
              JOIN   ALBLINIA  l  WITH (NOLOCK)
                ON  l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
                AND l.sal_codigo    = SUBSTRING(d.det_documento, 5, 2)
                AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
              JOIN   ARTICLES  a  WITH (NOLOCK) ON a.art_codi = l.art_codi
              WHERE  d.eje_ejercicio = c.eje_ejercicio
                AND  d.sca_serie     = c.sca_serie
                AND  d.car_numero    = c.car_numero
                AND  d.det_tipo      IN ('A', 'P')
                AND  l.lin_unit      > 0
                AND  RTRIM(a.art_descunit) NOT IN ('UNI', 'GRA')
          )
    """
    where_params: list = [desde_d, fins_d]
    if tra_codis:
        placeholders = ",".join(["?"] * len(tra_codis))
        where_sql += f" AND c.tra_codi IN ({placeholders})"
        where_params.extend(tra_codis)
    if estat is not None:
        where_sql += " AND c.car_estat = ?"
        where_params.append(int(estat))
    if art_codi:
        where_sql += """
          AND EXISTS (
              SELECT 1
              FROM   Detcargas d2 WITH (NOLOCK)
              JOIN   ALBLINIA l   WITH (NOLOCK)
                ON  l.eje_ejercicio = SUBSTRING(d2.det_documento, 1, 4)
                AND l.sal_codigo    = SUBSTRING(d2.det_documento, 5, 2)
                AND l.cpa_albara    = SUBSTRING(d2.det_documento, 7, 7)
              WHERE d2.eje_ejercicio = c.eje_ejercicio
                AND d2.sca_serie     = c.sca_serie
                AND d2.car_numero    = c.car_numero
                AND d2.det_tipo      IN ('A','P')
                AND l.art_codi       = ?
          )
        """
        where_params.append(art_codi)

    sql_items = """
        SELECT c.eje_ejercicio,
               RTRIM(c.sca_serie)   AS sca_serie,
               RTRIM(c.car_numero)  AS car_numero,
               RTRIM(c.car_descripcion) AS car_descripcion,
               c.car_fecha,
               c.car_fecsalida,
               c.car_estat,
               RTRIM(c.tra_codi)    AS tra_codi,
               RTRIM(t.tra_nom)     AS transportista,
               RTRIM(c.car_matricula)    AS car_matricula,
               RTRIM(c.car_nomconductor) AS car_nomconductor,
               c.car_pesonetocarga,
               c.car_pesoteorico,
               CAST(c.car_observaciones AS varchar(500)) AS car_observaciones
        FROM   Cargas c WITH (NOLOCK)
        LEFT JOIN TRANS t WITH (NOLOCK) ON t.tra_codi = c.tra_codi
    """ + where_sql + """
        ORDER BY COALESCE(c.car_fecsalida, c.car_fecha) DESC, c.car_numero DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    sql_count = "SELECT COUNT(*) AS n FROM Cargas c WITH (NOLOCK) " + where_sql

    conn = connectar()
    try:
        total = conn.execute(sql_count, *where_params).fetchone().n
        rows = conn.execute(sql_items, *where_params, offset, limit).fetchall()
    finally:
        conn.close()

    items = [
        {
            "eje_ejercicio": r.eje_ejercicio,
            "sca_serie": r.sca_serie,
            "car_numero": r.car_numero,
            "carrega_id": f"{r.eje_ejercicio}/{r.sca_serie}/{r.car_numero}",
            "car_descripcion": (r.car_descripcion or "").strip(),
            "car_fecha": r.car_fecha.strftime("%Y-%m-%d") if r.car_fecha else None,
            "car_fecsalida": r.car_fecsalida.strftime("%Y-%m-%d") if r.car_fecsalida else None,
            "car_estat": r.car_estat,
            "tra_codi": r.tra_codi,
            "transportista": r.transportista or "",
            "car_matricula": r.car_matricula or "",
            "car_nomconductor": r.car_nomconductor or "",
            "car_pesonetocarga": float(r.car_pesonetocarga) if r.car_pesonetocarga is not None else 0.0,
            "car_pesoteorico": float(r.car_pesoteorico) if r.car_pesoteorico is not None else 0.0,
            "car_observaciones": (r.car_observaciones or "").strip(),
        }
        for r in rows
    ]
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


def llistar_estats_carregues() -> list[dict]:
    """Estats distints de càrrega de l'últim any amb el comptador. Cacheable."""
    sql = """
        SELECT car_estat, COUNT(*) AS n
        FROM   Cargas WITH (NOLOCK)
        WHERE  COALESCE(car_fecsalida, car_fecha) >= DATEADD(YEAR, -1, GETDATE())
        GROUP  BY car_estat
        ORDER  BY car_estat
    """
    conn = connectar()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [{"estat": int(r.car_estat) if r.car_estat is not None else None, "n": int(r.n)} for r in rows]


def cercar_articles(q: str, limit: int = 20) -> list[dict]:
    """Autocompletar articles per codi o descripció. q de 2+ caràcters."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    limit = max(1, min(int(limit), 50))
    pat = f"%{q}%"
    sql = """
        SELECT TOP (?) RTRIM(art_codi) AS art_codi, RTRIM(art_descrip) AS art_descrip
        FROM   ARTICLES WITH (NOLOCK)
        WHERE  art_codi LIKE ? OR art_descrip LIKE ?
        ORDER  BY CASE WHEN art_codi LIKE ? THEN 0 ELSE 1 END, art_codi
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, limit, pat, pat, pat).fetchall()
    finally:
        conn.close()
    return [{"art_codi": r.art_codi, "art_descrip": (r.art_descrip or "").strip()} for r in rows]


def llistar_transportistes() -> list[dict]:
    """Llistat de transportistes que han fet alguna càrrega l'últim any."""
    sql = """
        SELECT DISTINCT RTRIM(t.tra_codi) AS tra_codi, RTRIM(t.tra_nom) AS tra_nom
        FROM   TRANS  t WITH (NOLOCK)
        JOIN   Cargas c WITH (NOLOCK) ON c.tra_codi = t.tra_codi
        WHERE  c.car_fecha >= DATEADD(YEAR, -1, GETDATE())
        ORDER  BY tra_nom
    """
    conn = connectar()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [{"tra_codi": r.tra_codi, "tra_nom": r.tra_nom or ""} for r in rows]


def obtenir_albarans_carrega(eje: str, sca: str, car: str) -> list[dict]:
    """Q2: Documents (tipus 'A' albarà o 'P' comanda) d'una càrrega.

    det_documento (varchar(13)) = eje(4) + sal_codigo(2) + cpa_albara(7).
    Format consistent per als dos tipus: 'A' i 'P' es passen igual a motor.calcular_embalatges()
    perquè aquesta consulta CPALBARA, que inclou ambdós estats.
    """
    sql = """
        SELECT SUBSTRING(d.det_documento, 1, 4) AS eje_doc,
               SUBSTRING(d.det_documento, 5, 2) AS sal_codigo,
               SUBSTRING(d.det_documento, 7, 7) AS cpa_albara,
               d.det_tipo,
               d.det_ordencarga
        FROM   Detcargas d WITH (NOLOCK)
        WHERE  d.eje_ejercicio = ?
          AND  d.sca_serie     = ?
          AND  d.car_numero    = ?
          AND  d.det_tipo      IN ('A', 'P')
        ORDER  BY COALESCE(d.det_ordencarga, 0), d.det_id
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, eje, sca, car).fetchall()
    finally:
        conn.close()
    return [
        {
            "eje_ejercicio": r.eje_doc,
            "sal_codigo":    r.sal_codigo,
            "cpa_albara":    r.cpa_albara,
            "det_tipo":      r.det_tipo,
        }
        for r in rows
    ]


def _pes_per_tunitat(tunitat: str) -> float:
    if tunitat and tunitat.startswith("S"):
        try:
            return float(tunitat[1:])
        except ValueError:
            return 0.0
    return 0.0


def resum_carrega(eje: str, sca: str, car: str) -> dict:
    """Previsualització lleugera del contingut d'una càrrega.

    Retorna els albarans associats amb client + resum de línies (sense executar
    el motor de càlcul d'embalatges). Pensat per inspeccionar abans de seleccionar.

    Output: {
        "albarans": [
            {
                "albara": "01/0001234",
                "det_tipo": "A" | "P",
                "cli_codi": "...",
                "cli_nom": "...",
                "total_sacs": N,
                "total_kg": N.0,
                "linies": [{art_codi, art_descrip, sacs, tunitat, kg}],
            },
            ...
        ],
        "total_sacs": N,
        "total_kg": N.0,
    }
    """
    albarans = obtenir_albarans_carrega(eje, sca, car)
    if not albarans:
        return {"albarans": [], "total_sacs": 0, "total_kg": 0.0}

    conn = connectar()
    try:
        # 1 query per als clients (CPALBARA + CLIENTS)
        claus = [(a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"]) for a in albarans]
        placeholders = ",".join(["(?,?,?)"] * len(claus))
        params: list = []
        for k in claus:
            params.extend(k)
        sql_clients = f"""
            SELECT cp.eje_ejercicio, RTRIM(cp.sal_codigo) AS sal_codigo, RTRIM(cp.cpa_albara) AS cpa_albara,
                   RTRIM(cp.cli_codi) AS cli_codi, RTRIM(c.cli_nom) AS cli_nom
            FROM   CPALBARA cp WITH (NOLOCK)
            LEFT JOIN CLIENTS c WITH (NOLOCK) ON c.cli_codi = cp.cli_codi
            WHERE  (cp.eje_ejercicio, cp.sal_codigo, cp.cpa_albara) IN ({placeholders})
        """
        try:
            client_rows = conn.execute(sql_clients, *params).fetchall()
        except pyodbc.Error:
            # Fallback per si la sintaxi de IN tuples no és suportada: OR concatenats
            conds = " OR ".join(["(cp.eje_ejercicio=? AND cp.sal_codigo=? AND cp.cpa_albara=?)"] * len(claus))
            sql_clients = f"""
                SELECT cp.eje_ejercicio, RTRIM(cp.sal_codigo) AS sal_codigo, RTRIM(cp.cpa_albara) AS cpa_albara,
                       RTRIM(cp.cli_codi) AS cli_codi, RTRIM(c.cli_nom) AS cli_nom
                FROM   CPALBARA cp WITH (NOLOCK)
                LEFT JOIN CLIENTS c WITH (NOLOCK) ON c.cli_codi = cp.cli_codi
                WHERE  {conds}
            """
            client_rows = conn.execute(sql_clients, *params).fetchall()
        clients = {
            (r.eje_ejercicio, r.sal_codigo.strip(), r.cpa_albara.strip()): (
                r.cli_codi.strip() if r.cli_codi else "",
                r.cli_nom or "",
            )
            for r in client_rows
        }

        # 1 query per a totes les línies (ALBLINIA + ARTICLES)
        conds = " OR ".join(["(l.eje_ejercicio=? AND l.sal_codigo=? AND l.cpa_albara=?)"] * len(claus))
        sql_lin = f"""
            SELECT l.eje_ejercicio, RTRIM(l.sal_codigo) AS sal_codigo, RTRIM(l.cpa_albara) AS cpa_albara,
                   RTRIM(l.art_codi) AS art_codi, RTRIM(a.art_descrip) AS art_descrip,
                   l.lin_unit AS sacs, RTRIM(a.art_descunit) AS tunitat
            FROM   ALBLINIA l WITH (NOLOCK)
            INNER JOIN ARTICLES a WITH (NOLOCK) ON a.art_codi = l.art_codi
            WHERE  {conds}
            ORDER  BY l.eje_ejercicio, l.sal_codigo, l.cpa_albara, l.lin_linia
        """
        lin_rows = conn.execute(sql_lin, *params).fetchall()
    finally:
        conn.close()

    # Agrupar línies per albarà (filtrar UNI/GRA i sacs=0, com fa RF1 del motor)
    linies_per_alb: dict[tuple[str, str, str], list[dict]] = {}
    for r in lin_rows:
        tun = (r.tunitat or "").strip()
        sacs = int(r.sacs or 0)
        if tun in ("UNI", "GRA") or sacs <= 0:
            continue
        key = (r.eje_ejercicio, r.sal_codigo.strip(), r.cpa_albara.strip())
        kg = sacs * _pes_per_tunitat(tun)
        linies_per_alb.setdefault(key, []).append({
            "art_codi": r.art_codi.strip() if r.art_codi else "",
            "art_descrip": (r.art_descrip or "").strip(),
            "sacs": sacs,
            "tunitat": tun,
            "kg": round(kg, 2),
        })

    # Composar resposta
    total_sacs = 0
    total_kg = 0.0
    out_alb = []
    for a in albarans:
        key = (a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"])
        cli_codi, cli_nom = clients.get(key, ("", ""))
        linies = linies_per_alb.get(key, [])
        a_sacs = sum(l["sacs"] for l in linies)
        a_kg = sum(l["kg"] for l in linies)
        total_sacs += a_sacs
        total_kg += a_kg
        out_alb.append({
            "albara": f"{a['sal_codigo']}/{a['cpa_albara']}",
            "det_tipo": a["det_tipo"],
            "cli_codi": cli_codi,
            "cli_nom": cli_nom,
            "total_sacs": a_sacs,
            "total_kg": round(a_kg, 2),
            "linies": linies,
        })

    return {"albarans": out_alb, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)}
