-- Esquema d'agrupacioCarregues a PostgreSQL.
-- Compatible amb PostgreSQL 12 o superior.
--
-- Ús al setup:
--   psql -h <host> -U <admin> -d <db> -f schema.sql

-- ---------------------------------------------------------------------------
-- Taula principal: una fila per agrupació desada
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agrupacions (
    id                    UUID         PRIMARY KEY,
    nom                   TEXT         NOT NULL,
    ts                    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    plantilla             BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Camps resum precalculats per a llistats ràpids (sense parsejar JSONB)
    n_carregues           INTEGER      NOT NULL DEFAULT 0,
    n_productes           INTEGER      NOT NULL DEFAULT 0,
    total_palets_fisics   INTEGER      NOT NULL DEFAULT 0,
    total_sacs            INTEGER      NOT NULL DEFAULT 0,
    -- Cossos grans com a JSONB (input + resultat motor)
    carregues             JSONB        NOT NULL,
    resultat              JSONB        NOT NULL,
    plantilla_meta        JSONB        -- només si plantilla = TRUE
);

CREATE INDEX IF NOT EXISTS idx_agrupacions_ts          ON agrupacions (ts DESC);
CREATE INDEX IF NOT EXISTS idx_agrupacions_plantilla   ON agrupacions (plantilla) WHERE plantilla = TRUE;

-- ---------------------------------------------------------------------------
-- Productes preparats per agrupació (estat operari magatzem)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS productes_preparats (
    agrupacio_id          UUID         NOT NULL REFERENCES agrupacions(id) ON DELETE CASCADE,
    art_codi              TEXT         NOT NULL,
    marcat_ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    marcat_ip             TEXT,
    PRIMARY KEY (agrupacio_id, art_codi)
);

CREATE INDEX IF NOT EXISTS idx_productes_preparats_agrupacio ON productes_preparats (agrupacio_id);

-- ---------------------------------------------------------------------------
-- Índex desnormalitzat: quines càrregues són en quina agrupació
-- (permet trobar tota agrupació d'una càrrega en O(1) sense parsejar JSONB)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agrupacio_carregues (
    agrupacio_id          UUID         NOT NULL REFERENCES agrupacions(id) ON DELETE CASCADE,
    carrega_id            TEXT         NOT NULL,
    tra_codi              TEXT,
    PRIMARY KEY (agrupacio_id, carrega_id)
);

CREATE INDEX IF NOT EXISTS idx_agrupacio_carregues_carrega ON agrupacio_carregues (carrega_id);
CREATE INDEX IF NOT EXISTS idx_agrupacio_carregues_tra     ON agrupacio_carregues (tra_codi);

-- ---------------------------------------------------------------------------
-- Vista: una agrupació es considera "finalitzada" quan tots els productes
-- del resultat ja estan marcats com preparats.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_agrupacions_estat AS
SELECT
    a.id,
    a.nom,
    a.ts,
    a.plantilla,
    a.n_productes,
    COALESCE(p.n_preparats, 0) AS n_preparats,
    (a.n_productes > 0 AND COALESCE(p.n_preparats, 0) >= a.n_productes) AS finalitzada
FROM agrupacions a
LEFT JOIN (
    SELECT agrupacio_id, COUNT(*)::INTEGER AS n_preparats
    FROM productes_preparats
    GROUP BY agrupacio_id
) p ON p.agrupacio_id = a.id;
