"""Analítica con DuckDB sobre datos JSON de las APIs colombianas y del inventario (Guía 6)."""
from fastapi import APIRouter

from app.api.deps import DatosAbiertosDep, StaffUser, Today
from app.api.errors import error_responses
from app.api.schemas.datos_abiertos import AnalisisResponse

router = APIRouter(prefix="/analitica", tags=["Analytics (DuckDB)"])


@router.get(
    "/oferta-mercado",
    response_model=AnalisisResponse,
    summary="Market supply per active ingredient (INVIMA CUM × inventory, DuckDB)",
    description=(
        "For the active ingredients in stock (batches at risk first), queries INVIMA's CUM dataset, loads the JSON "
        "into DuckDB and computes: registered presentations, distinct marketing-authorization holders, "
        "pharmaceutical forms, most common form and % of valid registrations, plus descriptive statistics "
        "(mean, median, standard deviation, min, max) of presentations per ingredient. "
        "It helps decide whether a critical batch can be replaced by an equivalent product."
    ),
    responses=error_responses(401, 403),
)
def oferta_mercado(_: StaffUser, servicio: DatosAbiertosDep, hoy: Today) -> AnalisisResponse:
    return AnalisisResponse(**servicio.oferta_mercado(hoy))


@router.get(
    "/inventario",
    response_model=AnalisisResponse,
    summary="Descriptive statistics of the inventory by expiry level (DuckDB)",
    description=(
        "Per alert level (VENCIDO, CRITICA, PREVENTIVA, VIGENTE): batches, units, mean / median / standard "
        "deviation / min / max / P25 / P75 of days to expiry and stock value in COP; plus totals, expired-stock "
        "loss and value at risk (critical + expired)."
    ),
    responses=error_responses(401, 403),
)
def estadisticas_inventario(_: StaffUser, servicio: DatosAbiertosDep, hoy: Today) -> AnalisisResponse:
    return AnalisisResponse(**servicio.estadisticas_inventario(hoy))


@router.get(
    "/cobertura-regional",
    response_model=AnalisisResponse,
    summary="Inventory by supplier location (DANE DIVIPOLA × inventory, DuckDB)",
    description=(
        "Joins the inventory with DANE's DIVIPOLA municipalities using the supplier's DANE code and reports "
        "suppliers, batches, units and % of batches at risk per department/municipality, plus descriptive "
        "statistics of municipalities per department."
    ),
    responses=error_responses(401, 403, 503),
)
def cobertura_regional(_: StaffUser, servicio: DatosAbiertosDep, hoy: Today) -> AnalisisResponse:
    return AnalisisResponse(**servicio.cobertura_regional(hoy))
