"""Autenticación JWT/Argon2id, roles y CRUD de medicamentos (códigos 200/201/401/403/404/409/422)."""
import jwt

from app.infrastructure.config import settings


def test_login_devuelve_jwt_con_rol(client):
    r = client.post("/api/v1/auth/login", data={"username": "admin", "password": "Admin#2026Seguro"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["rol"] == "ADMINISTRADOR"
    payload = jwt.decode(body["access_token"], settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["rol"] == "ADMINISTRADOR"


def test_login_password_incorrecta_401(client):
    r = client.post("/api/v1/auth/login", data={"username": "admin", "password": "incorrecta"})
    assert r.status_code == 401
    assert r.json()["error"] == "Unauthorized"


def test_endpoint_protegido_sin_token_401(client):
    assert client.get("/api/v1/lotes").status_code == 401


def test_token_invalido_401(client):
    r = client.get("/api/v1/lotes", headers={"Authorization": "Bearer token.falso.123"})
    assert r.status_code == 401


def test_crud_completo_medicamento(client, admin_headers, medicamento):
    mid = medicamento["id_medicamento"]
    assert client.get(f"/api/v1/medicamentos/{mid}", headers=admin_headers).status_code == 200
    assert len(client.get("/api/v1/medicamentos?q=Acetamin", headers=admin_headers).json()) == 1

    r = client.put(f"/api/v1/medicamentos/{mid}", headers=admin_headers, json={"precio": 3800})
    assert r.status_code == 200 and float(r.json()["precio"]) == 3800
    assert r.json()["nombre"] == "Acetaminofén 500 mg"  # actualización parcial

    r = client.delete(f"/api/v1/medicamentos/{mid}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["estado"] == "INACTIVO"  # borrado lógico


def test_farmaceuta_no_puede_modificar_catalogo_403(client, farma_headers, medicamento):
    r = client.put(f"/api/v1/medicamentos/{medicamento['id_medicamento']}", headers=farma_headers,
                   json={"precio": 1})
    assert r.status_code == 403


def test_medicamento_inexistente_404(client, admin_headers):
    r = client.delete("/api/v1/medicamentos/9999", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["path"] == "/api/v1/medicamentos/9999"


def test_validacion_de_datos_422(client, admin_headers):
    r = client.post("/api/v1/medicamentos", headers=admin_headers,
                    json={"nombre": "X", "codigo_barras": "1", "precio": -5})
    assert r.status_code == 422
    campos = {d["field"] for d in r.json()["details"]}
    assert {"body.nombre", "body.codigo_barras", "body.precio"} <= campos


def test_codigo_barras_duplicado_409(client, admin_headers, medicamento):
    r = client.post("/api/v1/medicamentos", headers=admin_headers, json={
        "nombre": "Otro", "codigo_barras": medicamento["codigo_barras"], "precio": 100})
    assert r.status_code == 409


def test_admin_crea_usuario_y_password_no_se_expone(client, admin_headers, farma_headers):
    nuevo = {"nombre": "Laura", "apellido": "Gómez", "usuario": "lgomez",
             "password": "Farma#2026Nueva", "rol": "FARMACEUTA"}
    r = client.post("/api/v1/usuarios", headers=admin_headers, json=nuevo)
    assert r.status_code == 201 and "password" not in r.json()
    assert client.post("/api/v1/usuarios", headers=farma_headers, json=nuevo).status_code == 403
