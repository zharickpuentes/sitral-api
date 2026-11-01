from decimal import Decimal

from sqlalchemy import Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base
from app.domain.shared.enums import EstadoRegistro


class Proveedor(Base):
    __tablename__ = "proveedor"

    id_proveedor: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(150))
    nit: Mapped[str] = mapped_column(String(30), unique=True)
    telefono: Mapped[str | None] = mapped_column(String(30))
    correo: Mapped[str | None] = mapped_column(String(100))
    direccion: Mapped[str | None] = mapped_column(String(200))
    # Ampliación Guía 6: código DANE (DIVIPOLA) del municipio del proveedor
    cod_municipio: Mapped[str | None] = mapped_column(String(5))
    estado: Mapped[EstadoRegistro] = mapped_column(Enum(EstadoRegistro), default=EstadoRegistro.ACTIVO)

    lotes: Mapped[list["Lote"]] = relationship(back_populates="proveedor")  # noqa: F821


class Medicamento(Base):
    __tablename__ = "medicamento"

    id_medicamento: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(150), index=True)
    presentacion: Mapped[str | None] = mapped_column(String(100))
    concentracion: Mapped[str | None] = mapped_column(String(50))
    codigo_barras: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Ampliación Fase 2: registro sanitario INVIMA, exigido en la trazabilidad
    # que verifica la Secretaría de Salud (Decreto 677 de 1995).
    registro_sanitario: Mapped[str | None] = mapped_column(String(50))
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    estado: Mapped[EstadoRegistro] = mapped_column(Enum(EstadoRegistro), default=EstadoRegistro.ACTIVO)

    lotes: Mapped[list["Lote"]] = relationship(back_populates="medicamento")  # noqa: F821
