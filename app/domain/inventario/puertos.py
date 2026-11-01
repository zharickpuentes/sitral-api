"""Puertos (interfaces) del bounded context Inventario.

Se definen con `typing.Protocol`: cualquier clase que implemente estos métodos
sirve como adaptador (SQLAlchemy en producción, Mock en las pruebas).
"""
from __future__ import annotations

from typing import Protocol

from app.domain.inventario.modelos import LoteVista
from app.domain.shared.enums import EstadoLote


class LoteRepositorio(Protocol):
    def listar_no_dados_de_baja(self) -> list[LoteVista]:
        """Lotes con estado distinto de BAJA (incluye agotados)."""

    def listar_con_existencias(self) -> list[LoteVista]:
        """Lotes con cantidad disponible > 0 y no dados de baja."""

    def actualizar_estado(self, id_lote: int, estado: EstadoLote) -> None: ...
