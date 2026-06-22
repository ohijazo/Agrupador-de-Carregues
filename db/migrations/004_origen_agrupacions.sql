-- Migracio: distingir agrupacions "desades" (manual) de "impreses" (auto-desat
-- quan l'operari prem Imprimir sense haver desat). Aixi el gerent pot veure
-- a /control totes les agrupacions que els operaris han fet, encara que no
-- les hagin desat explicitament.
-- Idempotent (IF NOT EXISTS / DO blocks): es pot aplicar sense risc.

ALTER TABLE agrupacions
    ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'desada';

DO $$ BEGIN
    ALTER TABLE agrupacions
        ADD CONSTRAINT agrupacions_origen_chk
        CHECK (origen IN ('desada', 'impresa'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_agrupacions_origen_ts
    ON agrupacions (origen, ts DESC);
