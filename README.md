# Agrupació de Càrregues

Aplicació interna per consolidar embalatges de múltiples càrregues de transport en un únic resum per producte, amb impressió pensada per al treballador del magatzem.

## Qui la fa servir

- **Operador d'oficina** — cerca càrregues per data/transportista, en selecciona unes quantes, i obté l'agrupació amb el detall de palets per article i transport (vista a `http://<servidor>:5002/`).
- **Preparador del magatzem** — obre una agrupació desada des d'una tablet a `/magatzem`, veu els articles a preparar amb cards grans i marca cada producte com a "Preparat" quan està fet.

## Què fa

1. Llistat de càrregues amb filtres (rang dates, multi-transportista, estat de càrrega, article que conté).
2. Agrupació: per cada selecció recalcula tot l'embalatge cridant `motor.calcular_embalatges()` de l'app germana `preparacioComandesVenda`.
3. Resum visual: KPIs, palets físics per tipus amb desglós per transport, taula de productes amb cercles colorits per càrrega, impressió en format pensat per al magatzem.
4. Persistència: agrupacions desades a `data/agrupacions/<uuid>.json` per recuperar-les setmanes després.

## Requisits

- Python 3.10+
- **SQL Server** (només lectura, ERP) — la connexió la dóna l'app germana via `PREPARACIO_PATH/.env`.
- Drivers ODBC 18 per SQL Server.
- **PostgreSQL 12+** (persistència local de les agrupacions desades).
- Node.js 18+ (només per a córrer tests JS).

## Variables d'entorn

L'app llegeix primer `./.env` local i després `PREPARACIO_PATH/.env` (app germana) com a fallback. Mira `.env.example` per la llista completa:

```
# SQL Server (ERP, lectura)
SQL_SERVER=servidor\instancia
SQL_DATABASE=nom_bd
SQL_USER=usuari
SQL_PASSWORD=secret
PREPARACIO_PATH=P:\preparacioComandesVenda

# PostgreSQL (persistència agrupacions)
PG_HOST=labfc.agri-energia.local
PG_PORT=5432
PG_DATABASE=agrupaciocarregues
PG_USER=app_agrupacions
PG_PASSWORD=...
```

## Setup PostgreSQL (per IT, una sola vegada)

```sql
-- Connectat com a admin
CREATE DATABASE agrupaciocarregues;
CREATE USER app_agrupacions WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE agrupaciocarregues TO app_agrupacions;

-- Després, connectat com a app_agrupacions a la BD nova:
\i db/schema.sql
```

Si hi ha agrupacions desades antigues a `data/agrupacions/*.json`, importa-les:

```bash
python migrate_json_to_pg.py --backup
```

## Com arrencar

```bash
pip install -r requirements.txt
python app.py
```

Per defecte escolta a `http://127.0.0.1:5001`. Si el port és ocupat, ajusta el final d'`app.py`.

## Endpoints HTTP

| Mètode | Ruta | Què fa |
|---|---|---|
| GET | `/` | Pàgina principal (oficina) |
| GET | `/magatzem` | Llistat d'agrupacions desades (vista tàctil) |
| GET | `/magatzem/<id>` | Pantalla de preparació al magatzem |
| GET | `/health` | Estat BD + motor d'embalatges |
| GET | `/api/transportistes` | Llista de transportistes |
| GET | `/api/estats-carregues` | Estats distints de càrrega |
| GET | `/api/articles?q=…` | Autocompletar articles (mín 2 caràcters) |
| GET | `/api/carregues?desde&fins&tra_codi[]&estat&art_codi&limit&offset` | Llista paginada `{items,total,limit,offset}` |
| GET | `/api/carrega-detall?eje&sca&car` | Preview albarans + línies d'una càrrega |
| POST | `/api/agrupar` | Recalcula agrupació (body: `{carregues: [...]}`) |
| GET | `/api/agrupacions` | Llista resumida d'agrupacions desades |
| POST | `/api/agrupacions` | Desa (body: `{nom, carregues, resultat}`) |
| GET | `/api/agrupacions/<id>` | Contingut sencer d'una agrupació desada |
| DELETE | `/api/agrupacions/<id>` | Elimina |
| PATCH | `/api/agrupacions/<id>/producte` | Marca/desmarca producte preparat (body: `{art_codi, preparat}`) |

## Estructura del repo

```
agrupacioCarregues/
├── app.py                      # Flask app + rutes + headers seguretat + logging rotat
├── valida.py                   # Validadors d'inputs (dates, codis, llistes)
├── agregador.py                # Lògica d'agrupació (orquestra el motor germà)
├── consultes_carregues.py      # Queries SQL (càrregues, albarans, articles, estats)
├── agrupacions_store.py        # CRUD a PostgreSQL de les agrupacions desades
├── db.py                       # Capa de connexió a PostgreSQL (pool psycopg)
├── db/schema.sql               # Schema PostgreSQL (3 taules + 1 vista)
├── migrate_json_to_pg.py       # Migrador one-shot dels JSON antics a PG
├── models_agrupacio.py         # Dataclasses del resultat
├── requirements.txt
├── .env.example
├── templates/
│   ├── index.html              # Pàgina principal
│   ├── ajuda.html              # Manual d'usuari (/ajuda)
│   ├── magatzem_llista.html    # Llistat al magatzem
│   └── magatzem_prep.html      # Preparació al magatzem
├── static/
│   ├── css/style.css
│   ├── css/magatzem.css
│   ├── js/fmt.js               # Helpers de format compartits (testable a Node)
│   ├── js/dialogs.js           # mostrarConfirmacio / mostrarInput
│   ├── js/app.js               # Lògica de la pàgina d'oficina
│   └── js/magatzem.js          # Lògica de la pàgina de magatzem
└── tests/
    ├── conftest.py             # Fixture compartida (PG test BD)
    ├── test_validacions.py     # Validadors (no necessiten PG)
    ├── test_agregador.py       # Motor mockejat (no necessiten PG)
    ├── test_agrupacions_store.py  # Requereix PG_HOST configurat
    ├── test_endpoints.py       # Requereix PG_HOST configurat
    └── test_format.mjs         # Tests JS (node --test)
```

## Tests

```bash
# Tests Python — els d'store i endpoints requereixen PG_HOST configurat al .env
# (si no, fan skip automàticament)
python -m pytest tests/ -q

# Tests JS (helpers de format)
node --test tests/test_format.mjs
```

Per al CI o desenvolupament local, crea una BD test separada (`agrupaciocarregues_test`) i exporta les variables `PG_*` apuntant-hi abans de córrer pytest.

## Drece­res de teclat (oficina)

- `Enter` als filtres → Cerca
- `Ctrl+A` dins la llista → Marca totes
- `Shift+clic` en una checkbox → Selecciona rang
- Clic a la fila → Commuta selecció
- `Esc` → Tanca avisos / cancel·la fetch / tanca diàleg

## Logging

Es desa a `agrupacio.log` amb rotació (5 fitxers de 2MB). Cada agrupació genera una línia `audit agrupar ip=… carregues=… productes=… palets=…`.

## Per a més detall de l'arquitectura

Vegeu [ARCHITECTURE.md](./ARCHITECTURE.md).
