"""Reglas de negocio de vencimiento (RQF008) — validación a 10 días.

Conciliación de requisitos:
* Brief del proyecto / tablero: alerta como máximo 10 días antes de la fecha
  de caducidad → UMBRAL_CRITICO_DIAS = 10. Es una regla estricta: NO se puede
  modificar desde la API.
* Entrevista Fase 1 (Tabla 1, P4): la administradora pidió 30 días → umbral
  PREVENTIVO configurable por el Administrador (línea base 30, mínimo 10).

Así, todo lote con 10 días o menos SIEMPRE genera alerta CRÍTICA, sin importar
cómo se configure el umbral preventivo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

from app.domain.shared.enums import EstadoLote, NivelAlerta

UMBRAL_CRITICO_DIAS: Final[int] = 10
UMBRAL_PREVENTIVO_DEFECTO: Final[int] = 30
UMBRAL_PREVENTIVO_MAXIMO: Final[int] = 180


@dataclass(frozen=True)
class EvaluacionVencimiento:
    dias_para_vencer: int
    estado_lote: EstadoLote
    nivel_alerta: NivelAlerta | None
    apto_para_venta: bool
    recomendacion: str


def dias_para_vencer(fecha_vencimiento: date, hoy: date) -> int:
    """Días calendario restantes. 0 = vence hoy (aún vendible), negativo = vencido."""
    return (fecha_vencimiento - hoy).days


def nivel_por_dias(dias: int, umbral_preventivo: int) -> NivelAlerta | None:
    if dias < 0:
        return NivelAlerta.VENCIDO
    if dias <= UMBRAL_CRITICO_DIAS:
        return NivelAlerta.CRITICA
    if dias <= umbral_preventivo:
        return NivelAlerta.PREVENTIVA
    return None


def evaluar_vencimiento(
    fecha_vencimiento: date,
    hoy: date,
    umbral_preventivo: int = UMBRAL_PREVENTIVO_DEFECTO,
    cantidad_disponible: int = 1,
    dado_de_baja: bool = False,
) -> EvaluacionVencimiento:
    """Clasifica un lote frente a la fecha actual y los dos umbrales."""
    umbral = max(umbral_preventivo, UMBRAL_CRITICO_DIAS)
    dias = dias_para_vencer(fecha_vencimiento, hoy)
    nivel = nivel_por_dias(dias, umbral)

    if dado_de_baja:
        return EvaluacionVencimiento(dias, EstadoLote.BAJA, None, False,
                                     "Lote retirado del inventario.")
    if cantidad_disponible <= 0:
        return EvaluacionVencimiento(dias, EstadoLote.AGOTADO, None, False,
                                     "Lote sin unidades disponibles.")

    if nivel is NivelAlerta.VENCIDO:
        return EvaluacionVencimiento(
            dias, EstadoLote.VENCIDO, nivel, False,
            "Lote vencido: bloquear la venta, separar en cuarentena y registrar la baja.",
        )
    if nivel is NivelAlerta.CRITICA:
        return EvaluacionVencimiento(
            dias, EstadoLote.PROXIMO_VENCER, nivel, True,
            f"Vence en {dias} día(s) (≤ {UMBRAL_CRITICO_DIAS}): priorizar su venta (FEFO) "
            "o gestionar devolución con el proveedor.",
        )
    if nivel is NivelAlerta.PREVENTIVA:
        return EvaluacionVencimiento(
            dias, EstadoLote.PROXIMO_VENCER, nivel, True,
            f"Vence en {dias} día(s): dentro del umbral preventivo de {umbral} días.",
        )
    return EvaluacionVencimiento(dias, EstadoLote.VIGENTE, None, True, "Lote vigente.")
