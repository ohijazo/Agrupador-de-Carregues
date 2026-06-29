# scripts/

## smoke.py

Smoke-test post-deploy. Executa la cadena d'endpoints crítics que els
operaris fan servir cada dia: `/health`, `/api/carregues`, `/api/agrupar`.

Detecta automàticament regressions del tipus que va afectar la producció el
28/06/2026 (la incidència "Error calculant: 'str' object has no attribute
'isoformat'"), inspeccionant els missatges de les incidències retornades per
`/api/agrupar`.

### Ús bàsic

```bash
# Contra local (default: http://localhost:50004)
python scripts/smoke.py

# Contra producció
AGRUPACIO_BASE_URL=http://agrupacions.agrienergia.local python scripts/smoke.py

# Amb auth activada
AGRUPACIO_BASE_URL=... SMOKE_USER=admin SMOKE_PASSWORD=xxx python scripts/smoke.py
```

### Quan executar-lo

Cada cop que es fa un `git pull` + restart al servidor, abans que arribi un
operari. La rutina del manual de desplegament queda actualitzada així:

```bash
sudo -u www-data git -C /var/www/comandes-venda pull
sudo systemctl restart comandes-venda.service
sudo systemctl restart agrupacio-carregues.service

# NOU pas:
python /var/www/agrupacio-carregues/scripts/smoke.py
```

Si retorna `exit 1`, no notifiquis als operaris fins haver investigat.

### Codis de sortida

- `0` → tots els passos verds, segur per a operaris.
- `1` → algun pas ha fallat. Llegir l'output per saber quin.

### Variables d'entorn

| Variable | Default | Descripció |
|----------|---------|-----------|
| `AGRUPACIO_BASE_URL` | `http://localhost:50004` | URL base de l'app |
| `SMOKE_USER` | – | Usuari per login (només si AUTH_ENABLED a l'app) |
| `SMOKE_PASSWORD` | – | Contrasenya |
| `SMOKE_DESDE` | avui − 30d | Inici del rang de càrregues a llistar |
| `SMOKE_FINS` | avui + 7d | Fi del rang |
| `SMOKE_MAX_CARREGUES` | `1` | Quantes càrregues recents passar a `/api/agrupar` |

### Què comprova exactament

1. `/health` retorna `ok:true` per `db` (SQL Server), `pg` (PostgreSQL) i `motor`.
2. `/api/carregues` retorna ≥1 ítem amb els camps obligatoris de l'agrupador.
3. `/api/agrupar` amb 1 càrrega real:
   - Resposta 200 (o 409 si ja està agrupada — també OK).
   - **Cap incidència** amb missatge contenint `isoformat`, `AttributeError`
     o `TypeError`. Aquest és exactament el patró del 28/06.
