"""Reintentos con backoff exponencial y jitter.

Espera antes del intento n (n = 1, 2, ...):  min(base · factor^(n-1), maximo) + jitter
Con base = 0,5 s y factor 2 → 0,5 s, 1 s, 2 s, ...
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class PoliticaReintento:
    intentos: int = 3                      # intentos totales (1 inicial + 2 reintentos)
    base: float = 0.5                      # segundos
    factor: float = 2.0
    maximo: float = 8.0
    jitter: float = 0.25                   # aleatorio en [0, jitter] para no sincronizar clientes
    es_reintentable: Callable[[BaseException], bool] = lambda _e: True
    dormir: Callable[[float], None] = field(default=time.sleep, repr=False)
    aleatorio: Callable[[], float] = field(default=random.random, repr=False)

    def espera(self, reintento: int) -> float:
        """Segundos a esperar antes del reintento número `reintento` (1, 2, ...)."""
        return min(self.base * self.factor ** (reintento - 1), self.maximo) + self.jitter * self.aleatorio()

    def ejecutar(self, funcion: Callable[[], T]) -> T:
        if self.intentos < 1:
            raise ValueError("intentos must be >= 1")
        for intento in range(1, self.intentos + 1):
            try:
                return funcion()
            except Exception as exc:
                if intento == self.intentos or not self.es_reintentable(exc):
                    raise
                self.dormir(self.espera(intento))
        raise AssertionError("unreachable")
