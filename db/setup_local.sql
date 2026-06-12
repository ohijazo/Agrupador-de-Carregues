-- Setup local de la BD per a desenvolupament/proves.
-- Executar com a 'postgres' (superuser) des de pgAdmin → Query Tool.
--
-- Crea: BD 'agrupaciocarregues_dev' + usuari 'app_agrupacions' amb
-- la contrasenya que esculls (canvia 'CANVIA_AQUESTA_CONTRASENYA').

-- 1. Crea l'usuari (només si no existeix)
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_agrupacions') THEN
      CREATE ROLE app_agrupacions WITH LOGIN PASSWORD 'CANVIA_AQUESTA_CONTRASENYA';
   END IF;
END
$$;

-- 2. Crea la BD
CREATE DATABASE agrupaciocarregues_dev OWNER app_agrupacions ENCODING 'UTF8';

-- 3. Permisos
GRANT ALL PRIVILEGES ON DATABASE agrupaciocarregues_dev TO app_agrupacions;

-- 4. Ara connecta't a la BD nova i executa db/schema.sql:
--    A pgAdmin: clic dret a 'agrupaciocarregues_dev' → Query Tool
--    Després obre db/schema.sql i executa'l (F5).
