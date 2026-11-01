"""Contenedor de adaptadores de larga vida (singletons del proceso).

Los adaptadores de datos abiertos guardan el estado de su circuit breaker, así
que deben sobrevivir entre peticiones: se crean una sola vez y se reutilizan.
"""
from __future__ import annotations

import threading

from app.infrastructure.analitica.duckdb_motor import MotorDuckDB
from app.infrastructure.config import settings
from app.infrastructure.datos_abiertos.adaptadores import (
    AdaptadorDaneDivipola, AdaptadorInvimaCUM, es_fallo_reintentable,
)
from app.infrastructure.datos_abiertos.cache import CacheJson
from app.infrastructure.datos_abiertos.socrata import ClienteSocrata
from app.infrastructure.resiliencia.circuit_breaker import CircuitBreaker
from app.infrastructure.resiliencia.reintentos import PoliticaReintento


class Contenedor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cum: AdaptadorInvimaCUM | None = None
        self._divipola: AdaptadorDaneDivipola | None = None
        self._analitica: MotorDuckDB | None = None
        self._cliente: ClienteSocrata | None = None

    def _cliente_socrata(self) -> ClienteSocrata:
        if self._cliente is None:
            self._cliente = ClienteSocrata(settings.DATOS_ABIERTOS_BASE_URL, settings.SOCRATA_APP_TOKEN,
                                           settings.OPENDATA_TIMEOUT_SECONDS)
        return self._cliente

    @staticmethod
    def _breaker(nombre: str) -> CircuitBreaker:
        return CircuitBreaker(nombre, umbral_fallos=settings.CB_FAILURE_THRESHOLD,
                              tiempo_recuperacion=settings.CB_RECOVERY_SECONDS, es_fallo=es_fallo_reintentable)

    @staticmethod
    def _reintentos() -> PoliticaReintento:
        return PoliticaReintento(intentos=settings.RETRY_ATTEMPTS, base=settings.RETRY_BASE_SECONDS,
                                 es_reintentable=es_fallo_reintentable)

    def cum(self) -> AdaptadorInvimaCUM:
        with self._lock:
            if self._cum is None:
                self._cum = AdaptadorInvimaCUM(self._cliente_socrata(), settings.DATASET_CUM_ID,
                                               self._breaker("invima_cum"), self._reintentos(),
                                               CacheJson(settings.OPENDATA_CACHE_DIR))
            return self._cum

    def divipola(self) -> AdaptadorDaneDivipola:
        with self._lock:
            if self._divipola is None:
                self._divipola = AdaptadorDaneDivipola(self._cliente_socrata(), settings.DATASET_DIVIPOLA_ID,
                                                       self._breaker("dane_divipola"), self._reintentos(),
                                                       CacheJson(settings.OPENDATA_CACHE_DIR))
            return self._divipola

    def analitica(self) -> MotorDuckDB:
        if self._analitica is None:
            self._analitica = MotorDuckDB()
        return self._analitica


contenedor = Contenedor()
