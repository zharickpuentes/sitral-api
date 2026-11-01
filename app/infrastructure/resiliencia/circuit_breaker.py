"""Circuit breaker de 3 estados para proteger las llamadas a APIs externas.

    CLOSED ──(N fallos seguidos)──▶ OPEN ──(pasa el tiempo de recuperación)──▶ HALF_OPEN
      ▲                                                                       │
      └──────────────(la llamada de prueba tiene éxito)───────────────────────┘
                     (si la llamada de prueba falla, vuelve a OPEN)

* CLOSED: las llamadas pasan normalmente; se cuentan los fallos consecutivos.
* OPEN: las llamadas se rechazan de inmediato (sin esperar el timeout de la red).
* HALF_OPEN: se deja pasar UNA llamada de prueba para ver si el servicio se recuperó.

Implementación propia (sin librerías) para poder demostrar y probar los tres
estados con un reloj inyectable.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class EstadoCircuito(str, Enum):
    CERRADO = "CLOSED"
    ABIERTO = "OPEN"
    SEMIABIERTO = "HALF_OPEN"


class CircuitoAbiertoError(Exception):
    """Se rechazó la llamada porque el circuito está abierto (o ya hay una prueba en curso)."""

    def __init__(self, nombre: str, reintentar_en: float):
        super().__init__(f"Circuit '{nombre}' is OPEN; retry in {reintentar_en:.0f} s.")
        self.nombre = nombre
        self.reintentar_en = reintentar_en


class CircuitBreaker:
    def __init__(self, nombre: str, umbral_fallos: int = 3, tiempo_recuperacion: float = 30.0,
                 reloj: Callable[[], float] = time.monotonic,
                 es_fallo: Callable[[BaseException], bool] = lambda _e: True):
        if umbral_fallos < 1 or tiempo_recuperacion <= 0:
            raise ValueError("umbral_fallos must be >= 1 and tiempo_recuperacion > 0")
        self.nombre = nombre
        self.umbral_fallos = umbral_fallos
        self.tiempo_recuperacion = tiempo_recuperacion
        self._reloj = reloj
        self._es_fallo = es_fallo
        self._lock = threading.Lock()
        self._estado = EstadoCircuito.CERRADO
        self._fallos = 0
        self._abierto_desde = 0.0
        self._prueba_en_curso = False
        self.total_llamadas = 0
        self.total_fallos = 0
        self.total_rechazadas = 0
        self.historial: deque[dict[str, str]] = deque(maxlen=20)

    # ------------------------------------------------------------ estado
    def _transicion(self, nuevo: EstadoCircuito, motivo: str) -> None:
        if nuevo != self._estado:
            self.historial.appendleft({
                "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "desde": self._estado.value, "hacia": nuevo.value, "motivo": motivo,
            })
            self._estado = nuevo

    def _actualizar(self) -> None:
        """OPEN pasa a HALF_OPEN cuando vence el tiempo de recuperación."""
        if (self._estado == EstadoCircuito.ABIERTO
                and self._reloj() - self._abierto_desde >= self.tiempo_recuperacion):
            self._transicion(EstadoCircuito.SEMIABIERTO, "recovery timeout elapsed")
            self._prueba_en_curso = False

    @property
    def estado(self) -> EstadoCircuito:
        with self._lock:
            self._actualizar()
            return self._estado

    def segundos_para_reintentar(self) -> float:
        with self._lock:
            if self._estado != EstadoCircuito.ABIERTO:
                return 0.0
            return max(0.0, self.tiempo_recuperacion - (self._reloj() - self._abierto_desde))

    # ------------------------------------------------------------ llamada protegida
    def llamar(self, funcion: Callable[[], T]) -> T:
        with self._lock:
            self._actualizar()
            if self._estado == EstadoCircuito.ABIERTO:
                self.total_rechazadas += 1
                raise CircuitoAbiertoError(
                    self.nombre, self.tiempo_recuperacion - (self._reloj() - self._abierto_desde))
            if self._estado == EstadoCircuito.SEMIABIERTO:
                if self._prueba_en_curso:
                    self.total_rechazadas += 1
                    raise CircuitoAbiertoError(self.nombre, 1)
                self._prueba_en_curso = True
            self.total_llamadas += 1

        try:
            resultado = funcion()
        except Exception as exc:
            with self._lock:
                self._prueba_en_curso = False
                if self._es_fallo(exc):
                    self._registrar_fallo(str(exc)[:120] or exc.__class__.__name__)
            raise
        with self._lock:
            self._prueba_en_curso = False
            self._fallos = 0
            if self._estado == EstadoCircuito.SEMIABIERTO:
                self._transicion(EstadoCircuito.CERRADO, "trial call succeeded")
        return resultado

    def _registrar_fallo(self, motivo: str) -> None:
        self.total_fallos += 1
        if self._estado == EstadoCircuito.SEMIABIERTO:
            self._abierto_desde = self._reloj()
            self._transicion(EstadoCircuito.ABIERTO, f"trial call failed: {motivo}")
            return
        self._fallos += 1
        if self._fallos >= self.umbral_fallos:
            self._abierto_desde = self._reloj()
            self._transicion(EstadoCircuito.ABIERTO, f"{self._fallos} consecutive failures: {motivo}")

    # ------------------------------------------------------------ administración
    def reiniciar(self) -> None:
        with self._lock:
            self._fallos = 0
            self._prueba_en_curso = False
            self._transicion(EstadoCircuito.CERRADO, "manual reset")

    def snapshot(self) -> dict[str, Any]:
        estado = self.estado
        return {
            "nombre": self.nombre, "estado": estado.value, "fallos_consecutivos": self._fallos,
            "umbral_fallos": self.umbral_fallos, "tiempo_recuperacion_s": self.tiempo_recuperacion,
            "reintentar_en_s": round(self.segundos_para_reintentar(), 1),
            "total_llamadas": self.total_llamadas, "total_fallos": self.total_fallos,
            "total_rechazadas": self.total_rechazadas, "historial": list(self.historial),
        }
