"""Modelos ORM de SITRAL — 10 tablas del esquema relacional de la Fase 1."""
from app.infrastructure.persistence.models.alertas import Alerta, ConfiguracionAlerta
from app.infrastructure.persistence.models.catalogo import Medicamento, Proveedor
from app.infrastructure.persistence.models.facturacion import DetalleFactura, Factura
from app.infrastructure.persistence.models.inventario import Lote, MovimientoInventario
from app.infrastructure.persistence.models.usuarios import Rol, Usuario

__all__ = [
    "Alerta", "ConfiguracionAlerta", "DetalleFactura", "Factura", "Lote",
    "Medicamento", "MovimientoInventario", "Proveedor", "Rol", "Usuario",
]
