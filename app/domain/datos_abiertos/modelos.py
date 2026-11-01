"""Modelos del bounded context Datos Abiertos (INVIMA CUM y DANE DIVIPOLA)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FuenteNoDisponibleError(Exception):
    """La fuente externa falló (o su circuito está abierto) y no hay caché disponible."""

    def __init__(self, fuente: str, mensaje: str, retry_after: int | None = None):
        super().__init__(mensaje)
        self.fuente = fuente
        self.mensaje = mensaje
        self.retry_after = retry_after


@dataclass
class ResultadoFuente:
    """Respuesta de una fuente de datos abiertos, ya normalizada.

    origen = "api"   → datos frescos del servicio público.
    origen = "cache" → la API falló o el circuito estaba abierto; se usa la última copia exitosa.
    """

    fuente: str
    registros: list[dict[str, Any]]
    origen: str
    estado_circuito: str
    consultado_en: str
    advertencia: str | None = None
    total: int = field(init=False)

    def __post_init__(self) -> None:
        self.total = len(self.registros)
