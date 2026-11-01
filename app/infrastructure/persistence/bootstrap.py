"""Datos mínimos de arranque y migraciones ligeras (idempotente)."""
import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.domain.shared.enums import RolNombre
from app.infrastructure.persistence.models import Rol
from app.infrastructure.persistence.repositorios import SqlConfiguracionAlertaRepositorio

logger = logging.getLogger("sitral")

_DESCRIPCIONES = {
    RolNombre.ADMINISTRADOR: "Control total: usuarios, proveedores, catálogo, alertas y dashboard.",
    RolNombre.FARMACEUTA: "Operación diaria: escaneo de lotes, facturación, inventario y alertas.",
}

# (tabla, columna, definición SQL) agregadas después de la primera versión del esquema.
_COLUMNAS_NUEVAS = [
    ("proveedor", "cod_municipio", "VARCHAR(5) NULL"),
]


def migrar_columnas(engine: Engine) -> None:
    """Agrega columnas nuevas a tablas existentes (create_all no modifica tablas ya creadas)."""
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    with engine.begin() as con:
        for tabla, columna, definicion in _COLUMNAS_NUEVAS:
            if tabla in tablas and columna not in {c["name"] for c in inspector.get_columns(tabla)}:
                con.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
                logger.info("Migración: columna %s.%s agregada", tabla, columna)


def sembrar_datos_base(db: Session) -> None:
    for nombre, descripcion in _DESCRIPCIONES.items():
        if db.scalar(select(Rol).where(Rol.nombre == nombre)) is None:
            db.add(Rol(nombre=nombre, descripcion=descripcion))
    SqlConfiguracionAlertaRepositorio(db).obtener()
    db.commit()
