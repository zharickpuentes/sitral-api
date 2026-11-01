"""Tablas de facturación (RQF006/RQF007). Sus routers se implementan en la
siguiente iteración; los modelos se declaran ya porque movimiento_inventario
y la trazabilidad de lotes los referencian."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base
from app.domain.shared.enums import EstadoFactura, TipoFactura


class Factura(Base):
    __tablename__ = "factura"

    id_factura: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuario.id_usuario"))
    id_proveedor: Mapped[int | None] = mapped_column(ForeignKey("proveedor.id_proveedor"))
    numero_factura: Mapped[str] = mapped_column(String(50), index=True)
    tipo: Mapped[TipoFactura] = mapped_column(Enum(TipoFactura))
    fecha: Mapped[datetime] = mapped_column(server_default=func.now())
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    estado: Mapped[EstadoFactura] = mapped_column(Enum(EstadoFactura), default=EstadoFactura.ACTIVA)

    detalles: Mapped[list["DetalleFactura"]] = relationship(back_populates="factura")


class DetalleFactura(Base):
    __tablename__ = "detalle_factura"

    id_detalle: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_factura: Mapped[int] = mapped_column(ForeignKey("factura.id_factura"))
    id_medicamento: Mapped[int] = mapped_column(ForeignKey("medicamento.id_medicamento"))
    id_lote: Mapped[int] = mapped_column(ForeignKey("lote.id_lote"))
    cantidad: Mapped[int]
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    factura: Mapped[Factura] = relationship(back_populates="detalles")
