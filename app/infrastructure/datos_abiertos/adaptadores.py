"""Adaptadores de las APIs colombianas: INVIMA CUM y DANE DIVIPOLA.

Cada consulta pasa por:   circuit breaker → reintentos con backoff → cliente Socrata
Si todo falla (o el circuito está abierto) se devuelve la última copia en caché.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError, ResultadoFuente
from app.infrastructure.datos_abiertos.cache import CacheJson
from app.infrastructure.datos_abiertos.normalizacion import normalizar_cum, normalizar_municipio
from app.infrastructure.datos_abiertos.socrata import ClienteSocrata, ErrorFuenteExterna
from app.infrastructure.resiliencia.circuit_breaker import CircuitBreaker, CircuitoAbiertoError
from app.infrastructure.resiliencia.reintentos import PoliticaReintento


def es_fallo_reintentable(exc: BaseException) -> bool:
    return isinstance(exc, ErrorFuenteExterna) and exc.reintentable


class FuenteResiliente:
    """Base común: protege una consulta Socrata con circuit breaker, reintentos y caché."""

    nombre = "fuente"

    def __init__(self, cliente: ClienteSocrata, dataset_id: str, breaker: CircuitBreaker,
                 reintentos: PoliticaReintento, cache: CacheJson):
        self._cliente = cliente
        self.dataset_id = dataset_id
        self._breaker = breaker
        self._reintentos = reintentos
        self._cache = cache
        self._falla_simulada = False

    # ------------------------------------------------------------ administración (demo)
    def simular_falla(self, activa: bool) -> None:
        """Hace que cada llamada falle como si el servicio estuviera caído (para demostrar el circuito)."""
        self._falla_simulada = activa

    def reiniciar(self) -> None:
        self._breaker.reiniciar()

    def estado(self) -> dict[str, Any]:
        return {**self._breaker.snapshot(), "fuente": self.nombre, "dataset_id": self.dataset_id,
                "falla_simulada": self._falla_simulada}

    # ------------------------------------------------------------ consulta protegida
    def _llamada_http(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if self._falla_simulada:
            raise ErrorFuenteExterna("Simulated outage (falla_simulada=true)", 503, True)
        return self._cliente.consultar(self.dataset_id, params)

    def _consultar(self, params: dict[str, Any], clave: str,
                   normalizador: Callable[[dict[str, Any]], dict[str, Any]]) -> ResultadoFuente:
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            crudos = self._breaker.llamar(lambda: self._reintentos.ejecutar(lambda: self._llamada_http(params)))
        except (CircuitoAbiertoError, ErrorFuenteExterna) as exc:
            en_cache = self._cache.leer(self.nombre, clave)
            estado = self._breaker.estado.value
            if en_cache is None:
                retry = int(exc.reintentar_en) + 1 if isinstance(exc, CircuitoAbiertoError) else None
                raise FuenteNoDisponibleError(self.nombre, f"{self.nombre} unavailable ({exc}) and no cached copy.",
                                              retry) from exc
            registros, guardado_en = en_cache
            return ResultadoFuente(self.nombre, registros, "cache", estado, ahora,
                                   advertencia=f"Served from cache saved at {guardado_en}: {exc}")
        registros = [normalizador(r) for r in crudos]
        self._cache.guardar(self.nombre, clave, registros)
        return ResultadoFuente(self.nombre, registros, "api", self._breaker.estado.value, ahora)


class AdaptadorInvimaCUM(FuenteResiliente):
    """INVIMA — Código Único de Medicamentos (CUM) vigentes, datos.gov.co."""

    nombre = "invima_cum"

    def buscar(self, termino: str, limite: int = 50) -> ResultadoFuente:
        termino = termino.strip()
        # $q = búsqueda de texto completo de Socrata: no depende de los nombres de columna.
        params = {"$q": termino, "$limit": max(1, min(limite, 1000))}
        return self._consultar(params, f"q={termino.upper()}|limit={params['$limit']}", normalizar_cum)


class AdaptadorDaneDivipola(FuenteResiliente):
    """DANE — División Político-Administrativa de Colombia (DIVIPOLA), datos.gov.co."""

    nombre = "dane_divipola"

    def municipios(self) -> ResultadoFuente:
        return self._consultar({"$limit": 5000}, "municipios", normalizar_municipio)
