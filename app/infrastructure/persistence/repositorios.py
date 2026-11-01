"""Adaptadores de persistencia (SQLAlchemy) que implementan los puertos del dominio.

Traducen entre los modelos ORM (tablas) y los modelos del dominio (LoteVista,
AlertaRegistro, ConfiguracionAlerta), de modo que la capa de aplicación nunca
ve una sesión ni una tabla de SQLAlchemy.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.alertas.modelos import AlertaRegistro, ConfiguracionAlerta as ConfiguracionVista
from app.domain.inventario.modelos import LoteVista
from app.domain.shared.enums import EstadoAlerta, EstadoConfiguracion, EstadoLote
from app.infrastructure.config import settings
from app.infrastructure.persistence.models import Alerta, ConfiguracionAlerta, Lote


def a_lote_vista(lote: Lote) -> LoteVista:
    med, prov = lote.medicamento, lote.proveedor
    return LoteVista(
        id_lote=lote.id_lote, numero_lote=lote.numero_lote, medicamento=med.nombre,
        codigo_barras=med.codigo_barras, proveedor=prov.nombre,
        cantidad_inicial=lote.cantidad_inicial, cantidad_disponible=lote.cantidad_disponible,
        fecha_ingreso=lote.fecha_ingreso, fecha_vencimiento=lote.fecha_vencimiento, estado=lote.estado,
        precio=float(med.precio or 0), presentacion=med.presentacion, concentracion=med.concentracion,
        cod_municipio_proveedor=getattr(prov, "cod_municipio", None),
    )


def a_alerta_registro(a: Alerta) -> AlertaRegistro:
    return AlertaRegistro(id_alerta=a.id_alerta, id_lote=a.id_lote, tipo=a.tipo, estado=a.estado,
                          dias_restantes=a.dias_restantes, mensaje=a.mensaje)


class SqlLoteRepositorio:
    def __init__(self, db: Session):
        self._db = db

    def listar_no_dados_de_baja(self) -> list[LoteVista]:
        stmt = select(Lote).where(Lote.estado != EstadoLote.BAJA).order_by(Lote.fecha_vencimiento)
        return [a_lote_vista(l) for l in self._db.scalars(stmt).unique()]

    def listar_con_existencias(self) -> list[LoteVista]:
        stmt = (select(Lote).where(Lote.cantidad_disponible > 0, Lote.estado != EstadoLote.BAJA)
                .order_by(Lote.fecha_vencimiento))
        return [a_lote_vista(l) for l in self._db.scalars(stmt).unique()]

    def actualizar_estado(self, id_lote: int, estado: EstadoLote) -> None:
        lote = self._db.get(Lote, id_lote)
        if lote is not None:
            lote.estado = estado


class SqlAlertaRepositorio:
    def __init__(self, db: Session):
        self._db = db

    def listar_por_lote(self, id_lote: int) -> list[AlertaRegistro]:
        stmt = select(Alerta).where(Alerta.id_lote == id_lote)
        return [a_alerta_registro(a) for a in self._db.scalars(stmt).unique()]

    def crear(self, id_lote: int, tipo: str, mensaje: str, dias_restantes: int) -> AlertaRegistro:
        alerta = Alerta(id_lote=id_lote, tipo=tipo, mensaje=mensaje, dias_restantes=dias_restantes,
                        estado=EstadoAlerta.PENDIENTE)
        self._db.add(alerta)
        self._db.flush()
        return a_alerta_registro(alerta)

    def actualizar(self, id_alerta: int, *, estado: EstadoAlerta | None = None,
                   dias_restantes: int | None = None, mensaje: str | None = None) -> None:
        alerta = self._db.get(Alerta, id_alerta)
        if alerta is None:
            return
        if estado is not None:
            alerta.estado = estado
        if dias_restantes is not None:
            alerta.dias_restantes = dias_restantes
        if mensaje is not None:
            alerta.mensaje = mensaje


class SqlConfiguracionAlertaRepositorio:
    def __init__(self, db: Session):
        self._db = db

    def _orm(self) -> ConfiguracionAlerta:
        config = self._db.scalar(
            select(ConfiguracionAlerta)
            .where(ConfiguracionAlerta.estado == EstadoConfiguracion.ACTIVA)
            .order_by(ConfiguracionAlerta.id_configuracion.desc())
        )
        if config is None:
            config = ConfiguracionAlerta(dias_anticipacion=settings.DEFAULT_ALERT_THRESHOLD_DAYS,
                                         estado=EstadoConfiguracion.ACTIVA)
            self._db.add(config)
            self._db.flush()
        return config

    def obtener(self) -> ConfiguracionVista:
        c = self._orm()
        return ConfiguracionVista(c.id_configuracion, c.dias_anticipacion, c.fecha_actualizacion)

    def actualizar_dias(self, dias_anticipacion: int) -> ConfiguracionVista:
        c = self._orm()
        c.dias_anticipacion = dias_anticipacion
        self._db.flush()
        self._db.refresh(c)
        return ConfiguracionVista(c.id_configuracion, c.dias_anticipacion, c.fecha_actualizacion)


class SqlUnidadDeTrabajo:
    def __init__(self, db: Session):
        self._db = db

    def commit(self) -> None:
        self._db.commit()
