-- Migracio: afegir suport a finalitzacio manual d'agrupacions.
-- Idempotent (IF NOT EXISTS / DO blocks): es pot aplicar sense risc.

ALTER TABLE agrupacions
    ADD COLUMN IF NOT EXISTS finalitzada_manual_at TIMESTAMPTZ;

ALTER TABLE agrupacions
    ADD COLUMN IF NOT EXISTS finalitzada_manual_per_id INTEGER;

DO $$ BEGIN
    ALTER TABLE agrupacions
        ADD CONSTRAINT fk_agrupacions_finalitzada_manual_per
        FOREIGN KEY (finalitzada_manual_per_id) REFERENCES usuaris(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_agrupacions_finalitzada_manual
    ON agrupacions (finalitzada_manual_at) WHERE finalitzada_manual_at IS NOT NULL;

-- Vista actualitzada: una agrupacio es finalitzada si esta tancada manualment
-- o si tots els seus productes estan marcats com a preparats.
CREATE OR REPLACE VIEW v_agrupacions_estat AS
SELECT
    a.id,
    a.nom,
    a.ts,
    a.plantilla,
    a.n_productes,
    COALESCE(p.n_preparats, 0) AS n_preparats,
    (
        a.finalitzada_manual_at IS NOT NULL
        OR (a.n_productes > 0 AND COALESCE(p.n_preparats, 0) >= a.n_productes)
    ) AS finalitzada,
    a.finalitzada_manual_at,
    a.finalitzada_manual_per_id
FROM agrupacions a
LEFT JOIN (
    SELECT agrupacio_id, COUNT(*)::INTEGER AS n_preparats
    FROM productes_preparats
    GROUP BY agrupacio_id
) p ON p.agrupacio_id = a.id;
