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
    # de comanda amb tunitat != UNI/GRA i sacs > 0 (les mateixes regles que
    # aplica el motor d'embalatges).
    # NOTA: el `sal_codigo` codificat a det_documento és la sèrie del PEDIDO
    # (sal_SerAlbDefPed); la sèrie real a ALBLINIA pot diferir. Per això
    # acceptem o sal directe o qualsevol sal mapejat via SERIEALB.
    # Resol primer la sal real (via CROSS APPLY amb CPALBARA) per evitar
    # caçar línies d'una comanda d'una altra sèrie amb el mateix número.
    # PRIORITAT del CROSS APPLY (mateix patró als 4 llocs del mòdul):
    # 1) SERIEALB inequívoc: si hi ha EXACTAMENT UN mapping pedido→albarà,
    #    aquest mapping és definitiu — encara que també existeixi una fila
    #    CPALBARA amb sal_codigo = sal_pedido (coincidència accidental d'un
    #    número d'albarà compartit per molts clients).
    #    Verificat amb NUTREX 2026/02/0000208 (mapping únic 02→52) i
    #    SIGFREDO 2026/02/0000216 (mapping únic 08→58 amb tra_codi també
    #    coincident a la fila errònia).
    # 2) tra_codi coincident: desempata quan SERIEALB té múltiples mappings.
    #    Verificat amb MATAS 2026/01/0002269 (sal_pedido=01 mapeja a molts;
    #    cap mapping té tra_codi=154, així que cau al match directe LLAUSAS).
    # 3) Match directe per sal_codigo: fallback quan no hi ha mapping ni
    #    tra_codi discriminatiu.
    exists_palletizable_sql = """
        EXISTS (
            SELECT 1
            FROM   Detcargas d  WITH (NOLOCK)
            CROSS APPLY (
                SELECT TOP 1 cp.sal_codigo
                FROM   CPALBARA cp WITH (NOLOCK)
                WHERE  cp.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
                  AND  cp.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
                  AND  ( cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2)
                         OR EXISTS (
                             SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                             WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                               AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                               AND  s.sal_codigo       = cp.sal_codigo
                         ) )
                ORDER BY
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                              AND  s.sal_codigo       = cp.sal_codigo
                        ) AND (
                            SELECT COUNT(*) FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                        ) = 1
                        THEN 0 ELSE 1
                    END,
                    CASE WHEN RTRIM(cp.tra_codi) = RTRIM(c.tra_codi) THEN 0 ELSE 1 END,
                    CASE WHEN cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2) THEN 0 ELSE 1 END
            ) sal_resolt
            JOIN   ALBLINIA  l   WITH (NOLOCK)
              ON  l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
              AND l.sal_codigo    = sal_resolt.sal_codigo
              AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
            JOIN   ARTICLES  a   WITH (NOLOCK) ON a.art_codi = l.art_codi
            WHERE  d.eje_ejercicio = c.eje_ejercicio
              AND  d.sca_serie     = c.sca_serie
              AND  d.car_numero    = c.car_numero
              AND  d.det_tipo      IN ('A', 'P')
              AND  l.lin_unit      > 0
              AND  RTRIM(a.art_descunit) NOT IN ('UNI', 'GRA')
        )
    """
    # IMPORTANT: per a cada det_documento resolem una sola `sal` real (via
    # CPALBARA, amb fallback a SERIEALB) ABANS de fer JOIN amb ALBLINIA.
    # Si juntem "sal directe OR sal via SERIEALB" directament al JOIN amb
    # ALBLINIA, podem caçar una comanda DIFERENT que té el mateix número però
    # a una altra sèrie i amb articles GRA — falsos positius.
    exists_granel_sql = """
        EXISTS (
            SELECT 1
            FROM   Detcargas d  WITH (NOLOCK)
            CROSS APPLY (
                SELECT TOP 1 cp.sal_codigo
                FROM   CPALBARA cp WITH (NOLOCK)
                WHERE  cp.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
                  AND  cp.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
                  AND  ( cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2)
                         OR EXISTS (
                             SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                             WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                               AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                               AND  s.sal_codigo       = cp.sal_codigo
                         ) )
                -- Prioritat: vegeu comentari a `exists_palletizable_sql`.
                ORDER BY
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                              AND  s.sal_codigo       = cp.sal_codigo
                        ) AND (
                            SELECT COUNT(*) FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d.det_documento, 5, 2)
                        ) = 1
                        THEN 0 ELSE 1
                    END,
                    CASE WHEN RTRIM(cp.tra_codi) = RTRIM(c.tra_codi) THEN 0 ELSE 1 END,
                    CASE WHEN cp.sal_codigo = SUBSTRING(d.det_documento, 5, 2) THEN 0 ELSE 1 END
            ) sal_resolt
            JOIN   ALBLINIA  l   WITH (NOLOCK)
              ON  l.eje_ejercicio = SUBSTRING(d.det_documento, 1, 4)
              AND l.sal_codigo    = sal_resolt.sal_codigo
              AND l.cpa_albara    = SUBSTRING(d.det_documento, 7, 7)
            JOIN   ARTICLES  a   WITH (NOLOCK) ON a.art_codi = l.art_codi
            WHERE  d.eje_ejercicio = c.eje_ejercicio
              AND  d.sca_serie     = c.sca_serie
              AND  d.car_numero    = c.car_numero
              AND  d.det_tipo      IN ('A', 'P')
              AND  RTRIM(a.art_descunit) = 'GRA'
              AND  l.lin_quan      > 0
        )
    """
    # Filtre de data: a) el cas general filtra per data de sortida (o data
    # genèrica si la de sortida és null), b) excepció AGRI/Mª Soledad López,
    # que el calendari pinta per data d'arribada (vegeu calendari.js:85-95);
    # cal retornar-les també si la seva car_fecllegada cau al rang, encara que
    # la car_fecsalida sigui fora. Aquesta segona branca s'aplica només per
    # aquests transportistes, sinó alteraríem el comportament d'altres rutes.
    where_sql = """
        WHERE  (
                    COALESCE(c.car_fecsalida, c.car_fecha) >= ?
                AND COALESCE(c.car_fecsalida, c.car_fecha) <  ?
               )
           OR  (
                    c.car_fecllegada >= ?
                AND c.car_fecllegada <  ?
                AND (
                        t.tra_nom LIKE 'AGRI%'
                     OR t.tra_nom LIKE 'M% SOLEDAD LOPEZ%'
                    )
               )
    """
    where_params: list = [desde_d, fins_d, desde_d, fins_d]
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

    # Suma de kg per càrrega. Dues fonts de pes:
    #   - Sacs (tunitat Sxx): kg = lin_unit × pes per sac (S25 → 25, ...)
    #   - Granel (tunitat 'GRA'): kg = lin_quan (lin_unit és 0; el pes està al
    #     camp `lin_quan` directament en kg).
    #   - 'UNI' (palets, peces…): no compten kg.
    # IMPORTANT: per a cada det_documento resolem una sola `sal` real (via
    # CPALBARA, amb fallback a SERIEALB) ABANS d'agregar amb ALBLINIA. Si
    # juntem "sal directe OR sal via SERIEALB" al JOIN, comptaríem doble quan
    # el mateix número de comanda existeix en més d'una sèrie a ALBLINIA.
    kg_total_sql = """
        ISNULL((
            SELECT SUM(
                CASE
                    WHEN RTRIM(a.art_descunit) = 'GRA'
                    THEN l.lin_quan
                    WHEN LEFT(RTRIM(a.art_descunit), 1) = 'S'
                         AND TRY_CAST(SUBSTRING(RTRIM(a.art_descunit), 2, 10) AS FLOAT) IS NOT NULL
                    THEN l.lin_unit * TRY_CAST(SUBSTRING(RTRIM(a.art_descunit), 2, 10) AS FLOAT)
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
                -- Prioritat: vegeu comentari a `exists_palletizable_sql`.
                ORDER BY
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d2.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d2.det_documento, 5, 2)
                              AND  s.sal_codigo       = cp.sal_codigo
                        ) AND (
                            SELECT COUNT(*) FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = SUBSTRING(d2.det_documento, 1, 4)
                              AND  s.sal_SerAlbDefPed = SUBSTRING(d2.det_documento, 5, 2)
                        ) = 1
                        THEN 0 ELSE 1
                    END,
                    CASE WHEN RTRIM(cp.tra_codi) = RTRIM(c.tra_codi) THEN 0 ELSE 1 END,
                    CASE WHEN cp.sal_codigo = SUBSTRING(d2.det_documento, 5, 2) THEN 0 ELSE 1 END
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
              AND  RTRIM(a.art_descunit) <> 'UNI'
              AND  ( l.lin_unit > 0 OR l.lin_quan > 0 )
        ), 0)
    """

    # Nombre de comandes (det_documento distints) dins la càrrega. Es fa servir
    # al calendari per detectar càrregues "monocomanda" (signal de capacitat).
    num_comandes_sql = """
        ISNULL((
            SELECT COUNT(DISTINCT d3.det_documento)
            FROM   Detcargas d3 WITH (NOLOCK)
            WHERE  d3.eje_ejercicio = c.eje_ejercicio
              AND  d3.sca_serie     = c.sca_serie
              AND  d3.car_numero    = c.car_numero
              AND  d3.det_tipo      IN ('A','P')
        ), 0)
    """

    sql_items = """
        SELECT c.eje_ejercicio,
               RTRIM(c.sca_serie)   AS sca_serie,
               RTRIM(c.car_numero)  AS car_numero,
               RTRIM(c.car_descripcion) AS car_descripcion,
               c.car_fecha,
               c.car_fecsalida,
               c.car_fecllegada,
               c.car_estat,
               RTRIM(c.tra_codi)    AS tra_codi,
               RTRIM(t.tra_nom)     AS transportista,
               RTRIM(c.car_matricula)    AS car_matricula,
               RTRIM(c.car_nomconductor) AS car_nomconductor,
               c.car_pesonetocarga,
               c.car_pesoteorico,
               CAST(c.car_observaciones AS varchar(500)) AS car_observaciones,
               CAST(CASE WHEN """ + exists_palletizable_sql + """ THEN 1 ELSE 0 END AS BIT) AS palletitzable,
               CAST(CASE WHEN """ + exists_granel_sql + """ THEN 1 ELSE 0 END AS BIT) AS is_granel,
               """ + kg_total_sql + """ AS kg_total,
               """ + num_comandes_sql + """ AS num_comandes
        FROM   Cargas c WITH (NOLOCK)
        LEFT JOIN TRANS t WITH (NOLOCK) ON t.tra_codi = c.tra_codi
    """ + where_sql + """
        ORDER BY COALESCE(c.car_fecsalida, c.car_fecha) DESC, c.car_numero DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    sql_count = (
        "SELECT COUNT(*) AS n FROM Cargas c WITH (NOLOCK) "
        "LEFT JOIN TRANS t WITH (NOLOCK) ON t.tra_codi = c.tra_codi "
        + where_sql
    )

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
            "car_fecsalida_hora": r.car_fecsalida.strftime("%H:%M") if r.car_fecsalida else None,
            "car_fecllegada": r.car_fecllegada.strftime("%Y-%m-%d") if r.car_fecllegada else None,
            "car_fecllegada_hora": r.car_fecllegada.strftime("%H:%M") if r.car_fecllegada else None,
            "car_estat": r.car_estat,
            "tra_codi": r.tra_codi,
            "transportista": r.transportista or "",
            "car_matricula": r.car_matricula or "",
            "car_nomconductor": r.car_nomconductor or "",
            "car_pesonetocarga": float(r.car_pesonetocarga) if r.car_pesonetocarga is not None else 0.0,
            "car_pesoteorico": float(r.car_pesoteorico) if r.car_pesoteorico is not None else 0.0,
            "car_observaciones": (r.car_observaciones or "").strip(),
            "palletitzable": bool(r.palletitzable),
            "is_granel": bool(r.is_granel),
            "kg_total": float(r.kg_total) if r.kg_total is not None else 0.0,
            "num_comandes": int(r.num_comandes) if r.num_comandes is not None else 0,
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


def obtenir_comandes_carrega(eje: str, sca: str, car: str) -> list[dict]:
    """Q2: Comandes (Detcargas tipus 'A' o 'P') d'una càrrega.

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

    Retorna les comandes associades amb client + resum de línies (sense executar
    el motor de càlcul d'embalatges). Pensat per inspeccionar abans de seleccionar.

    Output: {
        "comandes": [
            {
                "comanda": "01/0001234",
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
    comandes = obtenir_comandes_carrega(eje, sca, car)
    if not comandes:
        return {"comandes": [], "total_sacs": 0, "total_kg": 0.0}

    conn = connectar()
    try:
        # Obté el tra_codi de la càrrega — clau per a discriminar el sal_real
        # quan hi ha múltiples candidats a CPALBARA amb el mateix número.
        tra_row = conn.execute(
            "SELECT RTRIM(tra_codi) AS tra_codi FROM Cargas WITH (NOLOCK) "
            "WHERE eje_ejercicio=? AND sca_serie=? AND car_numero=?",
            eje, sca, car,
        ).fetchone()
        carrega_tra_codi = (tra_row.tra_codi if tra_row else "") or ""

        # Pas 1: resoldre la sèrie real (sal_real) per a cada comanda.
        # Detcargas codifica la sèrie del PEDIDO (sal_SerAlbDefPed); la comanda
        # real a CPALBARA/ALBLINIA pot tenir una sèrie diferent. SERIEALB és
        # la taula de mapeig, però per a un mateix sal_pedido pot haver-hi
        # múltiples sal_real possibles. Per discriminar, prioritzem:
        #   1) match de tra_codi amb el de la càrrega (la comanda real és del
        #      mateix transportista que la càrrega).
        #   2) sal directe (cas freqüent quan no hi ha mapping a SERIEALB).
        claus_doc = [(a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"]) for a in comandes]
        values_sql = ",".join(["(CAST(? AS varchar(4)), CAST(? AS varchar(2)), CAST(? AS varchar(7)))"] * len(claus_doc))
        params_resolve: list = [carrega_tra_codi]  # primer param: tra_codi
        for k in claus_doc:
            params_resolve.extend(k)

        sql_resolve = f"""
            DECLARE @carrega_tra varchar(5) = RTRIM(?);
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
                -- Prioritat: vegeu comentari a `exists_palletizable_sql`
                -- a `llistar_carregues`. Resum:
                --   1) SERIEALB inequívoc (un sol mapping) → definitiu.
                --   2) tra_codi coincident → desempata mappings múltiples (MATAS).
                --   3) Match directe per sal_codigo → fallback.
                ORDER BY
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = d.eje_doc
                              AND  s.sal_SerAlbDefPed = d.sal_doc
                              AND  s.sal_codigo       = cp.sal_codigo
                        ) AND (
                            SELECT COUNT(*) FROM SERIEALB s WITH (NOLOCK)
                            WHERE  s.eje_ejercicio    = d.eje_doc
                              AND  s.sal_SerAlbDefPed = d.sal_doc
                        ) = 1
                        THEN 0 ELSE 1
                    END,
                    CASE WHEN RTRIM(cp.tra_codi) = @carrega_tra THEN 0 ELSE 1 END,
                    CASE WHEN cp.sal_codigo = d.sal_doc THEN 0 ELSE 1 END
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
        for a in comandes:
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
                       l.lin_unit AS sacs, l.lin_quan AS quan, RTRIM(a.art_descunit) AS tunitat
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

    # Agrupar TOTES les línies per comanda; marquem cada una amb `palletitzable`
    # (palletitzable = tunitat != UNI/GRA i sacs > 0, mateixes regles que el motor).
    # Per al càlcul de kg:
    #   - tunitat Sxx (sacs): kg = sacs × pes_per_tunitat (S25 → 25, ...)
    #   - tunitat 'GRA' (granel): kg = lin_quan (pes directe en kg)
    #   - 'UNI' o desconegut: kg = 0
    linies_per_comanda: dict[tuple[str, str, str], list[dict]] = {}
    for r in lin_rows:
        tun = (r.tunitat or "").strip()
        sacs = int(r.sacs or 0)
        quan = float(r.quan or 0)
        palletitzable = tun not in ("UNI", "GRA") and sacs > 0
        if tun == "GRA":
            kg = quan
        elif palletitzable:
            kg = sacs * _pes_per_tunitat(tun)
        else:
            kg = 0.0
        key = (r.eje_ejercicio, r.sal_codigo.strip(), r.cpa_albara.strip())
        linies_per_comanda.setdefault(key, []).append({
            "art_codi": r.art_codi.strip() if r.art_codi else "",
            "art_descrip": (r.art_descrip or "").strip(),
            "sacs": sacs,
            "quan": quan,
            "tunitat": tun,
            "kg": round(kg, 2),
            "palletitzable": palletitzable,
        })

    # Composar resposta. `total_sacs` només compta sacs palletitzables (és
    # el que el motor d'embalatges utilitzarà). `total_kg` inclou els kg de
    # qualsevol font: sacs palletitzables + granel.
    total_sacs = 0
    total_kg = 0.0
    out_com = []
    for a in comandes:
        key_doc = (a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"])
        res = resolts.get(key_doc, {"sal_real": a["sal_codigo"], "cli_codi": "", "cli_nom": "", "pobla": ""})
        cli_codi = res["cli_codi"]
        cli_nom  = res["cli_nom"]
        pobla    = res.get("pobla", "")
        key_real = (a["eje_ejercicio"], res["sal_real"], a["cpa_albara"])
        linies = linies_per_comanda.get(key_real, [])
        a_sacs = sum(l["sacs"] for l in linies if l["palletitzable"])
        a_kg = sum(l["kg"] for l in linies)
        total_sacs += a_sacs
        total_kg += a_kg
        out_com.append({
            "comanda": f"{a['sal_codigo']}/{a['cpa_albara']}",
            "det_tipo": a["det_tipo"],
            "cli_codi": cli_codi,
            "cli_nom": cli_nom,
            "pobla": pobla,
            "total_sacs": a_sacs,
            "total_kg": round(a_kg, 2),
            "linies": linies,
        })

    return {"comandes": out_com, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)}


# -----------------------------------------------------------------------------
# DEBUG TEMPORAL: diagnòstic de la resolució de sal_real per a una càrrega.
# Existeix per investigar casos on el modal mostra client/kg erronis (cas
# SIGFREDO 2026/02/0000216 ↔ 0000052). Eliminar quan el fix definitiu del
# bug estigui validat i no en quedin casos nous reportats.
# -----------------------------------------------------------------------------
def debug_resolucio_sal(eje: str, sca: str, car: str) -> dict:
    """Retorna totes les alternatives CPALBARA + SERIEALB + ALBLINIA per a
    cada comanda d'una càrrega, perquè la persona usuària pugui veure per
    què `resum_carrega` ha triat una fila concreta i quines opcions hi havia.
    """
    comandes = obtenir_comandes_carrega(eje, sca, car)

    conn = connectar()
    try:
        car_row = conn.execute(
            "SELECT RTRIM(c.tra_codi) AS tra_codi, RTRIM(t.tra_nom) AS tra_nom, "
            "       RTRIM(c.car_descripcion) AS car_descripcion, "
            "       c.car_pesoteorico, c.car_pesonetocarga, c.car_fecha "
            "FROM   Cargas c WITH (NOLOCK) "
            "LEFT JOIN TRANS t WITH (NOLOCK) ON t.tra_codi = c.tra_codi "
            "WHERE  c.eje_ejercicio=? AND c.sca_serie=? AND c.car_numero=?",
            eje, sca, car,
        ).fetchone()
        if car_row is None:
            return {"error": "carrega no trobada", "eje": eje, "sca": sca, "car": car}
        carrega_tra_codi = (car_row.tra_codi or "").strip()

        comandes_out = []
        for a in comandes:
            eje_doc = a["eje_ejercicio"]
            sal_doc = a["sal_codigo"]
            alb_doc = a["cpa_albara"]

            # Tots els candidats CPALBARA per (eje, alb), sense filtre de sal,
            # però marcant si la fila passaria el filtre actual del WHERE
            # (match directe o via SERIEALB).
            cp_rows = conn.execute(
                """
                SELECT RTRIM(cp.sal_codigo) AS sal_codigo,
                       RTRIM(cp.cli_codi)   AS cli_codi,
                       RTRIM(c.cli_nom)     AS cli_nom,
                       RTRIM(cp.tra_codi)   AS tra_codi,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM SERIEALB s WITH (NOLOCK)
                           WHERE  s.eje_ejercicio    = ?
                             AND  s.sal_SerAlbDefPed = ?
                             AND  s.sal_codigo       = cp.sal_codigo
                       ) THEN 1 ELSE 0 END AS via_seriealb
                FROM   CPALBARA cp WITH (NOLOCK)
                LEFT JOIN CLIENTS c WITH (NOLOCK) ON c.cli_codi = cp.cli_codi
                WHERE  cp.eje_ejercicio = ?
                  AND  cp.cpa_albara    = ?
                ORDER  BY cp.sal_codigo
                """,
                eje_doc, sal_doc, eje_doc, alb_doc,
            ).fetchall()

            cpalbara_candidats = []
            for r in cp_rows:
                sal_c = (r.sal_codigo or "").strip()
                match_directe = sal_c == sal_doc
                via_seria = bool(r.via_seriealb)
                cpalbara_candidats.append({
                    "sal_codigo": sal_c,
                    "cli_codi": (r.cli_codi or "").strip(),
                    "cli_nom":  (r.cli_nom  or "").strip(),
                    "tra_codi": (r.tra_codi or "").strip(),
                    "match_directe": match_directe,
                    "match_tra": (r.tra_codi or "").strip() == carrega_tra_codi and carrega_tra_codi != "",
                    "via_seriealb": via_seria,
                    "passa_where": match_directe or via_seria,
                })

            # Mappings SERIEALB(eje, sal_SerAlbDefPed=sal_doc)
            sa_rows = conn.execute(
                "SELECT RTRIM(sal_SerAlbDefPed) AS pedido, RTRIM(sal_codigo) AS sal_codigo "
                "FROM   SERIEALB WITH (NOLOCK) "
                "WHERE  eje_ejercicio=? AND sal_SerAlbDefPed=? "
                "ORDER  BY sal_codigo",
                eje_doc, sal_doc,
            ).fetchall()
            seriealb_mappings = [
                {"sal_SerAlbDefPed": (r.pedido or "").strip(), "sal_codigo": (r.sal_codigo or "").strip()}
                for r in sa_rows
            ]

            # Línies ALBLINIA per (eje, alb) — totes les sales que tenen línies
            # per a aquest número d'albarà. Agrupades per sal_codigo amb kg
            # estimat (mateixa fórmula que kg_total_sql).
            lin_rows = conn.execute(
                """
                SELECT RTRIM(l.sal_codigo)  AS sal_codigo,
                       RTRIM(l.art_codi)    AS art_codi,
                       RTRIM(a.art_descrip) AS art_descrip,
                       RTRIM(a.art_descunit) AS tunitat,
                       l.lin_unit, l.lin_quan
                FROM   ALBLINIA l WITH (NOLOCK)
                LEFT JOIN ARTICLES a WITH (NOLOCK) ON a.art_codi = l.art_codi
                WHERE  l.eje_ejercicio = ?
                  AND  l.cpa_albara    = ?
                ORDER  BY l.sal_codigo, l.lin_linia
                """,
                eje_doc, alb_doc,
            ).fetchall()
            alblinia_per_sal: dict[str, dict] = {}
            for r in lin_rows:
                tun = (r.tunitat or "").strip()
                unit = int(r.lin_unit or 0)
                quan = float(r.lin_quan or 0)
                if tun == "GRA":
                    kg = quan
                elif tun.startswith("S"):
                    kg = unit * _pes_per_tunitat(tun)
                else:
                    kg = 0.0
                key = (r.sal_codigo or "").strip()
                bucket = alblinia_per_sal.setdefault(key, {"linies": [], "kg_total": 0.0})
                bucket["linies"].append({
                    "art_codi": (r.art_codi or "").strip(),
                    "art_descrip": (r.art_descrip or "").strip(),
                    "tunitat": tun,
                    "lin_unit": unit,
                    "lin_quan": quan,
                    "kg_estimat": round(kg, 2),
                })
                bucket["kg_total"] += kg
            for k, v in alblinia_per_sal.items():
                v["kg_total"] = round(v["kg_total"], 2)

            # Simula l'ORDER BY actual de resum_carrega/kg_total_sql:
            #   1) SERIEALB inequívoc: via_seriealb=true I el mapping és únic
            #   2) tra_codi coincident
            #   3) sal_codigo coincident amb sal_doc
            # Només sobre files que "passen el WHERE".
            seriealb_unic = len(seriealb_mappings) == 1
            candidats_validos = [c for c in cpalbara_candidats if c["passa_where"]]
            candidats_validos.sort(key=lambda c: (
                0 if (c["via_seriealb"] and seriealb_unic) else 1,
                0 if c["match_tra"] else 1,
                0 if c["match_directe"] else 1,
            ))
            triat = candidats_validos[0] if candidats_validos else None
            if triat is None:
                escolliria = {"sal_codigo": None, "rao": "cap candidat passa el WHERE"}
            else:
                if triat["via_seriealb"] and seriealb_unic:
                    rao = "SERIEALB inequívoc (mapping únic, prioritat 1)"
                elif triat["match_tra"]:
                    rao = "tra_codi coincident (prioritat 2)"
                elif triat["match_directe"]:
                    rao = "sal_codigo coincident (prioritat 3)"
                else:
                    rao = "primer candidat (cap criteri coincideix)"
                escolliria = {
                    "sal_codigo": triat["sal_codigo"],
                    "cli_codi": triat["cli_codi"],
                    "cli_nom": triat["cli_nom"],
                    "rao": rao,
                }

            comandes_out.append({
                "det_documento": f"{eje_doc}{sal_doc}{alb_doc}",
                "eje_doc": eje_doc,
                "sal_doc": sal_doc,
                "alb_doc": alb_doc,
                "det_tipo": a["det_tipo"],
                "cpalbara_candidats": cpalbara_candidats,
                "seriealb_mappings": seriealb_mappings,
                "alblinia_per_sal": alblinia_per_sal,
                "escolliria_actualment": escolliria,
            })
    finally:
        conn.close()

    return {
        "carrega": {
            "eje": eje, "sca": sca, "car": car,
            "tra_codi": carrega_tra_codi,
            "tra_nom": (car_row.tra_nom or "").strip() if car_row.tra_nom else "",
            "car_descripcion": (car_row.car_descripcion or "").strip() if car_row.car_descripcion else "",
            "car_pesoteorico": float(car_row.car_pesoteorico) if car_row.car_pesoteorico is not None else 0.0,
            "car_pesonetocarga": float(car_row.car_pesonetocarga) if car_row.car_pesonetocarga is not None else 0.0,
            "car_fecha": car_row.car_fecha.strftime("%Y-%m-%d") if car_row.car_fecha else None,
        },
        "comandes": comandes_out,
    }
