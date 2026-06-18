-- Migracio: afegir tracabilitat d'usuari a agrupacions i productes_preparats.
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc sobre una BD ja migrada.

ALTER TABLE agrupacions
    ADD COLUMN IF NOT EXISTS created_by_id INTEGER
        REFERENCES usuaris(id) ON DELETE SET NULL;

ALTER TABLE productes_preparats
    ADD COLUMN IF NOT EXISTS marcat_per_id INTEGER
        REFERENCES usuaris(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agrupacions_created_by
    ON agrupacions (created_by_id) WHERE created_by_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_productes_preparats_marcat_per
    ON productes_preparats (marcat_per_id) WHERE marcat_per_id IS NOT NULL;
