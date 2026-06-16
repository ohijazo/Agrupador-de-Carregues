"""Tests dels endpoints /api/admin/usuaris i el flow de login (AUTH activat).

Requereix PG_HOST. Activa temporalment AUTH_ENABLED per validar el flow.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def auth_client(store_tmp, monkeypatch):
    """Client amb AUTH_ENABLED=true i la taula usuaris neta."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test_secret_for_pytest_only" * 2)
    if not os.environ.get("PG_HOST"):
        pytest.skip("PG_HOST no configurat")
    import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuaris WHERE username LIKE 'test_%'")
            cur.execute("DELETE FROM audit_logs WHERE accio LIKE 'login_%' OR target LIKE 'test_%'")

    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuaris WHERE username LIKE 'test_%'")


def _get_csrf_token(client):
    """Helper: fa un GET a /login per obtenir la cookie CSRF.
    Compatible amb les dues APIs de Werkzeug (cookie_jar / get_cookie)."""
    client.get("/login")
    if hasattr(client, "get_cookie"):
        c = client.get_cookie("csrf_token")
        return c.value if c else ""
    cookie = next((c for c in getattr(client, "cookie_jar", []) if c.name == "csrf_token"), None)
    return cookie.value if cookie else ""


def _crear_admin(username="test_admin", password="adminpass123"):
    import auth
    return auth.crear_usuari(username, password, "Test Admin", rol="admin")


def _crear_oficina(username="test_oficina", password="oficinapass123"):
    import auth
    return auth.crear_usuari(username, password, "Test Oficina", rol="oficina")


def _login(client, username, password):
    """Login via form POST. Retorna la resposta."""
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def _login_as(client, user):
    """Helper: estableix la sessió directament (sense passar pel form de
    login). Més robust per als tests perquè evita problemes de propagació
    de cookies entre fixtures."""
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["nom"]
        sess["user_username"] = user["username"]
        sess["user_rol"] = user["rol"]


# --- Middleware d'auth ---------------------------------------------------
def test_index_sense_login_redirigeix_a_login(auth_client):
    r = auth_client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.location


def test_api_sense_login_retorna_401(auth_client):
    r = auth_client.get("/api/transportistes")
    assert r.status_code == 401
    assert "Autenticació" in r.get_json().get("error", "")


def test_health_continua_public_amb_auth_actiu(auth_client):
    r = auth_client.get("/health")
    assert r.status_code in (200, 503)
    assert "ok" in r.get_json()


# --- Login flow ----------------------------------------------------------
def test_login_correcte(auth_client):
    _crear_admin()
    r = _login(auth_client, "test_admin", "adminpass123")
    # Redirect cap a /
    assert r.status_code == 302
    # Ara amb la sessió set, accedim a /api/me
    r2 = auth_client.get("/api/me")
    body = r2.get_json()
    assert body["authenticated"] is True
    assert body["username"] == "test_admin"
    assert body["rol"] == "admin"


def test_login_password_incorrecte(auth_client):
    _crear_admin()
    r = _login(auth_client, "test_admin", "WRONG_password")
    assert r.status_code == 401


def test_login_usuari_inexistent(auth_client):
    r = _login(auth_client, "no_existeix", "qualsevol")
    assert r.status_code == 401


def test_login_usuari_desactivat(auth_client):
    import auth
    u = _crear_admin()
    auth.actualitzar_usuari(u["id"], actiu=False)
    r = _login(auth_client, "test_admin", "adminpass123")
    assert r.status_code == 401


def test_logout(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    # Verifica que estem logged in
    assert auth_client.get("/api/me").get_json()["authenticated"] is True
    auth_client.get("/logout")
    # Després del logout, la sessió s'ha esborrat
    body = auth_client.get("/api/me").get_json()
    assert body["authenticated"] is False


# --- Endpoints admin (requires_rol) --------------------------------------
def test_admin_endpoint_oficina_rebutjat(auth_client):
    u = _crear_oficina()
    _login_as(auth_client, u)
    r = auth_client.get("/api/admin/usuaris")
    assert r.status_code == 403
    assert "permisos" in r.get_json().get("error", "").lower()


def test_admin_endpoint_admin_ok(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    r = auth_client.get("/api/admin/usuaris")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_admin_crear_usuari(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    tok = _get_csrf_token(auth_client)
    r = auth_client.post(
        "/api/admin/usuaris",
        json={"username": "test_new", "password": "newpass123", "nom": "Test New", "rol": "oficina"},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 201
    assert r.get_json()["username"] == "test_new"


def test_admin_crear_username_duplicat(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    tok = _get_csrf_token(auth_client)
    payload = {"username": "test_dup", "password": "pass12345", "nom": "Dup", "rol": "oficina"}
    auth_client.post("/api/admin/usuaris", json=payload, headers={"X-CSRF-Token": tok})
    r = auth_client.post("/api/admin/usuaris", json=payload, headers={"X-CSRF-Token": tok})
    assert r.status_code == 409


def test_admin_crear_password_curta(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    tok = _get_csrf_token(auth_client)
    r = auth_client.post(
        "/api/admin/usuaris",
        json={"username": "test_x", "password": "curt", "nom": "X", "rol": "oficina"},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 400


def test_admin_no_es_pot_desactivar_a_si_mateix(auth_client):
    u = _crear_admin()
    _login_as(auth_client, u)
    tok = _get_csrf_token(auth_client)
    r = auth_client.patch(
        f"/api/admin/usuaris/{u['id']}",
        json={"actiu": False},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 400
    assert "propi" in r.get_json().get("error", "").lower()


# --- Redirect magatzem → /magatzem --------------------------------------
def test_magatzem_redirigit_a_magatzem_des_de_index(auth_client):
    import auth
    u = auth.crear_usuari("test_magatzem", "magpass123", "Test Mag", rol="magatzem")
    _login_as(auth_client, u)
    r = auth_client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert "/magatzem" in r.location


def test_magatzem_no_pot_cercar_carregues(auth_client):
    import auth
    u = auth.crear_usuari("test_magatzem2", "magpass123", "Test Mag", rol="magatzem")
    _login_as(auth_client, u)
    r = auth_client.get("/api/transportistes")
    assert r.status_code == 403
