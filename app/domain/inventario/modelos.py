"""Modelos del bounded context Inventario (independientes de la base de datos)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.shared.enums import EstadoLote


@dataclass(frozen=True)
class LoteVista:
    """Proyección de un lote con los datos de su medicamento y proveedor.

    Es lo que los repositorios entregan a la capa de aplicación: así los casos
    de uso no dependen de los modelos ORM de SQLAlchemy.
    """

    id_lote: int
    numero_lote: str
    medicamento: str
    codigo_barras: str
    proveedor: str
    cantidad_inicial: int
    cantidad_disponible: int
    fecha_ingreso: date
    fecha_vencimiento: date
    estado: EstadoLote
    precio: float = 0.0
    presentacion: str | None = None
    concentracion: str | None = None
    cod_municipio_proveedor: str | None = None

    @property
    def dado_de_baja(self) -> bool:
        return self.estado == EstadoLote.BAJA
