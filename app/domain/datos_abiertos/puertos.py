"""Puertos del bounded context Datos Abiertos y Analítica."""
from __future__ import annotations

from typing import Any, Protocol

from app.domain.datos_abiertos.modelos import ResultadoFuente


class FuenteExternaPort(Protocol):
    """Capacidades comunes de una fuente externa protegida con circuit breaker."""

    nombre: str

    def estado(self) -> dict[str, Any]: ...

    def simular_falla(self, activa: bool) -> None: ...

    def reiniciar(self) -> None: ...


class CatalogoMedicamentosPort(FuenteExternaPort, Protocol):
    """INVIMA — Código Único de Medicamentos (CUM) en datos.gov.co."""

    def buscar(self, termino: str, limite: int = 50) -> ResultadoFuente: ...


class DivisionPoliticaPort(FuenteExternaPort, Protocol):
    """DANE — División Político-Administrativa (DIVIPOLA) en datos.gov.co."""

    def municipios(self) -> ResultadoFuente: ...


class MotorAnaliticoPort(Protocol):
    """Consultas analíticas SQL sobre datos JSON (implementado con DuckDB)."""

    def oferta_por_principio(self, registros_cum: list[dict[str, Any]]) -> dict[str, Any]: ...

    def estadisticas_inventario(self, inventario: list[dict[str, Any]]) -> dict[str, Any]: ...

    def cobertura_regional(self, inventario: list[dict[str, Any]],
                           municipios: list[dict[str, Any]]) -> dict[str, Any]: ...
