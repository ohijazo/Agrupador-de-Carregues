-- Migracio: data planificada de carrega resistent a la sobreescriptura de KAIS.
--
-- Problema: quan un operari canvia l'estat d'una carrega a "Sortida" (car_estat=2),
-- KAIS sobreescriu car_fecsalida amb la data/hora exactes del canvi d'estat. Aixo
-- fa que la carrega "salti" de dia al calendari (cas reportat 2026-06-29 amb la
-- carrega 2026/01/0002367 planificada per al 25/06 i sobreescrita a 26/06).
--
-- Solucio: dues taules locals a PostgreSQL.
--   - kais_carrega_snapshot  : captura automatica de car_fecsalida la primera
--                              vegada que veiem la carrega amb car_estat != 2.
--                              S'actualitza mentre l'estat segueix sent != 2.
--   - kais_carrega_override  : override manual (admin) per a casos en que el
--                              snapshot no es va captar a temps (ex. carregues
--                              ja en Sortida abans del deploy d'aquesta feature).
--
-- Precedencia al lookup: override > snapshot > valor live de KAIS.
--
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc.

CREATE TABLE IF NOT EXISTS kais_carrega_snapshot (
    carrega_id              TEXT         PRIMARY KEY,
    car_fecsalida_original  TIMESTAMP    NOT NULL,
    car_estat_snapshot      INTEGER      NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kais_carrega_snapshot_updated
    ON kais_carrega_snapshot (updated_at DESC);

CREATE TABLE IF NOT EXISTS kais_carrega_override (
    carrega_id              TEXT         PRIMARY KEY,
    car_fecsalida_override  TIMESTAMP    NOT NULL,
    motiu                   TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_id           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_kais_carrega_override_updated
    ON kais_carrega_override (updated_at DESC);

DO $$ BEGIN
    ALTER TABLE kais_carrega_override
        ADD CONSTRAINT fk_kais_carrega_override_created_by
        FOREIGN KEY (created_by_id) REFERENCES usuaris(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
