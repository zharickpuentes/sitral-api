"""Lotes: escaneo, registro con validación a 10 días, consulta FEFO,
trazabilidad y baja (RQF005, RQF008, RQF009, RQF012)."""
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, AlertasDep, DbSession, StaffUser, Today
from app.api.errors import error_responses
from app.domain.shared.enums import EstadoLote, EstadoRegistro, TipoMovimiento
from app.domain.inventario.escaneo import CodigoInvalidoError, interpretar_codigo
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS, evaluar_vencimiento
from app.infrastructure.persistence.models import Factura, Lote, Medicamento, MovimientoInventario, Proveedor
from app.api.schemas.lotes import (
    AlertaResumen, EscaneoRequest, EscaneoResponse, LoteCreate, LoteRead, LoteUpdate,
    MedicamentoResumen, MovimientoRead, TrazabilidadLote, ValidacionVencimiento,
)
from app.api.mappers import a_lote_read, a_validacion, evaluar_lote
from app.infrastructure.persistence.repositorios import a_lote_vista

router = APIRouter(prefix="/lotes", tags=["Batches & expiry validation"])

IdLote = Annotated[int, Path(gt=0, description="Batch identifier (id_lote).", examples=[6])]


def _obtener(db, id_lote: int) -> Lote:
    lote = db.get(Lote, id_lote)
    if lote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Batch {id_lote} was not found.")
    return lote


def _proveedor_activo(db, id_proveedor: int) -> Proveedor:
    prov = db.get(Proveedor, id_proveedor)
    if prov is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Supplier {id_proveedor} was not found.")
    if prov.estado != EstadoRegistro.ACTIVO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Supplier {id_proveedor} is inactive.")
    return prov


# ------------------------------------------------------------------ escaneo
@router.post(
    "/escanear",
    response_model=EscaneoResponse,
    summary="Decode a scanned barcode or QR code",
    description=(
        "Interprets the raw content read by the mobile camera (RQF005) and pre-validates the batch before it is "
        "registered. Supported formats: **EAN-8/13, UPC-A, GTIN-14**, **GS1 element strings** "
        "(`(01)…(17)…(10)…` or raw with FNC1 separators, as printed in GS1 DataMatrix/QR) and the **SITRAL JSON QR**.\n\n"
        "When the code contains an expiry date (AI 17), the response already reports the days left and whether "
        "the batch falls inside the strict **10-day** critical window."
    ),
    responses=error_responses(400, 401, 403, 422),
)
def escanear(payload: EscaneoRequest, db: DbSession, _: StaffUser, hoy: Today, alertas: AlertasDep) -> EscaneoResponse:
    try:
        datos = interpretar_codigo(payload.codigo)
    except CodigoInvalidoError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    med = None
    candidatos = datos.codigos_candidatos()
    if candidatos:
        med = db.scalar(select(Medicamento).where(Medicamento.codigo_barras.in_(candidatos)))

    lote_existente = None
    if med and datos.numero_lote:
        lote_existente = db.scalar(select(Lote.id_lote).where(
            Lote.id_medicamento == med.id_medicamento, Lote.numero_lote == datos.numero_lote))

    dias = nivel = None
    puede_ingresar = True
    if datos.fecha_vencimiento:
        ev = evaluar_vencimiento(datos.fecha_vencimiento, hoy, alertas.umbral_preventivo())
        dias, nivel = ev.dias_para_vencer, ev.nivel_alerta
        puede_ingresar = ev.dias_para_vencer >= 0

    advertencias = list(datos.advertencias)
    if med is None:
        advertencias.append("Medicine not found in the catalog: register it before receiving the batch.")
    elif med.estado != EstadoRegistro.ACTIVO:
        advertencias.append("The medicine is inactive in the catalog.")
    if dias is not None and 0 <= dias <= UMBRAL_CRITICO_DIAS:
        advertencias.append(f"Batch expires in {dias} day(s): inside the {UMBRAL_CRITICO_DIAS}-day critical window.")

    return EscaneoResponse(
        formato=datos.formato,
        codigo_barras=datos.codigo_barras,
        numero_lote=datos.numero_lote,
        fecha_vencimiento=datos.fecha_vencimiento,
        medicamento_registrado=med is not None,
        medicamento=MedicamentoResumen.model_validate(med) if med else None,
        lote_existente_id=lote_existente,
        dias_para_vencer=dias,
        nivel_alerta=nivel,
        puede_ingresar=puede_ingresar,
        advertencias=advertencias,
    )


