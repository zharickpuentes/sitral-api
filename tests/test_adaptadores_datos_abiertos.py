"""Adaptadores de datos.gov.co con un servidor HTTP simulado (httpx.MockTransport).

Verifican la cadena completa: circuit breaker → reintentos con backoff → cliente
Socrata → normalización → caché JSON, sin salir a Internet.
"""
import httpx
import pytest

from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError
from app.infrastructure.datos_abiertos.adaptadores import (
    AdaptadorDaneDivipola, AdaptadorInvimaCUM, es_fallo_reintentable,
)
from app.infrastructure.datos_abiertos.cache import CacheJson
from app.infrastructure.datos_abiertos.socrata import ClienteSocrata
from app.infrastructure.resiliencia.circuit_breaker import CircuitBreaker
from app.infrastructure.resiliencia.reintentos import PoliticaReintento

MUNICIPIOS = [{"cod_dpto": "11", "dpto": "BOGOTÁ, D.C.", "cod_mpio": "11001", "nom_mpio": "BOGOTÁ, D.C."},
              {"cod_dpto": "25", "dpto": "CUNDINAMARCA", "cod_mpio": "25175", "nom_mpio": "CHÍA"}]


class Servidor:
    """Responde con la secuencia de códigos indicada y registra cada petición."""

    def __init__(self, codigos, cuerpo=MUNICIPIOS):
        self.codigos = list(codigos)
        self.cuerpo = cuerpo
        self.peticiones: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        codigo = self.codigos.pop(0) if self.codigos else 200
        return httpx.Response(codigo, json=self.cuerpo if codigo == 200 else {"error": True})


def adaptador(clase, servidor, tmp_path, reloj=None):
    cliente = ClienteSocrata("https://www.datos.gov.co/resource", "token-demo", 5,
                             transport=httpx.MockTransport(servidor))
    breaker = CircuitBreaker(clase.nombre, 3, 20, es_fallo=es_fallo_reintentable,
                             **({"reloj": reloj} if reloj else {}))
    esperas: list[float] = []
    reintentos = PoliticaReintento(intentos=3, base=0.5, jitter=0, es_reintentable=es_fallo_reintentable,
                                   dormir=esperas.append)
    return clase(cliente, "gdxc-w37w", breaker, reintentos, CacheJson(tmp_path)), esperas


def test_reintenta_errores_5xx_y_normaliza(tmp_path):
    srv = Servidor([503, 500, 200])
    divipola, esperas = adaptador(AdaptadorDaneDivipola, srv, tmp_path)
    res = divipola.municipios()
    assert res.origen == "api" and res.estado_circuito == "CLOSED" and res.total == 2
    assert res.registros[1] == {**res.registros[1], "cod_municipio": "25175", "cod_departamento": "25"}
    assert esperas == [0.5, 1.0] and len(srv.peticiones) == 3
    assert srv.peticiones[0].headers["X-App-Token"] == "token-demo"
    assert srv.peticiones[0].url.path == "/resource/gdxc-w37w.json"


def test_error_4xx_no_se_reintenta_ni_abre_el_circuito(tmp_path):
    srv = Servidor([400])
    cum, esperas = adaptador(AdaptadorInvimaCUM, srv, tmp_path)
    with pytest.raises(FuenteNoDisponibleError):
        cum.buscar("acetaminofen")
    assert esperas == [] and cum.estado()["estado"] == "CLOSED"


def test_caida_abre_el_circuito_y_sirve_la_cache(tmp_path):
    srv = Servidor([200])
    divipola, _ = adaptador(AdaptadorDaneDivipola, srv, tmp_path)
    assert divipola.municipios().origen == "api"           # llena la caché

    divipola.simular_falla(True)
    for _ in range(3):                                      # 3 llamadas fallidas (cada una con sus reintentos)
        res = divipola.municipios()
        assert res.origen == "cache" and res.total == 2
    assert divipola.estado()["estado"] == "OPEN"

    peticiones = len(srv.peticiones)
    res = divipola.municipios()                             # circuito abierto: ni siquiera intenta la red
    assert res.origen == "cache" and res.estado_circuito == "OPEN"
    assert len(srv.peticiones) == peticiones


def test_sin_cache_y_circuito_abierto_responde_no_disponible(tmp_path):
    srv = Servidor([503] * 9)
    cum, _ = adaptador(AdaptadorInvimaCUM, srv, tmp_path)
    for _ in range(3):
        with pytest.raises(FuenteNoDisponibleError):
            cum.buscar("losartan")
    with pytest.raises(FuenteNoDisponibleError) as exc:
        cum.buscar("losartan")
    assert exc.value.retry_after is not None


def test_half_open_y_recuperacion(tmp_path):
    t = [0.0]
    srv = Servidor([503] * 9)
    divipola, _ = adaptador(AdaptadorDaneDivipola, srv, tmp_path, reloj=lambda: t[0])
    for _ in range(3):
        with pytest.raises(FuenteNoDisponibleError):
            divipola.municipios()
    assert divipola.estado()["estado"] == "OPEN"
    t[0] = 25
    assert divipola.estado()["estado"] == "HALF_OPEN"
    assert divipola.municipios().origen == "api"             # el servidor ya responde 200
    assert divipola.estado()["estado"] == "CLOSED"
