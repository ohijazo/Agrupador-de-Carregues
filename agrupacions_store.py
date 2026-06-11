"""Store senzill d'agrupacions desades en fitxers JSON dins `data/agrupacions/`.

Cada agrupació té: id (uuid), nom, ts (ISO), carregues (entrada), resultat (resposta),
i opcionalment estats per producte (per al mode magatzem futur).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agrupacions")
_RE_ID = re.compile(r"^[a-f0-9-]{8,40}$")


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
    with open(_path(id_), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
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
            out.append(_resumir(obj))
        except (OSError, json.JSONDecodeError):
            continue
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
        return True
    except (FileNotFoundError, ValueError):
        return False


def marca_producte(id_: str, art_codi: str, preparat: bool) -> dict | None:
    obj = obtenir(id_)
    if obj is None:
        return None
    preparats = set(obj.get("productes_preparats") or [])
    if preparat:
        preparats.add(art_codi)
    else:
        preparats.discard(art_codi)
    obj["productes_preparats"] = sorted(preparats)
    with open(_path(id_), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return obj


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
