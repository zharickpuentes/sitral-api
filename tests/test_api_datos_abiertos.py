"""Endpoints /datos-abiertos, /analitica y /dashboard con puertos falsos inyectados.

Se sobrescribe la dependencia `get_servicio_datos_abiertos` (raíz de composición)
para usar fuentes en memoria: las pruebas nunca llaman a datos.gov.co.
"""
import pytest

from app.api.deps import get_servicio_datos_abiertos
from app.application.datos_abiertos.servicio import ServicioDatosAbiertos
from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError, ResultadoFuente
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.repositorios import SqlLoteRepositorio
from app.main import app


class FuenteFalsa:
    def __init__(self, nombre, registros):
        self.nombre = nombre
        self.registros = registros
        self.caida = False
        self.estado_actual = "CLOSED"

    def estado(self):
        return {"fuente": self.nombre, "nombre": self.nombre, "dataset_id": "demo", "estado": self.estado_actual,
                "fallos_consecutivos": 0, "umbral_fallos": 3, "tiempo_recuperacion_s": 20.0, "reintentar_en_s": 0.0,
                "total_llamadas": 0, "total_fallos": 0, "total_rechazadas": 0, "falla_simulada": self.caida,
                "historial": []}

    def simular_falla(self, activa):
        self.caida = activa

    def reiniciar(self):
        self.estado_actual = "CLOSED"

    def _resultado(self):
        if self.caida:
            raise FuenteNoDisponibleError(self.nombre, "simulated outage", retry_after=20)
        return ResultadoFuente(self.nombre, list(self.registros), "api", self.estado_actual, "2026-10-14T12:00:00")

    def buscar(self, termino, limite=50):
        return self._resultado()

    def municipios(self):
        return self._resultado()


class MotorFalso:
    def oferta_por_principio(self, registros):
        return {"filas": [{"principio_activo": "ACETAMINOFEN", "presentaciones": len(registros)}],
                "resumen": {"principios": 1}, "sql": {"filas": "SELECT ..."}}

    def estadisticas_inventario(self, inventario):
        return {"filas": [{"nivel": f["nivel"]} for f in inventario], "resumen": {"lotes": len(inventario)},
                "sql": {"filas": "SELECT ..."}}

    def cobertura_regional(self, inventario, municipios):
        return {"filas": [], "resumen_divipola": {"municipios": len(municipios)}, "sql": {"filas": "SELECT ..."}}


CUM = [{"registro_sanitario": "INVIMA 2019M-0012345", "producto": "ACETAMINOFEN 500 MG"}]
MUNICIPIOS = [{"cod_departamento": "11", "cod_municipio": "11001", "municipio": "BOGOTÁ"},
              {"cod_departamento": "25", "cod_municipio": "25175", "municipio": "CHÍA"}]


@pytest.fixture()
def fuentes(client):
    cum, divipola = FuenteFalsa("invima_cum", CUM), FuenteFalsa("dane_divipola", MUNICIPIOS)
    obtener_db = app.dependency_overrides[get_db]

    def _servicio():
        db = next(obtener_db())
        return ServicioDatosAbiertos(cum, divipola, MotorFalso(), SqlLoteRepositorio(db), umbral_preventivo=30)

    app.dependency_overrides[get_servicio_datos_abiertos] = _servicio
    return cum, divipola


def test_buscar_medicamentos_y_verificar_registro(client, farma_headers, fuentes):
    r = client.get("/api/v1/datos-abiertos/medicamentos", params={"q": "acetaminofen"}, headers=farma_headers)
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["origen"] == "api"
    r = client.get("/api/v1/datos-abiertos/medicamentos/registro", params={"registro": "INVIMA 2019M-0012345"},
                   headers=farma_headers)
    assert r.status_code == 200 and r.json()["encontrado"] is True


def test_municipios_filtrados(client, farma_headers, fuentes):
    r = client.get("/api/v1/datos-abiertos/municipios", params={"cod_departamento": "25"}, headers=farma_headers)
    assert r.status_code == 200 and [m["municipio"] for m in r.json()["registros"]] == ["CHÍA"]


def test_requiere_autenticacion(client, fuentes):
    assert client.get("/api/v1/datos-abiertos/circuitos").status_code == 401


def test_fuente_caida_sin_cache_responde_503(client, farma_headers, fuentes):
    fuentes[0].simular_falla(True)
    r = client.get("/api/v1/datos-abiertos/medicamentos", params={"q": "losartan"}, headers=farma_headers)
    assert r.status_code == 503 and r.json()["status_code"] == 503


def test_simular_falla_solo_administrador(client, admin_headers, farma_headers, fuentes):
    url = "/api/v1/datos-abiertos/circuitos/dane_divipola/simular-falla"
    assert client.post(url, headers=farma_headers).status_code == 403
    r = client.post(url, params={"activar": True}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["falla_simulada"] is True
    assert client.post("/api/v1/datos-abiertos/circuitos/otra/reiniciar", headers=admin_headers).status_code == 422


def test_estado_de_circuitos(client, farma_headers, fuentes):
    r = client.get("/api/v1/datos-abiertos/circuitos", headers=farma_headers)
    assert r.status_code == 200 and {c["fuente"] for c in r.json()} == {"invima_cum", "dane_divipola"}


def test_endpoints_analiticos(client, farma_headers, fuentes, crear_lote):
    assert crear_lote("LT-1", dias=4).status_code == 201
    assert crear_lote("LT-2", dias=200).status_code == 201
    r = client.get("/api/v1/analitica/inventario", headers=farma_headers)
    assert r.status_code == 200 and r.json()["resumen"]["lotes"] == 2
    assert sorted(f["nivel"] for f in r.json()["filas"]) == ["CRITICA", "VIGENTE"]
    r = client.get("/api/v1/analitica/oferta-mercado", headers=farma_headers)
    assert r.status_code == 200 and r.json()["origenes"] == {"ACETAMINOFEN": "api"}
    r = client.get("/api/v1/analitica/cobertura-regional", headers=farma_headers)
    assert r.status_code == 200 and r.json()["resumen_divipola"]["municipios"] == 2


def test_dashboard_se_sirve(client):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "chart.umd.min.js" in r.text
