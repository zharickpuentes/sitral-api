"""Formato uniforme de errores HTTP y su documentación en OpenAPI."""
import logging
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("sitral")


class ErrorResponse(BaseModel):
    """Standard error body returned by every SITRAL endpoint."""

    status_code: int = Field(..., examples=[404])
    error: str = Field(..., examples=["Not Found"])
    message: str = Field(..., examples=["Batch 9999 was not found."])
    path: str = Field(..., examples=["/api/v1/lotes/9999"])
    timestamp: datetime
    details: list[dict[str, Any]] | None = None


_EJEMPLOS: dict[int, tuple[str, str]] = {
    400: ("Business rule violated.", "Cannot register an expired batch (expiry date 2026-10-01)."),
    401: ("Missing, invalid or expired JWT token.", "Not authenticated"),
    403: ("Authenticated user lacks the required role.", "This action requires one of the roles: ADMINISTRADOR."),
    404: ("Requested resource does not exist.", "Batch 9999 was not found."),
    409: ("Resource conflicts with an existing record.", "Batch 'LT-2026-001' already exists for this medicine."),
    422: ("Request payload or parameters failed validation.", "Request validation failed."),
    429: ("Too many requests.", "SITRAL AI limit of 10 requests per minute reached."),
    503: ("External service unavailable (circuit OPEN or provider down) and no cached copy.",
          "invima_cum unavailable (Circuit 'invima_cum' is OPEN; retry in 18 s.) and no cached copy."),
}


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Bloque `responses=` reutilizable para documentar errores en Swagger UI."""
    out: dict[int | str, dict[str, Any]] = {}
    for code in codes:
        descripcion, mensaje = _EJEMPLOS[code]
        out[code] = {
            "model": ErrorResponse,
            "description": descripcion,
            "content": {"application/json": {"example": {
                "status_code": code,
                "error": HTTPStatus(code).phrase,
                "message": mensaje,
                "path": "/api/v1/...",
                "timestamp": "2026-10-14T13:00:00Z",
                "details": None,
            }}},
        }
    return out


def _cuerpo(request: Request, code: int, message: str, details: list | None = None) -> dict:
    return jsonable_encoder(ErrorResponse(
        status_code=code,
        error=HTTPStatus(code).phrase,
        message=message,
        path=request.url.path,
        timestamp=datetime.now(timezone.utc),
        details=details,
    ))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_cuerpo(request, exc.status_code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        detalles = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_cuerpo(request, 422, "Request validation failed.", detalles))

    # Excepciones del dominio → códigos HTTP (la capa de dominio no conoce HTTP).
    from app.domain.asistente.puertos import LimiteExcedidoError, LLMError
    from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError

    @app.exception_handler(LLMError)
    async def llm_exception_handler(request: Request, exc: LLMError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(status_code=exc.status_code, content=_cuerpo(request, exc.status_code, exc.message),
                            headers=headers)

    @app.exception_handler(LimiteExcedidoError)
    async def limite_exception_handler(request: Request, exc: LimiteExcedidoError):
        return JSONResponse(status_code=429, content=_cuerpo(request, 429, str(exc)),
                            headers={"Retry-After": str(exc.retry_after)})

    @app.exception_handler(FuenteNoDisponibleError)
    async def fuente_exception_handler(request: Request, exc: FuenteNoDisponibleError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(status_code=503, content=_cuerpo(request, 503, exc.mensaje), headers=headers)

    @app.exception_handler(IntegrityError)
    async def integrity_exception_handler(request: Request, exc: IntegrityError):
        logger.warning("IntegrityError: %s", exc.orig)
        return JSONResponse(status_code=409, content=_cuerpo(
            request, 409, "The operation conflicts with existing data (duplicate or invalid reference)."))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Error no controlado en %s", request.url.path)
        return JSONResponse(status_code=500, content=_cuerpo(request, 500, "Internal server error."))
