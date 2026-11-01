"""Puertos del bounded context Alertas."""
from __future__ import annotations

from typing import Protocol

from app.domain.alertas.modelos import AlertaRegistro, ConfiguracionAlerta
from app.domain.shared.enums import EstadoAlerta


class AlertaRepositorio(Protocol):
    def listar_por_lote(self, id_lote: int) -> list[AlertaRegistro]: ...

    def crear(self, id_lote: int, tipo: str, mensaje: str, dias_restantes: int) -> AlertaRegistro: ...

    def actualizar(self, id_alerta: int, *, estado: EstadoAlerta | None = None,
                   dias_restantes: int | None = None, mensaje: str | None = None) -> None: ...


class ConfiguracionAlertaRepositorio(Protocol):
    def obtener(self) -> ConfiguracionAlerta:
        """Devuelve la configuración activa (la crea con la línea base si no existe)."""

    def actualizar_dias(self, dias_anticipacion: int) -> ConfiguracionAlerta: ...


class UnidadDeTrabajo(Protocol):
    """Confirma de forma atómica los cambios hechos por los repositorios (RQNF005)."""

    def commit(self) -> None: ...
