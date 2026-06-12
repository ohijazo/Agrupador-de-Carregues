"""Store senzill d'agrupacions desades en fitxers JSON dins `data/agrupacions/`.

Cada agrupació té: id (uuid), nom, ts (ISO), carregues (entrada), resultat (resposta),
i opcionalment estats per producte (per al mode magatzem futur).

Concurrència:
  - Modificacions (marca_producte, reset_preparats) protegides amb file lock
    exclusiu (portalocker) per evitar pèrdua d'escriptures si dos clients
    actuen al mateix moment (per exemple dues tablets de magatzem).
  - L'índex en memòria està protegit per un threading.Lock perquè dins d'un
    mateix procés diversos workers WSGI o el polling no calculin alhora.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from threading import Lock
from typing import Callable

import portalocker

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agrupacions")
_RE_ID = re.compile(r"^[a-f0-9-]{8,40}$")

# Cache de l'índex carrega_id -> [agrupacions]. Es recalcula quan canvia
# el fingerprint del directori (noms+mtime+mida dels JSON).
_index_cache: dict[str, list[dict]] | None = None
_index_cache_key: tuple | None = None
_index_lock = Lock()


def _invalidar_index() -> None:
    global _index_cache, _index_cache_key
    with _index_lock:
        _index_cache = None
        _index_cache_key = None


def _ensure_dir() -> None:
    os.makedirs(_DIR, exist_ok=True)


def _path(id_: str) -> str:
    if not _RE_ID.fullmatch(id_):
        raise ValueError("id invàlid")
    return os.path.join(_DIR, f"{id_}.json")


def guardar(nom: str, carregues: list[dict], resultat: dict) -> dict:
    _ensure_dir()
    id_ = uuid.uuid4().hex
    ts = datetime.now().isoformat(timespec="seconds")
    nom = (nom or "").strip() or f"Agrupació {ts}"
    obj = {
        "id": id_,
        "nom": nom[:80],
        "ts": ts,
        "carregues": carregues,
        "resultat": resultat,
        "productes_preparats": [],
    }
    # Nou fitxer (uuid únic): no cal lock; obrim en "x" per ser estrictes
    # contra col·lisions impossibles però defensives.
    with open(_path(id_), "x", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    _invalidar_index()
    return _resumir(obj)


def llistar() -> list[dict]:
    _ensure_dir()
    out = []
    for fname in os.listdir(_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_DIR, fname), encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        out.append(_resumir(obj))
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def obtenir(id_: str) -> dict | None:
    try:
        with open(_path(id_), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def eliminar(id_: str) -> bool:
    try:
        os.remove(_path(id_))
        _invalidar_index()
        return True
    except (FileNotFoundError, ValueError):
        return False


def _modificar_amb_lock(id_: str, mutator: Callable[[dict], None]) -> dict | None:
    """Obre el JSON amb lock exclusiu, l'aplica `mutator(obj)` i el reescriu.

    Retorna l'objecte modificat, o None si el fitxer no existeix. El lock
    garanteix que cap altre procés/thread pugui llegir-modificar-escriure
    entre mig (evita la classic lost update race).
    """
    try:
        path = _path(id_)
    except ValueError:
        return None
    try:
        f = open(path, "r+", encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        portalocker.lock(f, portalocker.LOCK_EX)
        try:
            obj = json.load(f)
        except json.JSONDecodeError:
            return None
        mutator(obj)
        f.seek(0)
        f.truncate()
        json.dump(obj, f, ensure_ascii=False)
    finally:
        try:
            portalocker.unlock(f)
        except Exception:
            pass
        f.close()
    _invalidar_index()
    return obj


def marca_producte(id_: str, art_codi: str, preparat: bool) -> dict | None:
    def _aplicar(obj: dict) -> None:
        preparats = set(obj.get("productes_preparats") or [])
        if preparat:
            preparats.add(art_codi)
        else:
            preparats.discard(art_codi)
        obj["productes_preparats"] = sorted(preparats)
    return _modificar_amb_lock(id_, _aplicar)


def reset_preparats(id_: str) -> dict | None:
    """Desmarca tots els productes preparats d'una agrupació."""
    def _aplicar(obj: dict) -> None:
        obj["productes_preparats"] = []
    return _modificar_amb_lock(id_, _aplicar)


def _es_finalitzada(obj: dict) -> bool:
    """Una agrupació està finalitzada quan tots els seus productes estan marcats."""
    n_prods = len((obj.get("resultat") or {}).get("productes") or [])
    n_prep = len(obj.get("productes_preparats") or [])
    return n_prods > 0 and n_prep >= n_prods


def index_carregues_agrupades() -> dict[str, list[dict]]:
    """Retorna {carrega_id: [{id, nom, ts, finalitzada}, ...]}.

    Cacheable: es recalcula quan canvia el fingerprint del directori
    (noms + mtime_ns + mida dels JSON desats). Thread-safe via _index_lock.
    """
    global _index_cache, _index_cache_key
    _ensure_dir()
    try:
        fnames = [f for f in os.listdir(_DIR) if f.endswith(".json")]
    except OSError:
        return {}
    stats: list[tuple[str, int, int]] = []
    for f in fnames:
        try:
            st = os.stat(os.path.join(_DIR, f))
            stats.append((f, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    stats.sort()
    key = tuple(stats)
    with _index_lock:
        if _index_cache_key == key and _index_cache is not None:
            return _index_cache

    index: dict[str, list[dict]] = {}
    for fname, _, _ in stats:
        try:
            with open(os.path.join(_DIR, fname), encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        info = {
            "id": obj.get("id"),
            "nom": obj.get("nom"),
            "ts": obj.get("ts"),
            "finalitzada": _es_finalitzada(obj),
        }
        for c in obj.get("carregues") or []:
            cid = c.get("carrega_id")
            if cid:
                index.setdefault(cid, []).append(info)
    with _index_lock:
        _index_cache = index
        _index_cache_key = key
    return index


def _resumir(obj: dict) -> dict:
    res = obj.get("resultat") or {}
    return {
        "id": obj.get("id"),
        "nom": obj.get("nom"),
        "ts": obj.get("ts"),
        "n_carregues": len(obj.get("carregues") or []),
        "n_productes": len(res.get("productes") or []),
        "total_palets_fisics": res.get("total_palets_fisics", 0),
        "total_sacs": res.get("total_sacs", 0),
        "n_preparats": len(obj.get("productes_preparats") or []),
    }
