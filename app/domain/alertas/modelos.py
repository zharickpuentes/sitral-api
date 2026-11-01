"""Modelos del bounded context Alertas de vencimiento."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.shared.enums import EstadoAlerta, NivelAlerta

PRIORIDAD_NIVEL: dict[str, int] = {
    NivelAlerta.PREVENTIVA.value: 1,
    NivelAlerta.CRITICA.value: 2,
    NivelAlerta.VENCIDO.value: 3,
}


@dataclass
class AlertaRegistro:
    id_alerta: int | None
    id_lote: int
    tipo: str
    estado: EstadoAlerta
    dias_restantes: int
    mensaje: str = ""


@dataclass(frozen=True)
class ConfiguracionAlerta:
    id_configuracion: int
    dias_anticipacion: int
    fecha_actualizacion: datetime | None = None


@dataclass
class ResumenGeneracion:
    fecha_evaluacion: date
    umbral_critico_dias: int
    umbral_preventivo_dias: int
    lotes_evaluados: int = 0
    lotes_actualizados: int = 0
    alertas_nuevas: dict[str, int] = field(default_factory=dict)
    alertas_escaladas: int = 0
