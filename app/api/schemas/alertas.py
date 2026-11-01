from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.shared.enums import EstadoAlerta
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS, UMBRAL_PREVENTIVO_MAXIMO


class AlertaRead(BaseModel):
    """Expiry alert with the data required by RQF008 (medicine, batch, quantity, expiry)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id_alerta": 12, "id_lote": 7, "tipo": "CRITICA", "estado": "PENDIENTE",
        "mensaje": "CRITICA: Amoxicilina 500 mg lote LT-2026-077 vence en 8 día(s) (2026-10-22). Disponibles: 30.",
        "dias_restantes": 8, "fecha_generacion": "2026-10-14T06:00:00",
        "medicamento": "Amoxicilina 500 mg", "numero_lote": "LT-2026-077",
        "cantidad_disponible": 30, "fecha_vencimiento": "2026-10-22",
    }]})

    id_alerta: int
    id_lote: int
    tipo: str = Field(..., description="PREVENTIVA, CRITICA (≤ 10 days) or VENCIDO.")
    estado: EstadoAlerta
    mensaje: str
    dias_restantes: int = Field(..., description="Days left, recalculated on every alert run.")
    fecha_generacion: datetime | None = None
    medicamento: str
    numero_lote: str
    cantidad_disponible: int
    fecha_vencimiento: date


class ResumenGeneracion(BaseModel):
    """Outcome of an alert evaluation run (manual or scheduled)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "fecha_evaluacion": "2026-10-14", "umbral_critico_dias": 10, "umbral_preventivo_dias": 30,
        "lotes_evaluados": 100, "lotes_actualizados": 4,
        "alertas_nuevas": {"PREVENTIVA": 3, "CRITICA": 1, "VENCIDO": 0}, "alertas_escaladas": 1,
    }]})

    fecha_evaluacion: date
    umbral_critico_dias: int
    umbral_preventivo_dias: int
    lotes_evaluados: int
    lotes_actualizados: int
    alertas_nuevas: dict[str, int]
    alertas_escaladas: int


class ConfiguracionAlertaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_configuracion: int
    dias_anticipacion: int = Field(..., description="Configurable early-warning threshold (days).")
    umbral_critico_dias: int = Field(UMBRAL_CRITICO_DIAS, description="Strict critical threshold; cannot be changed.")
    fecha_actualizacion: datetime | None = None


class ConfiguracionAlertaUpdate(BaseModel):
    """Administrator adjustment of the early-warning baseline (Fase 1 baseline: 30 days)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"dias_anticipacion": 30}]})

    dias_anticipacion: int = Field(
        ..., ge=UMBRAL_CRITICO_DIAS, le=UMBRAL_PREVENTIVO_MAXIMO,
        description=f"Early-warning days. Must be between {UMBRAL_CRITICO_DIAS} and {UMBRAL_PREVENTIVO_MAXIMO}; "
                    f"values below {UMBRAL_CRITICO_DIAS} are rejected with 422 because the 10-day rule is strict.",
    )
