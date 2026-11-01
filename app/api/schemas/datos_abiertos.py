from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResultadoFuenteResponse(BaseModel):
    """Normalized records returned by a Colombian open-data source."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "fuente": "invima_cum", "origen": "api", "estado_circuito": "CLOSED",
        "consultado_en": "2026-10-30T16:00:00+00:00", "advertencia": None, "total": 1,
        "registros": [{"producto": "ACETAMINOFEN 500 MG TABLETAS", "titular": "LABORATORIO EJEMPLO S.A.",
                       "registro_sanitario": "INVIMA 2019M-0012345", "estado_registro": "Vigente",
                       "principio_activo": "ACETAMINOFEN", "forma_farmaceutica": "TABLETA"}],
    }]})

    fuente: str = Field(..., description="invima_cum or dane_divipola.")
    origen: str = Field(..., description="`api` = fresh data; `cache` = last successful copy (API down or circuit OPEN).")
    estado_circuito: str = Field(..., description="Circuit breaker state: CLOSED, OPEN or HALF_OPEN.")
    consultado_en: str
    advertencia: str | None = None
    total: int
    registros: list[dict[str, Any]]


class VerificacionRegistroResponse(BaseModel):
    """Result of checking an INVIMA sanitary registration against the CUM dataset."""

    registro_sanitario: str
    encontrado: bool
    resultado: ResultadoFuenteResponse


class EstadoCircuitoResponse(BaseModel):
    """Live state of a circuit breaker protecting an external API."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "fuente": "dane_divipola", "nombre": "dane_divipola", "dataset_id": "gdxc-w37w", "estado": "OPEN",
        "fallos_consecutivos": 3, "umbral_fallos": 3, "tiempo_recuperacion_s": 20.0, "reintentar_en_s": 14.2,
        "total_llamadas": 5, "total_fallos": 3, "total_rechazadas": 2, "falla_simulada": True,
        "historial": [{"momento": "2026-10-30T16:01:02+00:00", "desde": "CLOSED", "hacia": "OPEN",
                       "motivo": "3 consecutive failures: Simulated outage"}],
    }]})

    fuente: str
    nombre: str
    dataset_id: str
    estado: str = Field(..., description="CLOSED → normal; OPEN → calls rejected; HALF_OPEN → one trial call allowed.")
    fallos_consecutivos: int
    umbral_fallos: int
    tiempo_recuperacion_s: float
    reintentar_en_s: float
    total_llamadas: int
    total_fallos: int
    total_rechazadas: int
    falla_simulada: bool
    historial: list[dict[str, str]]


class AnalisisResponse(BaseModel):
    """Output of a DuckDB analytical query: result rows, descriptive summary and the SQL executed."""

    filas: list[dict[str, Any]]
    resumen: dict[str, Any] | None = None
    resumen_divipola: dict[str, Any] | None = None
    origenes: dict[str, str] | None = None
    origen_divipola: str | None = None
    sql: dict[str, str]
