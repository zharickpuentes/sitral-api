"""Mappers de la capa API: modelos ORM / dominio → esquemas de respuesta (Pydantic)."""
from datetime import date

from app.api.schemas.lotes import LoteRead, MedicamentoResumen, ProveedorResumen, ValidacionVencimiento
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS, EvaluacionVencimiento, evaluar_vencimiento
from app.domain.shared.enums import EstadoLote
from app.infrastructure.persistence.models import Lote


def evaluar_lote(lote: Lote, hoy: date, umbral: int) -> EvaluacionVencimiento:
    return evaluar_vencimiento(lote.fecha_vencimiento, hoy, umbral,
                               cantidad_disponible=lote.cantidad_disponible,
                               dado_de_baja=lote.estado == EstadoLote.BAJA)


def a_lote_read(lote: Lote, hoy: date, umbral: int) -> LoteRead:
    ev = evaluar_lote(lote, hoy, umbral)
    return LoteRead(
        id_lote=lote.id_lote,
        numero_lote=lote.numero_lote,
        cantidad_inicial=lote.cantidad_inicial,
        cantidad_disponible=lote.cantidad_disponible,
        fecha_ingreso=lote.fecha_ingreso,
        fecha_vencimiento=lote.fecha_vencimiento,
        estado=ev.estado_lote,
        dias_para_vencer=ev.dias_para_vencer,
        nivel_alerta=ev.nivel_alerta,
        apto_para_venta=ev.apto_para_venta,
        medicamento=MedicamentoResumen.model_validate(lote.medicamento),
        proveedor=ProveedorResumen.model_validate(lote.proveedor),
    )


def a_validacion(lote: Lote, hoy: date, umbral: int) -> ValidacionVencimiento:
    ev = evaluar_lote(lote, hoy, umbral)
    return ValidacionVencimiento(
        id_lote=lote.id_lote,
        numero_lote=lote.numero_lote,
        fecha_vencimiento=lote.fecha_vencimiento,
        fecha_evaluacion=hoy,
        dias_para_vencer=ev.dias_para_vencer,
        umbral_critico_dias=UMBRAL_CRITICO_DIAS,
        umbral_preventivo_dias=umbral,
        dentro_umbral_critico=0 <= ev.dias_para_vencer <= UMBRAL_CRITICO_DIAS,
        nivel_alerta=ev.nivel_alerta,
        estado_lote=ev.estado_lote,
        apto_para_venta=ev.apto_para_venta,
        recomendacion=ev.recomendacion,
    )
