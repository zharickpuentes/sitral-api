"""Dependencias inyectables: sesión, usuario autenticado, roles y fecha local."""
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.infrastructure.persistence.database import get_db
from app.infrastructure.security import decode_access_token
from app.domain.shared.enums import EstadoRegistro, RolNombre
from app.infrastructure.persistence.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

DbSession = Annotated[Session, Depends(get_db)]

_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_today() -> date:
    """Fecha actual en Colombia (no la del servidor en UTC).

    Se sobrescribe en las pruebas para fijar la fecha y probar los límites
    de 10 y 11 días de forma determinista.
    """
    return datetime.now(ZoneInfo(settings.TIMEZONE)).date()


Today = Annotated[date, Depends(get_today)]


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> Usuario:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _NO_AUTENTICADO
    user = db.get(Usuario, user_id)
    if user is None:
        raise _NO_AUTENTICADO
    if user.estado != EstadoRegistro.ACTIVO:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is inactive.")
    return user


CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def require_roles(*roles: RolNombre) -> Callable[[Usuario], Usuario]:
    def _checker(user: CurrentUser) -> Usuario:
        if user.rol.nombre not in roles:
            nombres = ", ".join(r.value for r in roles)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This action requires one of the roles: {nombres}.")
        return user
    return _checker


AdminUser = Annotated[Usuario, Depends(require_roles(RolNombre.ADMINISTRADOR))]
StaffUser = Annotated[Usuario, Depends(require_roles(RolNombre.ADMINISTRADOR, RolNombre.FARMACEUTA))]


# =============================================================================
# Raíz de composición (composition root)
# -----------------------------------------------------------------------------
# Aquí, y solo aquí, se conectan los puertos del dominio con sus adaptadores
# concretos. Cada servicio de aplicación recibe sus dependencias por CONSTRUCTOR.
# En las pruebas se reemplazan con app.dependency_overrides o con Mocks.
# =============================================================================
from app.api.contenedor import contenedor  # noqa: E402
from app.application.alertas.servicio import ServicioAlertas  # noqa: E402
from app.application.asistente.servicio import PreciosLLM, ServicioAsistenteIA  # noqa: E402
from app.application.datos_abiertos.servicio import ServicioDatosAbiertos  # noqa: E402
from app.domain.asistente.puertos import LLMError, LLMPort  # noqa: E402
from app.infrastructure.llm.gemini import get_llm  # noqa: E402
from app.infrastructure.observabilidad import ai_soporte  # noqa: E402
from app.infrastructure.persistence.repositorios import (  # noqa: E402
    SqlAlertaRepositorio, SqlConfiguracionAlertaRepositorio, SqlLoteRepositorio, SqlUnidadDeTrabajo,
)


def get_servicio_alertas(db: DbSession) -> ServicioAlertas:
    return ServicioAlertas(
        lotes=SqlLoteRepositorio(db),
        alertas=SqlAlertaRepositorio(db),
        configuracion=SqlConfiguracionAlertaRepositorio(db),
        uow=SqlUnidadDeTrabajo(db),
    )


AlertasDep = Annotated[ServicioAlertas, Depends(get_servicio_alertas)]


def _asistente(db: Session, alertas: ServicioAlertas, llm: LLMPort) -> ServicioAsistenteIA:
    return ServicioAsistenteIA(
        lotes=SqlLoteRepositorio(db),
        umbral_preventivo=alertas.umbral_preventivo(),
        llm=llm,
        bitacora=ai_soporte.BitacoraJsonl(settings.AI_LOG_PATH),
        limitador=ai_soporte.limitador,
        precios=PreciosLLM(settings.LLM_PRICE_INPUT_PER_1M, settings.LLM_PRICE_OUTPUT_PER_1M),
    )


def get_servicio_asistente(db: DbSession, alertas: AlertasDep,
                           llm: Annotated[LLMPort, Depends(get_llm)]) -> ServicioAsistenteIA:
    return _asistente(db, alertas, llm)


class _SinLLM:
    """Marcador para operaciones que no llaman al modelo (p. ej. vista previa del contexto RAG)."""

    model = "none"

    def generate(self, system: str, prompt: str, *, temperature=None):  # pragma: no cover
        raise LLMError(503, "This operation does not use the LLM.")


def get_servicio_contexto(db: DbSession, alertas: AlertasDep) -> ServicioAsistenteIA:
    return _asistente(db, alertas, _SinLLM())


AsistenteDep = Annotated[ServicioAsistenteIA, Depends(get_servicio_asistente)]
ContextoDep = Annotated[ServicioAsistenteIA, Depends(get_servicio_contexto)]


def get_servicio_datos_abiertos(db: DbSession, alertas: AlertasDep) -> ServicioDatosAbiertos:
    return ServicioDatosAbiertos(
        catalogo_cum=contenedor.cum(),
        divipola=contenedor.divipola(),
        analitica=contenedor.analitica(),
        lotes=SqlLoteRepositorio(db),
        umbral_preventivo=alertas.umbral_preventivo(),
        max_principios=settings.ANALYTICS_MAX_PRINCIPIOS,
    )


DatosAbiertosDep = Annotated[ServicioDatosAbiertos, Depends(get_servicio_datos_abiertos)]
