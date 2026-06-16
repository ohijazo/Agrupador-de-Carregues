"""Autenticació amb usuaris locals a PostgreSQL.

Format del hash de contrasenya: `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`.
Usa `hashlib.pbkdf2_hmac` (built-in, sense dependències externes). El format
inclou l'algorisme i les iteracions perquè es pugui migrar a Argon2/scrypt
al futur sense invalidar els hashes existents.

Sessions amb Flask `session` (cookies signades amb `app.secret_key`).

L'autenticació s'activa amb la variable `AUTH_ENABLED=true` al `.env`. Per
defecte (`false`) l'app continua oberta — útil per a desenvolupament local.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from functools import wraps

from flask import jsonify, redirect, request, session, url_for

import audit
import db

log = logging.getLogger("agrupacio.auth")

PBKDF2_ITER = 200_000
PBKDF2_ALGO = "sha256"
SALT_BYTES = 16


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Hash / verify
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("contrasenya buida")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, plain.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(plain: str, stored: str) -> bool:
    if not plain or not stored:
        return False
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, plain.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# CRUD usuaris
# ---------------------------------------------------------------------------
def crear_usuari(username: str, password: str, nom: str, rol: str = "oficina") -> dict:
    username = (username or "").strip().lower()
    if not username or " " in username:
        raise ValueError("username invàlid (no pot ser buit ni contenir espais)")
    if rol not in ("admin", "oficina", "magatzem"):
        raise ValueError(f"rol invàlid: {rol}")
    h = hash_password(password)
    row = db.fetch_one(
        """
        INSERT INTO usuaris (username, password_hash, nom, rol)
        VALUES (%s, %s, %s, %s)
        RETURNING id, username, nom, rol, actiu, created_at
        """,
        (username, h, nom.strip(), rol),
    )
    audit.log("usuari_creat", target=username, detall={"rol": rol})
    return dict(row)


def get_user_by_username(username: str) -> dict | None:
    return db.fetch_one(
        "SELECT id, username, password_hash, nom, rol, actiu FROM usuaris WHERE username = %s",
        ((username or "").strip().lower(),),
    )


def actualitza_last_login(user_id: int) -> None:
    try:
        db.execute("UPDATE usuaris SET last_login_at = NOW() WHERE id = %s", (user_id,))
    except Exception as e:
        log.warning("No s'ha pogut actualitzar last_login_at: %s", str(e)[:200])


# ---------------------------------------------------------------------------
# Decoradors
# ---------------------------------------------------------------------------
def requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not auth_enabled():
            return fn(*args, **kwargs)
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Autenticació requerida"}), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def requires_rol(*rols):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not auth_enabled():
                return fn(*args, **kwargs)
            if not session.get("user_id"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Autenticació requerida"}), 401
                return redirect(url_for("login", next=request.path))
            if session.get("user_rol") not in rols:
                return jsonify({"error": "Permisos insuficients"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco
