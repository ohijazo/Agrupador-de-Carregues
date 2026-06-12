-- =====================================================================
-- Setup local de la BD per a desenvolupament/proves.
-- Executar com a 'postgres' (superuser) des de pgAdmin → Query Tool.
--
-- IMPORTANT: pgAdmin embolcalla diverses sentències en una transacció
-- i CREATE DATABASE no pot anar dins d'una transacció. Per això cal
-- executar cada BLOC per separat:
--    1) Selecciona el text del BLOC (entre les línies "-- BLOC N --")
--    2) Prem F5
--    3) Passa al següent bloc
--
-- Abans de començar: canvia 'CANVIA_AQUESTA_CONTRASENYA' al BLOC 1
-- per la contrasenya que vulguis per l'usuari app_agrupacions.
-- =====================================================================


-- =====================================================================
-- BLOC 1 — Crea l'usuari app_agrupacions (si no existeix)
-- =====================================================================
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_agrupacions') THEN
      CREATE ROLE app_agrupacions WITH LOGIN PASSWORD 'CANVIA_AQUESTA_CONTRASENYA';
   END IF;
END
$$;


-- =====================================================================
-- BLOC 2 — Crea la BD agrupaciocarregues_dev
-- =====================================================================
CREATE DATABASE agrupaciocarregues_dev OWNER app_agrupacions ENCODING 'UTF8';


-- =====================================================================
-- BLOC 3 — Permisos sobre la BD
-- =====================================================================
GRANT ALL PRIVILEGES ON DATABASE agrupaciocarregues_dev TO app_agrupacions;


-- =====================================================================
-- SEGÜENT PAS:
-- A pgAdmin, fes clic dret a 'agrupaciocarregues_dev' → Query Tool,
-- obre db/schema.sql i executa'l (F5) per crear les 3 taules + 1 vista.
-- =====================================================================


-- =====================================================================
-- BLOC 4 — Permisos sobre les taules (executar DESPRÉS de schema.sql)
--
-- IMPORTANT: connectat a la BD 'agrupaciocarregues_dev' (NO a 'postgres')
-- i com a superuser 'postgres'. Si has executat schema.sql com a postgres,
-- les taules pertanyen a ell i app_agrupacions no hi pot ni llegir.
-- =====================================================================
GRANT USAGE ON SCHEMA public TO app_agrupacions;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO app_agrupacions;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_agrupacions;

-- Per a futures taules/seqüències creades al schema public:
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO app_agrupacions;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO app_agrupacions;
