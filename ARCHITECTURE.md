# Arquitectura

## Visió general

Aplicació Flask monolítica que llegeix dades d'un SQL Server (només lectura) i orquestra el càlcul d'embalatges delegat a una app germana (`preparacioComandesVenda`) carregada via `sys.path`.

```
┌──────────────────────┐         ┌────────────────────┐
│  Navegador           │         │  Tablet (magatzem) │
│  http://host:5002/   │         │  /magatzem/<id>    │
└──────────┬───────────┘         └────────┬───────────┘
           │ HTTP                          │ HTTP
           ▼                                ▼
┌─────────────────────────────────────────────────────┐
│  Flask (app.py)                                     │
│  ├─ valida.py        validació inputs               │
│  ├─ Headers seguretat (CSP, X-Frame, …)             │
│  └─ Logging rotat + auditoria                       │
└──────┬──────────────────────────┬───────────────────┘
       │                           │
       ▼                           ▼
┌──────────────────────┐  ┌──────────────────────────────┐
│ consultes_carregues  │  │ agregador.py                 │
│ • llistar_carregues  │  │  ↓ (sys.path)                │
│ • llistar_estats     │  │ motor.calcular_embalatges()  │
│ • cercar_articles    │  │ (app germana)                │
│ • resum_carrega      │  └──────────────────────────────┘
└──────┬───────────────┘                  │
       │ pyodbc                            │ llegeix
       ▼                                   ▼
┌────────────────────────────────────────────────┐
│ SQL Server (ApplicationIntent=ReadOnly)         │
│ Cargas · Detcargas · CPALBARA · ALBLINIA …      │
└────────────────────────────────────────────────┘

  Persistència local:  data/agrupacions/<uuid>.json
                       (agrupacions_store.py)
```

## Components

### Backend

- **`app.py`** — Punt d'entrada Flask.
  - Carrega `.env` local i `PREPARACIO_PATH/.env` (en aquest ordre).
  - Injecta `PREPARACIO_PATH` a `sys.path` perquè `agregador.py` pugui importar `motor` i `models`.
  - Configura `RotatingFileHandler` (2MB × 5).
  - `@app.after_request` afegeix headers de seguretat (CSP, X-Frame-Options, etc.).
  - Errors gestionats: `pyodbc.Error` → 503, `ModuleNotFoundError` → 503, resta → 500. Missatges interns només al log.

- **`valida.py`** — Validadors purs (sense efectes laterals). Cada funció retorna `(valor, err)`.

- **`consultes_carregues.py`** — Totes les queries SQL parametritzades. Una connexió per request, tancada en `finally`. `ApplicationIntent=ReadOnly`.

- **`agregador.py`** — Per cada càrrega seleccionada:
  1. Llegeix els albarans (Detcargas amb `det_tipo IN ('A','P')`).
  2. Per cada albarà crida `motor.calcular_embalatges(sal, cpa)` de l'app germana — l'import és diferit i cau a `ModuleNotFoundError → 503` si l'app germana no és disponible.
  3. Acumula: `{producte → {càrrega → palets}}` + `{tipus_palet → {càrrega → quantitat}}`.
  4. Serialitza a JSON pla per al frontend.

- **`agrupacions_store.py`** — CRUD de fitxers JSON a `data/agrupacions/`. ID = UUID hex; nom + carregues + resultat cachejat + `productes_preparats` (llista d'`art_codi` marcats com fets pel preparador).

### Frontend

Vanilla JS sense framework. Dos modes:

- **Oficina (`/`, `templates/index.html`, `static/js/app.js`)**:
  - Estat `state` global dins una IIFE.
  - Re-render diff per `carrega_id` a la taula de càrregues per evitar reconstruir el `<tbody>`.
  - Event delegation al `<tbody>`: un sol listener despatxa per `data-role`.
  - Component `crearMultiSelect(...)` reutilitzable (chips + dropdown cercable + teclat).
  - Modal de resultat (`<dialog>`) amb imprès personalitzat: cada palet `N×M` colorit pel transport.
  - Cache local de detalls expandits (`detallCache` Map).

- **Magatzem (`/magatzem`, `static/js/magatzem.js`)**:
  - Vista llista d'agrupacions desades (URL pròpia per fer-la usable des de la tablet del magatzem).
  - Vista preparació (`/magatzem/<id>`): cards grans amb checkbox "Preparat" de 64×64.
  - Polling cada 5s mentre la pestanya és visible per reflectir canvis fets des d'altres dispositius.
  - Pintat optimista al togglar: aplica immediatament a la UI i fa rollback si el `PATCH` falla.

- **`static/js/fmt.js`** — `fmtData` i `fmtDataHora` exportats com a globals i com a CommonJS perquè `tests/test_format.mjs` els pugui importar des de Node sense duplicar codi.

## Decisions de disseny clau

- **No hi ha framework** — l'app és prou petita per mantenir-se vanilla; afegir React/Vue introduiria build pipeline i complexitat injustificada.
- **El motor d'embalatges no es duplica** — depenem de l'app germana via `sys.path`. El cost és l'acoblament; el benefici és no replicar la lògica d'embalatges.
- **Connexió per request** — sense pool. Volum moderat (< ~100 req/min); el pool no aporta a aquesta escala i simplifica el manteniment.
- **Agrupacions desades en JSON** — sense BD pròpia. Lectura/escriptura atòmica i transportable. ID UUID per evitar col·lisions.
- **Estat "preparat" al servidor** — els canvis des de la tablet són immediatament visibles per oficina (i viceversa) amb polling 5s. Sense WebSockets perquè no cal la latència.

## Errors i robustesa

- Validació estricta a tots els endpoints — qualsevol formulari deformat retorna 400 amb un missatge clar abans de tocar SQL.
- Errors SQL es retornen com a "Error de connexió amb la base de dades" — el detall queda al log.
- Si `motor.py` no es pot importar, l'agrupació retorna 503 "Motor no disponible".
- El frontend mostra toasts al carregar si `/health` informa que alguna dependència està KO.

## Tests

- `tests/test_validacions.py` cobreix tot `valida.py` (28 casos).
- `tests/test_format.mjs` cobreix els helpers de format JS (14 casos).
- L'agregador i `motor` no tenen tests automatitzats (el motor és codi de l'app germana; els tests existeixen allà).

## Coses fora d'abast

- Autenticació / login.
- WSGI de producció (waitress, gunicorn) i registre com a servei.
- Internacionalització — només català.
- Multi-empresa / multi-magatzem.
- Generació de PDF al backend (la impressió la fa el navegador via `@media print`).
