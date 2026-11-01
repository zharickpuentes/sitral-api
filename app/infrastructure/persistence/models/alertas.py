from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base
from app.domain.shared.enums import EstadoAlerta, EstadoConfiguracion


class ConfiguracionAlerta(Base):
    __tablename__ = "configuracion_alerta"

    id_configuracion: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dias_anticipacion: Mapped[int]  # umbral PREVENTIVO (≥ 10); el crítico (10) es fijo
    fecha_actualizacion: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    estado: Mapped[EstadoConfiguracion] = mapped_column(
        Enum(EstadoConfiguracion), default=EstadoConfiguracion.ACTIVA)


class Alerta(Base):
    __tablename__ = "alerta"
    __table_args__ = (Index("ix_alerta_lote_tipo", "id_lote", "tipo"),)

    id_alerta: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_lote: Mapped[int] = mapped_column(ForeignKey("lote.id_lote"))
    tipo: Mapped[str] = mapped_column(String(50))  # NivelAlerta: PREVENTIVA | CRITICA | VENCIDO
    mensaje: Mapped[str] = mapped_column(String(255))
    dias_restantes: Mapped[int]
    fecha_generacion: Mapped[datetime] = mapped_column(server_default=func.now())
    estado: Mapped[EstadoAlerta] = mapped_column(Enum(EstadoAlerta), default=EstadoAlerta.PENDIENTE)

    lote: Mapped["Lote"] = relationship(back_populates="alertas", lazy="joined")  # noqa: F821
