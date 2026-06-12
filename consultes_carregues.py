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

    # Mostrem TOTES les càrregues del rang (palletitzables i no). El frontend
    # rep per cada fila un boolean `palletitzable` per marcar-les visualment i
    # oferir un filtre opcional "Amaga no-palletitzables".
    #
    # Una càrrega es considera "palletitzable" si té com a mínim una línia
    # d'albarà amb tunitat != UNI/GRA i sacs > 0 (les mateixes regles que
    # aplica el motor d'embalatges).
    # NOTA: el `sal_codigo` codificat a det_documento és la sèrie del PEDIDO
    # (sal_SerAlbDefPed); la sèrie real a ALBLINIA pot diferir. Per això
    # acceptem o sal directe o qualsevol sal mapejat via SERIEALB.
    exists_palletizable_sql = """
        EXISTS (
            SELECT 1
            FROM   Detcargas d  WITH (NOLOCK)
            JOIN   ALBLINIA  l  WITH (NOLOCK)
              ON  l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
              AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
              AND ( l.sal_codigo = SUBSTRING(d.det_documento, 5, 2)
                    OR EXISTS (
                        SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                        WHERE s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                          AND s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                          AND s.sal_codigo       = l.sal_codigo
                    )
                  )
            JOIN   ARTICLES  a  WITH (NOLOCK) ON a.art_codi = l.art_codi
            WHERE  d.eje_ejercicio = c.eje_ejercicio
              AND  d.sca_serie     = c.sca_serie
              AND  d.car_numero    = c.car_numero
              AND  d.det_tipo      IN ('A', 'P')
              AND  l.lin_unit      > 0
              AND  RTRIM(a.art_descunit) NOT IN ('UNI', 'GRA')
        )
    """
    where_sql = """
        WHERE  COALESCE(c.car_fecsalida, c.car_fecha) >= ?
          AND  COALESCE(c.car_fecsalida, c.car_fecha) <  ?
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

    # Suma de kg per càrrega: mateixa lògica que `_pes_per_tunitat` en SQL.
    # IMPORTANT: per a cada det_documento resolem una sola `sal` real (via
    # CPALBARA, amb fallback a SERIEALB) ABANS d'agregar amb ALBLINIA. Si
    # juntem "sal directe OR sal via SERIEALB" al JOIN, comptaríem doble quan
    # el mateix número d'albarà existeix en més d'una sèrie a ALBLINIA.
    # Mateix patró que `resum_carrega` (CROSS APPLY).
    kg_total_sql = """
        ISNULL((
            SELECT SUM(
                l.lin_unit *
                CASE
                    WHEN LEFT(RTRIM(a.art_descunit), 1) = 'S'
                         AND TRY_CAST(SUBSTRING(RTRIM(a.art_descunit), 2, 10) AS FLOAT) IS NOT NULL
                    THEN TRY_CAST(SUBSTRING(RTRIM(a.art_descunit), 2, 10) AS FLOAT)
                    ELSE 0
                END
            )
            FROM   Detcargas d2  WITH (NOLOCK)
            CROSS APPLY (
                SELECT TOP 1 cp.sal_codigo
                FROM   CPALBARA cp WITH (NOLOCK)
                WHERE  cp.eje_ejercicio = SUBSTRING(d2.det_documento, 1, 4)
                  AND  cp.cpa_albara    = SUBSTRING(d2.det_documento, 7, 7)
                  AND  ( cp.sal_codigo = SUBSTRING(d2.det_documento, 5, 2)
                         OR EXISTS (
                             SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                             WHERE  s.eje_ejercicio    = SUBSTRING(d2.det_documento, 1, 4)
                               AND  s.sal_SerAlbDefPed = SUBSTRING(d2.det_documento, 5, 2)
                               AND  s.sal_codigo       = cp.sal_codigo
                         ) )
                ORDER BY CASE WHEN cp.sal_codigo = SUBSTRING(d2.det_documento, 5, 2) THEN 0 ELSE 1 END
            ) sal_resolt
            JOIN   ALBLINIA  l   WITH (NOLOCK)
              ON  l.eje_ejercicio = SUBSTRING(d2.det_documento, 1, 4)
              AND l.sal_codigo    = sal_resolt.sal_codigo
              AND l.cpa_albara    = SUBSTRING(d2.det_documento, 7, 7)
            JOIN   ARTICLES  a   WITH (NOLOCK) ON a.art_codi = l.art_codi
            WHERE  d2.eje_ejercicio = c.eje_ejercicio
              AND  d2.sca_serie     = c.sca_serie
              AND  d2.car_numero    = c.car_numero
              AND  d2.det_tipo      IN ('A', 'P')
              AND  l.lin_unit       > 0
              AND  RTRIM(a.art_descunit) NOT IN ('UNI', 'GRA')
        ), 0)
    """

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
               CAST(c.car_observaciones AS varchar(500)) AS car_observaciones,
               CAST(CASE WHEN """ + exists_palletizable_sql + """ THEN 1 ELSE 0 END AS BIT) AS palletitzable,
               """ + kg_total_sql + """ AS kg_total
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
            "palletitzable": bool(r.palletitzable),
            "kg_total": float(r.kg_total) if r.kg_total is not None else 0.0,
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


def obtenir_descrip_articles(codis: list[str]) -> dict[str, str]:
    """Retorna {art_codi: art_descrip} complet per a una llista de codis.

    El motor d'embalatges retorna sovint una versió escurçada del descrip
    (sense mides), però per imprimir-ho a paper volem el text complet
    tal com el guarden a ARTICLES.
    """
    codis = [c for c in (codis or []) if c]
    if not codis:
        return {}
    # Deduplica preservant ordre
    seen = set()
    unics = []
    for c in codis:
        if c not in seen:
            seen.add(c)
            unics.append(c)
    placeholders = ",".join(["?"] * len(unics))
    sql = f"""
        SELECT RTRIM(art_codi) AS art_codi, RTRIM(art_descrip) AS art_descrip
        FROM   ARTICLES WITH (NOLOCK)
        WHERE  art_codi IN ({placeholders})
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, *unics).fetchall()
    finally:
        conn.close()
    return {r.art_codi: (r.art_descrip or "").strip() for r in rows}


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
        # Pas 1: resoldre la sèrie real (sal_real) per a cada albarà.
        # Detcargas codifica la sèrie del PEDIDO (sal_SerAlbDefPed); la comanda
        # real a CPALBARA/ALBLINIA pot tenir una sèrie diferent. SERIEALB és la
        # taula de mapeig. Provem primer sal directe (cas habitual) i, si no
        # existeix, traduïm via SERIEALB.sal_SerAlbDefPed.
        claus_doc = [(a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"]) for a in albarans]
        values_sql = ",".join(["(CAST(? AS varchar(4)), CAST(? AS varchar(2)), CAST(? AS varchar(7)))"] * len(claus_doc))
        params_resolve: list = []
        for k in claus_doc:
            params_resolve.extend(k)

        sql_resolve = f"""
            SELECT d.eje_doc, d.sal_doc, d.alb_doc,
                   RTRIM(cp.sal_codigo) AS sal_real,
                   RTRIM(cp.cli_codi)   AS cli_codi,
                   RTRIM(c.cli_nom)     AS cli_nom,
                   RTRIM(cp.cpa_pobla)  AS cpa_pobla,
                   RTRIM(cv.adr_pobla)  AS cv_pobla
            FROM (VALUES {values_sql}) AS d(eje_doc, sal_doc, alb_doc)
            OUTER APPLY (
                SELECT TOP 1 cp.sal_codigo, cp.cli_codi, cp.adr_codi, cp.cpa_pobla
                FROM   CPALBARA cp WITH (NOLOCK)
                WHERE  cp.eje_ejercicio = d.eje_doc
                  AND  cp.cpa_albara    = d.alb_doc
                  AND  ( cp.sal_codigo = d.sal_doc
                         OR EXISTS (
                             SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                             WHERE  s.eje_ejercicio    = d.eje_doc
                               AND  s.sal_SerAlbDefPed = d.sal_doc
                               AND  s.sal_codigo       = cp.sal_codigo
                         ) )
                ORDER BY CASE WHEN cp.sal_codigo = d.sal_doc THEN 0 ELSE 1 END
            ) cp
            LEFT JOIN CLIENTS c WITH (NOLOCK) ON c.cli_codi = cp.cli_codi
            -- Direcció d'enviament (CLIENVIO): fallback per a `pobla` quan CPALBARA.cpa_pobla és buit.
            LEFT JOIN CLIENVIO cv WITH (NOLOCK)
                ON cv.cli_codi = cp.cli_codi AND cv.adr_codi = cp.adr_codi
        """
        resolved_rows = conn.execute(sql_resolve, *params_resolve).fetchall()

        # Mapeig: (eje_doc, sal_doc, alb_doc) -> {sal_real, cli_codi, cli_nom, pobla}
        resolts: dict[tuple[str, str, str], dict] = {}
        for r in resolved_rows:
            sal_real = (r.sal_real or "").strip() or r.sal_doc.strip()
            pobla = (r.cpa_pobla or "").strip() or (r.cv_pobla or "").strip()
            resolts[(r.eje_doc.strip(), r.sal_doc.strip(), r.alb_doc.strip())] = {
                "sal_real": sal_real,
                "cli_codi": (r.cli_codi or "").strip(),
                "cli_nom":  (r.cli_nom  or "").strip(),
                "pobla":    pobla,
            }

        # Pas 2: buscar línies amb les (eje, sal_real, alb) resoltes.
        # LEFT JOIN ARTICLES per no perdre línies amb codi sense mestre.
        claus_real = set()
        for a in albarans:
            res = resolts.get((a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"]))
            sal_real = res["sal_real"] if res else a["sal_codigo"]
            claus_real.add((a["eje_ejercicio"], sal_real, a["cpa_albara"]))
        claus_real = list(claus_real)

        if claus_real:
            conds_lin = " OR ".join(["(l.eje_ejercicio=? AND l.sal_codigo=? AND l.cpa_albara=?)"] * len(claus_real))
            params_lin: list = []
            for k in claus_real:
                params_lin.extend(k)
            sql_lin = f"""
                SELECT l.eje_ejercicio, RTRIM(l.sal_codigo) AS sal_codigo, RTRIM(l.cpa_albara) AS cpa_albara,
                       RTRIM(l.art_codi) AS art_codi, RTRIM(a.art_descrip) AS art_descrip,
                       l.lin_unit AS sacs, RTRIM(a.art_descunit) AS tunitat
                FROM   ALBLINIA l WITH (NOLOCK)
                LEFT JOIN ARTICLES a WITH (NOLOCK) ON a.art_codi = l.art_codi
                WHERE  {conds_lin}
                ORDER  BY l.eje_ejercicio, l.sal_codigo, l.cpa_albara, l.lin_linia
            """
            lin_rows = conn.execute(sql_lin, *params_lin).fetchall()
        else:
            lin_rows = []
    finally:
        conn.close()

    # Agrupar TOTES les línies per albarà; marquem cada una amb `palletitzable`
    # (palletitzable = tunitat != UNI/GRA i sacs > 0, mateixes regles que el motor).
    # Així el frontend pot atenuar / amagar les no-palletitzables, però l'usuari
    # les pot veure si vol.
    linies_per_alb: dict[tuple[str, str, str], list[dict]] = {}
    for r in lin_rows:
        tun = (r.tunitat or "").strip()
        sacs = int(r.sacs or 0)
        palletitzable = tun not in ("UNI", "GRA") and sacs > 0
        key = (r.eje_ejercicio, r.sal_codigo.strip(), r.cpa_albara.strip())
        kg = sacs * _pes_per_tunitat(tun) if palletitzable else 0.0
        linies_per_alb.setdefault(key, []).append({
            "art_codi": r.art_codi.strip() if r.art_codi else "",
            "art_descrip": (r.art_descrip or "").strip(),
            "sacs": sacs,
            "tunitat": tun,
            "kg": round(kg, 2),
            "palletitzable": palletitzable,
        })

    # Composar resposta. Els totals reflecteixen NOMÉS línies palletitzables
    # (és el que el motor d'embalatges considerarà).
    total_sacs = 0
    total_kg = 0.0
    out_alb = []
    for a in albarans:
        key_doc = (a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"])
        res = resolts.get(key_doc, {"sal_real": a["sal_codigo"], "cli_codi": "", "cli_nom": "", "pobla": ""})
        cli_codi = res["cli_codi"]
        cli_nom  = res["cli_nom"]
        pobla    = res.get("pobla", "")
        key_real = (a["eje_ejercicio"], res["sal_real"], a["cpa_albara"])
        linies = linies_per_alb.get(key_real, [])
        a_sacs = sum(l["sacs"] for l in linies if l["palletitzable"])
        a_kg = sum(l["kg"] for l in linies if l["palletitzable"])
        total_sacs += a_sacs
        total_kg += a_kg
        out_alb.append({
            "albara": f"{a['sal_codigo']}/{a['cpa_albara']}",
            "det_tipo": a["det_tipo"],
            "cli_codi": cli_codi,
            "cli_nom": cli_nom,
            "pobla": pobla,
            "total_sacs": a_sacs,
            "total_kg": round(a_kg, 2),
            "linies": linies,
        })

    return {"albarans": out_alb, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)}
