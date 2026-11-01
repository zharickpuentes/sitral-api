from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base
from app.domain.shared.enums import EstadoRegistro, RolNombre


class Rol(Base):
    __tablename__ = "rol"

    id_rol: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[RolNombre] = mapped_column(Enum(RolNombre), unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(150))

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="rol")


class Usuario(Base):
    __tablename__ = "usuario"

    id_usuario: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id_rol: Mapped[int] = mapped_column(ForeignKey("rol.id_rol"))
    nombre: Mapped[str] = mapped_column(String(100))
    apellido: Mapped[str] = mapped_column(String(100))
    usuario: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # Columna `password` del esquema Fase 1: almacena SOLO el hash Argon2id.
    password_hash: Mapped[str] = mapped_column("password", String(255))
    estado: Mapped[EstadoRegistro] = mapped_column(Enum(EstadoRegistro), default=EstadoRegistro.ACTIVO)
    fecha_creacion: Mapped[datetime] = mapped_column(server_default=func.now())

    rol: Mapped[Rol] = relationship(back_populates="usuarios", lazy="joined")
