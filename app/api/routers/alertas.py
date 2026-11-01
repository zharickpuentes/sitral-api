"""Alertas de vencimiento y configuración del umbral (RQF008)."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from dataclasses import asdict

from app.api.deps import AdminUser, AlertasDep, DbSession, StaffUser, Today
from app.api.errors import error_responses
from app.domain.shared.enums import EstadoAlerta, NivelAlerta
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS
from app.infrastructure.persistence.models import Alerta
from app.api.schemas.alertas import (
    AlertaRead, ConfiguracionAlertaRead, ConfiguracionAlertaUpdate, ResumenGeneracion,
)

router = APIRouter(prefix="/alertas", tags=["Expiry alerts"])


def a_alerta_read(a: Alerta) -> AlertaRead:
    return AlertaRead(
        id_alerta=a.id_alerta, id_lote=a.id_lote, tipo=a.tipo, estado=a.estado, mensaje=a.mensaje,
        dias_restantes=a.dias_restantes, fecha_generacion=a.fecha_generacion,
        medicamento=a.lote.medicamento.nombre, numero_lote=a.lote.numero_lote,
        cantidad_disponible=a.lote.cantidad_disponible, fecha_vencimiento=a.lote.fecha_vencimiento,
    )


def _config_read(config) -> ConfiguracionAlertaRead:
    return ConfiguracionAlertaRead(id_configuracion=config.id_configuracion,
                                   dias_anticipacion=config.dias_anticipacion,
                                   umbral_critico_dias=UMBRAL_CRITICO_DIAS,
                                   fecha_actualizacion=config.fecha_actualizacion)


@router.post(
    "/generar",
    response_model=ResumenGeneracion,
    summary="Run the expiry alert evaluation",
    description=(
        "Evaluates every batch with stock against the **strict 10-day critical threshold** and the configurable "
        "early-warning threshold, updates batch status (VIGENTE / PROXIMO_VENCER / VENCIDO / AGOTADO) and creates "
        "alerts. The run is **idempotent**: repeated executions never duplicate alerts, and a pending alert is "
        "escalated when the batch moves to a higher level. It also runs automatically every day when "
        "`ALERT_JOB_ENABLED=true` (actor *Sistema*)."
    ),
    responses=error_responses(401, 403),
)
def ejecutar_generacion(alertas: AlertasDep, _: StaffUser, hoy: Today) -> ResumenGeneracion:
    return ResumenGeneracion(**asdict(alertas.generar(hoy)))


@router.get(
    "",
    response_model=list[AlertaRead],
    summary="List expiry alerts",
    description="Returns alerts ordered by urgency (fewest days left first). By default only PENDIENTE alerts.",
    responses=error_responses(401, 403, 422),
)
def listar(
    db: DbSession, _: StaffUser,
    estado: EstadoAlerta | None = EstadoAlerta.PENDIENTE,
    tipo: NivelAlerta | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlertaRead]:
    stmt = select(Alerta).order_by(Alerta.dias_restantes, Alerta.id_alerta)
    if estado is not None:
        stmt = stmt.where(Alerta.estado == estado)
    if tipo is not None:
        stmt = stmt.where(Alerta.tipo == tipo.value)
    return [a_alerta_read(a) for a in db.scalars(stmt.offset(skip).limit(limit)).unique()]


@router.patch(
    "/{id_alerta}/atender",
    response_model=AlertaRead,
    summary="Mark an alert as handled",
    description="Marks a PENDIENTE alert as ATENDIDA once the pharmacist has acted on it (sold, returned or quarantined).",
    responses=error_responses(400, 401, 403, 404, 422),
)
def atender(
    id_alerta: Annotated[int, Path(gt=0, examples=[12])], db: DbSession, _: StaffUser,
) -> AlertaRead:
    alerta = db.get(Alerta, id_alerta)
    if alerta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Alert {id_alerta} was not found.")
    if alerta.estado != EstadoAlerta.PENDIENTE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Alert {id_alerta} is already {alerta.estado.value}.")
    alerta.estado = EstadoAlerta.ATENDIDA
    db.commit()
    db.refresh(alerta)
    return a_alerta_read(alerta)


@router.get(
    "/configuracion",
    response_model=ConfiguracionAlertaRead,
    summary="Get the alert threshold configuration",
    description="Returns the early-warning threshold (baseline 30 days) and the fixed 10-day critical threshold.",
    responses=error_responses(401, 403),
)
def leer_configuracion(alertas: AlertasDep, db: DbSession, _: StaffUser) -> ConfiguracionAlertaRead:
    config = alertas.configuracion()
    db.commit()
    return _config_read(config)


@router.put(
    "/configuracion",
    response_model=ConfiguracionAlertaRead,
    summary="Update the early-warning threshold (Administrator only)",
    description=(
        "Adjusts `dias_anticipacion` (10–180). Values below **10** are rejected with **422** because the "
        "10-day critical window is a strict rule. Pharmacists receive **403**. Run `POST /alertas/generar` "
        "afterwards to apply the new threshold immediately."
    ),
    responses=error_responses(401, 403, 422),
)
def actualizar_configuracion(
    payload: ConfiguracionAlertaUpdate, alertas: AlertasDep, _: AdminUser,
) -> ConfiguracionAlertaRead:
    return _config_read(alertas.actualizar_umbral(payload.dias_anticipacion))
