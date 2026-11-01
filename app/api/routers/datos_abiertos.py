"""Datos abiertos colombianos: INVIMA CUM y DANE DIVIPOLA (Guía 6)."""
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.api.deps import AdminUser, DatosAbiertosDep, StaffUser
from app.api.errors import error_responses
from app.api.schemas.datos_abiertos import (
    EstadoCircuitoResponse, ResultadoFuenteResponse, VerificacionRegistroResponse,
)

router = APIRouter(prefix="/datos-abiertos", tags=["Colombian open data (datos.gov.co)"])

Fuente = Annotated[Literal["invima_cum", "dane_divipola"],
                   Path(description="External source: `invima_cum` or `dane_divipola`.")]

_RESILIENCIA = (
    "Calls go through a **circuit breaker** (CLOSED → OPEN after 3 consecutive failures → HALF_OPEN after the "
    "recovery time) and **retry with exponential backoff** (0.5 s, 1 s). If the API fails or the circuit is OPEN, "
    "the last successful copy is returned with `origen = cache`; without a cached copy the API answers **503**."
)


@router.get(
    "/medicamentos",
    response_model=ResultadoFuenteResponse,
    summary="Search INVIMA's Unique Medicine Code (CUM) dataset",
    description="Full-text search on the INVIMA CUM dataset published on datos.gov.co (Socrata SODA API). "
                + _RESILIENCIA,
    responses=error_responses(401, 403, 422, 503),
)
def buscar_medicamentos(
    _: StaffUser, servicio: DatosAbiertosDep,
    q: Annotated[str, Query(min_length=3, max_length=100, description="Active ingredient, product or holder.",
                            examples=["acetaminofen"])],
    limite: Annotated[int, Query(ge=1, le=500)] = 50,
) -> ResultadoFuenteResponse:
    return ResultadoFuenteResponse(**asdict(servicio.buscar_medicamentos(q, limite)))


@router.get(
    "/medicamentos/registro",
    response_model=VerificacionRegistroResponse,
    summary="Verify an INVIMA sanitary registration number",
    description="Looks up a sanitary registration (e.g. `INVIMA 2019M-0012345`) in the CUM dataset and returns the "
                "exact matches. Useful to validate the `registro_sanitario` of the SITRAL catalog. " + _RESILIENCIA,
    responses=error_responses(401, 403, 422, 503),
)
def verificar_registro(
    _: StaffUser, servicio: DatosAbiertosDep,
    registro: Annotated[str, Query(min_length=5, max_length=60, examples=["INVIMA 2019M-0012345"])],
) -> VerificacionRegistroResponse:
    encontrado, res = servicio.verificar_registro(registro)
    return VerificacionRegistroResponse(registro_sanitario=registro, encontrado=encontrado,
                                        resultado=ResultadoFuenteResponse(**asdict(res)))


@router.get(
    "/municipios",
    response_model=ResultadoFuenteResponse,
    summary="List Colombian municipalities (DANE DIVIPOLA)",
    description="Returns DANE's DIVIPOLA codes (department and municipality) from datos.gov.co, optionally "
                "filtered by department code (e.g. `11` = Bogotá D.C., `25` = Cundinamarca). " + _RESILIENCIA,
    responses=error_responses(401, 403, 422, 503),
)
def municipios(
    _: StaffUser, servicio: DatosAbiertosDep,
    cod_departamento: Annotated[str | None, Query(pattern=r"^\d{1,2}$", examples=["25"])] = None,
) -> ResultadoFuenteResponse:
    return ResultadoFuenteResponse(**asdict(servicio.municipios(cod_departamento)))


@router.get(
    "/circuitos",
    response_model=list[EstadoCircuitoResponse],
    summary="Get the circuit breaker state of each external API",
    description="Shows the current state (CLOSED, OPEN, HALF_OPEN), counters and the latest state transitions.",
    responses=error_responses(401, 403),
)
def estado_circuitos(_: StaffUser, servicio: DatosAbiertosDep) -> list[EstadoCircuitoResponse]:
    return [EstadoCircuitoResponse(**e) for e in servicio.estado_circuitos()]


@router.post(
    "/circuitos/{fuente}/simular-falla",
    response_model=EstadoCircuitoResponse,
    summary="Simulate an outage of an external API (Administrator only)",
    description="With `activar=true` every call to the source fails as if datos.gov.co were down, so the circuit "
                "breaker can be demonstrated: 3 failed calls → OPEN; after the recovery time → HALF_OPEN; "
                "deactivate the outage and call again → CLOSED.",
    responses=error_responses(401, 403, 422),
)
def simular_falla(fuente: Fuente, _: AdminUser, servicio: DatosAbiertosDep,
                  activar: Annotated[bool, Query()] = True) -> EstadoCircuitoResponse:
    adaptador = servicio.fuentes()[fuente]
    adaptador.simular_falla(activar)
    return EstadoCircuitoResponse(**adaptador.estado())


@router.post(
    "/circuitos/{fuente}/reiniciar",
    response_model=EstadoCircuitoResponse,
    summary="Reset a circuit breaker to CLOSED (Administrator only)",
    responses=error_responses(401, 403, 422),
)
def reiniciar_circuito(fuente: Fuente, _: AdminUser, servicio: DatosAbiertosDep) -> EstadoCircuitoResponse:
    adaptador = servicio.fuentes()[fuente]
    adaptador.reiniciar()
    return EstadoCircuitoResponse(**adaptador.estado())
