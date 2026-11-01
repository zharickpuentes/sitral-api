from datetime import date, datetime

from sqlalchemy import Date, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base
from app.domain.shared.enums import EstadoLote, TipoMovimiento


class Lote(Base):
    __tablename__ = "lote"
    __table_args__ = (
        UniqueConstraint("id_medicamento", "numero_lote", name="uq_lote_medicamento_numero"),
        Index("ix_lote_fecha_vencimiento", "fecha_vencimiento"),  # consultas FEFO y alertas
    )

    id_lote: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_medicamento: Mapped[int] = mapped_column(ForeignKey("medicamento.id_medicamento"))
    id_proveedor: Mapped[int] = mapped_column(ForeignKey("proveedor.id_proveedor"))
    numero_lote: Mapped[str] = mapped_column(String(100))
    cantidad_inicial: Mapped[int]
    cantidad_disponible: Mapped[int]
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    fecha_vencimiento: Mapped[date] = mapped_column(Date)
    estado: Mapped[EstadoLote] = mapped_column(Enum(EstadoLote), default=EstadoLote.VIGENTE)

    medicamento: Mapped["Medicamento"] = relationship(back_populates="lotes", lazy="joined")  # noqa: F821
    proveedor: Mapped["Proveedor"] = relationship(back_populates="lotes", lazy="joined")  # noqa: F821
    movimientos: Mapped[list["MovimientoInventario"]] = relationship(
        back_populates="lote", order_by="MovimientoInventario.fecha")
    alertas: Mapped[list["Alerta"]] = relationship(  # noqa: F821
        back_populates="lote", order_by="Alerta.fecha_generacion")


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"

    id_movimiento: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_lote: Mapped[int] = mapped_column(ForeignKey("lote.id_lote"), index=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuario.id_usuario"))
    id_factura: Mapped[int | None] = mapped_column(ForeignKey("factura.id_factura"))
    tipo_movimiento: Mapped[TipoMovimiento] = mapped_column(Enum(TipoMovimiento))
    cantidad: Mapped[int]
    fecha: Mapped[datetime] = mapped_column(server_default=func.now())
    descripcion: Mapped[str | None] = mapped_column(String(255))

    lote: Mapped[Lote] = relationship(back_populates="movimientos")