# ------------------------------------------------------------------ CRUD
@router.post(
    "",
    response_model=LoteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register an incoming batch",
    description=(
        "Registers a batch received from a supplier (RQF005) and records an ENTRADA inventory movement.\n\n"
        "**Business rules**\n"
        "- Expired batches are rejected with **400**.\n"
        "- Expiry date must be later than the reception date (**400**).\n"
        "- The pair (medicine, batch number) must be unique (**409**).\n"
        "- If the batch expires in **10 days or less**, it is accepted but a **CRITICA** alert is created immediately "
        "(RQF008); inside the configurable window a **PREVENTIVA** alert is created."
    ),
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
def registrar(payload: LoteCreate, db: DbSession, user: StaffUser, hoy: Today, alertas: AlertasDep) -> LoteRead:
    med = db.get(Medicamento, payload.id_medicamento)
    if med is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Medicine {payload.id_medicamento} was not found.")
    if med.estado != EstadoRegistro.ACTIVO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Medicine {payload.id_medicamento} is inactive.")
    _proveedor_activo(db, payload.id_proveedor)
    if payload.id_factura is not None and db.get(Factura, payload.id_factura) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Invoice {payload.id_factura} was not found.")

    fecha_ingreso = payload.fecha_ingreso or hoy
    if fecha_ingreso > hoy:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reception date cannot be in the future.")
    if payload.fecha_vencimiento < hoy:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Cannot register an expired batch (expiry date {payload.fecha_vencimiento}).")
    if payload.fecha_vencimiento <= fecha_ingreso:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Expiry date must be later than the reception date.")
    if db.scalar(select(Lote.id_lote).where(Lote.id_medicamento == payload.id_medicamento,
                                            Lote.numero_lote == payload.numero_lote)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Batch '{payload.numero_lote}' already exists for medicine {payload.id_medicamento}.")

    umbral = alertas.umbral_preventivo()
    ev = evaluar_vencimiento(payload.fecha_vencimiento, hoy, umbral, payload.cantidad_inicial)
    lote = Lote(
        id_medicamento=payload.id_medicamento, id_proveedor=payload.id_proveedor,
        numero_lote=payload.numero_lote.strip(), cantidad_inicial=payload.cantidad_inicial,
        cantidad_disponible=payload.cantidad_inicial, fecha_ingreso=fecha_ingreso,
        fecha_vencimiento=payload.fecha_vencimiento, estado=ev.estado_lote,
    )
    db.add(lote)
    db.flush()  # obtiene id_lote dentro de la misma transacción (RQNF005)
    db.add(MovimientoInventario(
        id_lote=lote.id_lote, id_usuario=user.id_usuario, id_factura=payload.id_factura,
        tipo_movimiento=TipoMovimiento.ENTRADA, cantidad=payload.cantidad_inicial,
        descripcion="Ingreso de lote por escaneo",
    ))
    db.refresh(lote)
    alertas.sincronizar_lote(a_lote_vista(lote), ev)
    db.commit()
    db.refresh(lote)
    return a_lote_read(lote, hoy, umbral)


@router.get(
    "",
    response_model=list[LoteRead],
    summary="List batches (FEFO order)",
    description=(
        "Inventory query by batch (RQF009). Results are sorted by expiry date ascending — **First Expired, First Out** — "
        "so the first batch of each medicine is the one that should be sold first. "
        "Use `vence_en_dias=10` to get every batch inside the strict 10-day window."
    ),
    responses=error_responses(401, 403, 422),
)
def listar(
    db: DbSession, _: StaffUser, hoy: Today, alertas: AlertasDep,
    id_medicamento: Annotated[int | None, Query(gt=0)] = None,
    id_proveedor: Annotated[int | None, Query(gt=0)] = None,
    numero_lote: Annotated[str | None, Query(max_length=100, description="Partial batch number.")] = None,
    estado: EstadoLote | None = None,
    vence_en_dias: Annotated[int | None, Query(ge=0, le=3650,
                             description="Only batches expiring within N days (expired ones included).")] = None,
    solo_disponibles: bool = True,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[LoteRead]:
    stmt = select(Lote).order_by(Lote.fecha_vencimiento, Lote.id_lote)
    if id_medicamento:
        stmt = stmt.where(Lote.id_medicamento == id_medicamento)
    if id_proveedor:
        stmt = stmt.where(Lote.id_proveedor == id_proveedor)
    if numero_lote:
        stmt = stmt.where(Lote.numero_lote.ilike(f"%{numero_lote}%"))
    if vence_en_dias is not None:
        stmt = stmt.where(Lote.fecha_vencimiento <= hoy + timedelta(days=vence_en_dias))
    if solo_disponibles:
        stmt = stmt.where(Lote.cantidad_disponible > 0, Lote.estado != EstadoLote.BAJA)

    umbral = alertas.umbral_preventivo()
    lotes = [a_lote_read(l, hoy, umbral) for l in db.scalars(stmt).unique()]
    if estado is not None:  # el estado se calcula en vivo, por eso se filtra después
        lotes = [l for l in lotes if l.estado == estado]
    return lotes[skip: skip + limit]


@router.get("/{id_lote}", response_model=LoteRead, summary="Get a batch by id",
            responses=error_responses(401, 403, 404, 422))
def obtener(id_lote: IdLote, db: DbSession, _: StaffUser, hoy: Today, alertas: AlertasDep) -> LoteRead:
    return a_lote_read(_obtener(db, id_lote), hoy, alertas.umbral_preventivo())


@router.get(
    "/{id_lote}/validacion",
    response_model=ValidacionVencimiento,
    summary="Validate a batch against the strict 10-day expiry rule",
    description=(
        "Evaluates one batch against the **non-editable 10-day critical threshold** and the Administrator-configured "
        "early-warning threshold. Returns days left, alert level, whether it can still be sold and a recommended action. "
        "The mobile app calls this before adding a batch to a sale."
    ),
    responses=error_responses(401, 403, 404, 422),
)
def validar(id_lote: IdLote, db: DbSession, _: StaffUser, hoy: Today, alertas: AlertasDep) -> ValidacionVencimiento:
    return a_validacion(_obtener(db, id_lote), hoy, alertas.umbral_preventivo())


@router.get(
    "/{id_lote}/trazabilidad",
    response_model=TrazabilidadLote,
    summary="Get the full traceability of a batch",
    description="Reception, supplier, invoices, inventory movements, sales, write-offs and alerts of a batch (RQF012).",
    responses=error_responses(401, 403, 404, 422),
)
def trazabilidad(id_lote: IdLote, db: DbSession, _: StaffUser, hoy: Today, alertas: AlertasDep) -> TrazabilidadLote:
    lote = _obtener(db, id_lote)
    movs = lote.movimientos
    return TrazabilidadLote(
        lote=a_lote_read(lote, hoy, alertas.umbral_preventivo()),
        movimientos=[MovimientoRead.model_validate(m) for m in movs],
        alertas=[AlertaResumen(id_alerta=a.id_alerta, tipo=a.tipo, estado=a.estado.value,
                               dias_restantes=a.dias_restantes, fecha_generacion=a.fecha_generacion)
                 for a in lote.alertas],
        unidades_vendidas=sum(m.cantidad for m in movs if m.tipo_movimiento == TipoMovimiento.SALIDA),
        unidades_dadas_de_baja=sum(m.cantidad for m in movs if m.tipo_movimiento == TipoMovimiento.BAJA),
    )


@router.patch(
    "/{id_lote}",
    response_model=LoteRead,
    summary="Correct batch data (Administrator only)",
    description=(
        "Corrects the batch number, supplier or expiry date of a batch. Every change is written to the audit trail "
        "as an AJUSTE movement and the expiry alerts are re-evaluated. Quantities cannot be edited here."
    ),
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
def corregir(id_lote: IdLote, payload: LoteUpdate, db: DbSession, user: AdminUser, hoy: Today, alertas: AlertasDep) -> LoteRead:
    lote = _obtener(db, id_lote)
    if lote.estado == EstadoLote.BAJA:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A written-off batch cannot be modified.")
    cambios = payload.model_dump(exclude_unset=True, exclude={"motivo"})
    if not cambios:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update were provided.")
    if "id_proveedor" in cambios:
        _proveedor_activo(db, cambios["id_proveedor"])
    if "fecha_vencimiento" in cambios and cambios["fecha_vencimiento"] <= lote.fecha_ingreso:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Expiry date must be later than the reception date.")
    if "numero_lote" in cambios and db.scalar(select(Lote.id_lote).where(
            Lote.id_medicamento == lote.id_medicamento, Lote.numero_lote == cambios["numero_lote"],
            Lote.id_lote != id_lote)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Batch '{cambios['numero_lote']}' already exists.")

    detalle = "; ".join(f"{k}: {getattr(lote, k)} -> {v}" for k, v in cambios.items())
    for campo, valor in cambios.items():
        setattr(lote, campo, valor)
    db.add(MovimientoInventario(id_lote=lote.id_lote, id_usuario=user.id_usuario,
                                tipo_movimiento=TipoMovimiento.AJUSTE, cantidad=0,
                                descripcion=f"{payload.motivo} | {detalle}"[:255]))
    umbral = alertas.umbral_preventivo()
    ev = evaluar_lote(lote, hoy, umbral)
    lote.estado = ev.estado_lote
    alertas.sincronizar_lote(a_lote_vista(lote), ev)
    db.commit()
    db.refresh(lote)
    return a_lote_read(lote, hoy, umbral)


@router.delete(
    "/{id_lote}",
    response_model=LoteRead,
    summary="Write off a batch (logical delete, Administrator only)",
    description=(
        "Removes the remaining units of a batch from inventory (e.g. expired stock sent for destruction). "
        "The row is kept for traceability: status becomes BAJA and a BAJA movement records the lost units, "
        "which feed the *estimated losses* KPI."
    ),
    responses=error_responses(400, 401, 403, 404, 422),
)
def dar_de_baja(
    id_lote: IdLote, db: DbSession, user: AdminUser, hoy: Today, alertas: AlertasDep,
    motivo: Annotated[str, Query(min_length=3, max_length=200, description="Reason for the write-off.")] = "Vencimiento",
) -> LoteRead:
    lote = _obtener(db, id_lote)
    if lote.estado == EstadoLote.BAJA:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Batch {id_lote} is already written off.")
    unidades = lote.cantidad_disponible
    db.add(MovimientoInventario(id_lote=lote.id_lote, id_usuario=user.id_usuario,
                                tipo_movimiento=TipoMovimiento.BAJA, cantidad=unidades,
                                descripcion=f"Baja: {motivo}"[:255]))
    lote.cantidad_disponible = 0
    lote.estado = EstadoLote.BAJA
    db.commit()
    db.refresh(lote)
    return a_lote_read(lote, hoy, alertas.umbral_preventivo())
