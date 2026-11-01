from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.shared.enums import EstadoLote, NivelAlerta, TipoMovimiento
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS


class LoteCreate(BaseModel):
    """Payload to register an incoming batch after scanning it (RQF005)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id_medicamento": 1, "id_proveedor": 1, "numero_lote": "LT-2026-001",
        "cantidad_inicial": 45, "fecha_vencimiento": "2027-03-31",
        "fecha_ingreso": "2026-10-14", "id_factura": None,
    }]})

    id_medicamento: int = Field(..., gt=0, description="Catalog medicine this batch belongs to.")
    id_proveedor: int = Field(..., gt=0, description="Supplier that delivered the batch.")
    numero_lote: str = Field(..., min_length=1, max_length=100, description="Batch/lot number printed by the manufacturer.")
    cantidad_inicial: int = Field(..., gt=0, le=1_000_000, description="Units received.")
    fecha_vencimiento: date = Field(..., description="Expiry date (ISO 8601, YYYY-MM-DD).")
    fecha_ingreso: date | None = Field(None, description="Reception date. Defaults to today (America/Bogota).")
    id_factura: int | None = Field(None, gt=0, description="Optional purchase invoice linked to the entry movement.")


class LoteUpdate(BaseModel):
    """Administrative correction of batch data. Quantities change only through movements."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"fecha_vencimiento": "2027-02-28"}]})

    numero_lote: str | None = Field(None, min_length=1, max_length=100)
    id_proveedor: int | None = Field(None, gt=0)
    fecha_vencimiento: date | None = None
    motivo: str = Field("Corrección administrativa", max_length=200, description="Reason stored in the audit trail.")


class MedicamentoResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_medicamento: int
    nombre: str
    presentacion: str | None = None
    codigo_barras: str


class ProveedorResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_proveedor: int
    nombre: str
    nit: str


class LoteRead(BaseModel):
    """Batch with expiry status computed in real time against the 10-day rule."""

    model_config = ConfigDict(from_attributes=True, json_schema_extra={"examples": [{
        "id_lote": 6, "numero_lote": "LT-2026-PRUEBA", "cantidad_inicial": 45, "cantidad_disponible": 45,
        "fecha_ingreso": "2026-10-14", "fecha_vencimiento": "2026-11-02", "estado": "PROXIMO_VENCER",
        "dias_para_vencer": 19, "nivel_alerta": "PREVENTIVA", "apto_para_venta": True,
        "medicamento": {"id_medicamento": 1, "nombre": "Acetaminofén 500 mg",
                        "presentacion": "Caja x 20 tabletas", "codigo_barras": "7701234567890"},
        "proveedor": {"id_proveedor": 1, "nombre": "Distribuidora Farmacéutica Andina S.A.S.", "nit": "900123456-7"},
    }]})

    id_lote: int
    numero_lote: str
    cantidad_inicial: int
    cantidad_disponible: int
    fecha_ingreso: date
    fecha_vencimiento: date
    estado: EstadoLote
    dias_para_vencer: int = Field(..., description="Calendar days until expiry (negative = expired).")
    nivel_alerta: NivelAlerta | None = Field(None, description="CRITICA when ≤ 10 days, PREVENTIVA within the configurable threshold.")
    apto_para_venta: bool = Field(..., description="False when the batch is expired, depleted or written off.")
    medicamento: MedicamentoResumen
    proveedor: ProveedorResumen


class ValidacionVencimiento(BaseModel):
    """Result of the strict 10-day expiry validation for one batch."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id_lote": 7, "numero_lote": "LT-2026-077", "fecha_vencimiento": "2026-10-22",
        "fecha_evaluacion": "2026-10-14", "dias_para_vencer": 8, "umbral_critico_dias": 10,
        "umbral_preventivo_dias": 30, "dentro_umbral_critico": True, "nivel_alerta": "CRITICA",
        "estado_lote": "PROXIMO_VENCER", "apto_para_venta": True,
        "recomendacion": "Vence en 8 día(s) (≤ 10): priorizar su venta (FEFO) o gestionar devolución con el proveedor.",
    }]})

    id_lote: int
    numero_lote: str
    fecha_vencimiento: date
    fecha_evaluacion: date
    dias_para_vencer: int
    umbral_critico_dias: int = Field(UMBRAL_CRITICO_DIAS, description="Strict, non-editable critical window (10 days).")
    umbral_preventivo_dias: int = Field(..., description="Administrator-configurable early-warning window.")
    dentro_umbral_critico: bool
    nivel_alerta: NivelAlerta | None
    estado_lote: EstadoLote
    apto_para_venta: bool
    recomendacion: str


class EscaneoRequest(BaseModel):
    """Raw content read by the mobile camera (barcode or QR)."""

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"codigo": "(01)07701234567890(17)271231(10)LT-2026-001"},
        {"codigo": "7701234567890"},
    ]})

    codigo: str = Field(..., min_length=4, max_length=500,
                        description="Scanned payload: EAN/GTIN, GS1 element string (with or without parentheses) or SITRAL JSON QR.")


class EscaneoResponse(BaseModel):
    """Data extracted from the scan plus a pre-validation of the batch."""

    formato: str = Field(..., examples=["GS1_LEGIBLE"])
    codigo_barras: str | None = None
    numero_lote: str | None = None
    fecha_vencimiento: date | None = None
    medicamento_registrado: bool = Field(..., description="Whether the product exists in the catalog.")
    medicamento: MedicamentoResumen | None = None
    lote_existente_id: int | None = Field(None, description="id_lote if this batch was already registered.")
    dias_para_vencer: int | None = None
    nivel_alerta: NivelAlerta | None = None
    puede_ingresar: bool = Field(..., description="False if the scanned batch is already expired.")
    advertencias: list[str] = []


class MovimientoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_movimiento: int
    tipo_movimiento: TipoMovimiento
    cantidad: int
    fecha: datetime | None = None
    id_usuario: int
    id_factura: int | None = None
    descripcion: str | None = None


class AlertaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_alerta: int
    tipo: str
    estado: str
    dias_restantes: int
    fecha_generacion: datetime | None = None


class TrazabilidadLote(BaseModel):
    """Full history of a batch from reception to sale or write-off (RQF012)."""

    lote: LoteRead
    movimientos: list[MovimientoRead]
    alertas: list[AlertaResumen]
    unidades_vendidas: int
    unidades_dadas_de_baja: int
