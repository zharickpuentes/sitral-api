"""Fixtures de pruebas de integración.

Se usa SQLite en memoria (no requiere MySQL en CI) y se fija la fecha actual
en 2026-10-14 para que los límites de 10/11 días sean deterministas.
"""
import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["ALERT_JOB_ENABLED"] = "false"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-pytest-0123456789")
import tempfile  # noqa: E402

os.environ["AI_LOG_PATH"] = os.path.join(tempfile.gettempdir(), "sitral_pytest_llamadas_ia.jsonl")
os.environ["GEMINI_API_KEY"] = ""  # las pruebas nunca llaman al LLM real

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.infrastructure.persistence.database import Base, get_db  # noqa: E402
from app.api.deps import get_today  # noqa: E402
from app.infrastructure.security import hash_password  # noqa: E402
from app.domain.shared.enums import RolNombre  # noqa: E402
from app.main import app  # noqa: E402
from app.infrastructure.persistence.models import Rol, Usuario  # noqa: E402
from app.infrastructure.persistence.bootstrap import sembrar_datos_base  # noqa: E402

HOY = date(2026, 10, 14)
ADMIN = ("admin", "Admin#2026Seguro")
FARMA = ("farmaceuta", "Farma#2026Segura")


def en_dias(n: int) -> str:
    return (HOY + timedelta(days=n)).isoformat()


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        sembrar_datos_base(db)
        for (usuario, pwd), rol in ((ADMIN, RolNombre.ADMINISTRADOR), (FARMA, RolNombre.FARMACEUTA)):
            id_rol = db.scalar(select(Rol.id_rol).where(Rol.nombre == rol))
            db.add(Usuario(id_rol=id_rol, nombre=usuario.title(), apellido="Prueba",
                           usuario=usuario, password_hash=hash_password(pwd)))
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def _get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    from app.infrastructure.observabilidad import ai_soporte
    ai_soporte.limitador = ai_soporte.LimitadorPorMinuto(ai_soporte.settings.AI_RATE_LIMIT_PER_MINUTE)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_today] = lambda: HOY
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client: TestClient, usuario: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", data={"username": usuario, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client):
    return _login(client, *ADMIN)


@pytest.fixture()
def farma_headers(client):
    return _login(client, *FARMA)


@pytest.fixture()
def medicamento(client, admin_headers):
    r = client.post("/api/v1/medicamentos", headers=admin_headers, json={
        "nombre": "Acetaminofén 500 mg", "presentacion": "Caja x 20 tabletas", "concentracion": "500 mg",
        "codigo_barras": "7701234567890", "registro_sanitario": "INVIMA 2019M-0012345", "precio": 3500,
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def proveedor(client, admin_headers):
    r = client.post("/api/v1/proveedores", headers=admin_headers, json={
        "nombre": "Distribuidora Farmacéutica Andina S.A.S.", "nit": "900123456-7",
        "telefono": "6015550101", "correo": "ventas@farmaandina.co",
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def crear_lote(client, farma_headers, medicamento, proveedor):
    def _crear(numero: str, dias: int, cantidad: int = 40, headers=None):
        return client.post("/api/v1/lotes", headers=headers or farma_headers, json={
            "id_medicamento": medicamento["id_medicamento"], "id_proveedor": proveedor["id_proveedor"],
            "numero_lote": numero, "cantidad_inicial": cantidad, "fecha_vencimiento": en_dias(dias),
        })
    return _crear
