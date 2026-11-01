from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.infrastructure.config import settings
from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.errors import error_responses
from app.infrastructure.security import create_access_token, hash_password, needs_rehash, verify_password
from app.domain.shared.enums import EstadoRegistro
from app.infrastructure.persistence.models import Rol, Usuario
from app.api.schemas.auth import Token, UsuarioCreate, UsuarioRead

router = APIRouter(tags=["Authentication & Users"])


def a_usuario_read(u: Usuario) -> UsuarioRead:
    return UsuarioRead(id_usuario=u.id_usuario, nombre=u.nombre, apellido=u.apellido, usuario=u.usuario,
                       rol=u.rol.nombre, estado=u.estado, fecha_creacion=u.fecha_creacion)


@router.post(
    "/auth/login",
    response_model=Token,
    summary="Log in and obtain a JWT access token",
    description=(
        "Validates the username and password against the stored **Argon2id** hash (RQF001). "
        "On success returns a signed JWT that must be sent in the `Authorization: Bearer <token>` header. "
        "Uses the OAuth2 password form so it works with the **Authorize** button in Swagger UI."
    ),
    responses=error_responses(401, 403, 422),
)
def login(db: DbSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    user = db.scalar(select(Usuario).where(Usuario.usuario == form.username))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password.",
                            headers={"WWW-Authenticate": "Bearer"})
    if user.estado != EstadoRegistro.ACTIVO:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is inactive.")
    if needs_rehash(user.password_hash):  # actualiza parámetros Argon2 si cambiaron
        user.password_hash = hash_password(form.password)
        db.commit()
    token = create_access_token(user.id_usuario, user.rol.nombre.value)
    return Token(access_token=token, expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, rol=user.rol.nombre)


@router.get(
    "/auth/me",
    response_model=UsuarioRead,
    summary="Get the authenticated user profile",
    description="Returns the profile of the user that owns the JWT sent in the request.",
    responses=error_responses(401, 403),
)
def me(user: CurrentUser) -> UsuarioRead:
    return a_usuario_read(user)


@router.post(
    "/usuarios",
    response_model=UsuarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a system user (Administrator only)",
    description="Registers an Administrator or Pharmacist account (RQF002). The password is hashed with Argon2id.",
    responses=error_responses(400, 401, 403, 409, 422),
)
def crear_usuario(payload: UsuarioCreate, db: DbSession, _: AdminUser) -> UsuarioRead:
    if db.scalar(select(Usuario).where(Usuario.usuario == payload.usuario)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Username '{payload.usuario}' is already taken.")
    rol = db.scalar(select(Rol).where(Rol.nombre == payload.rol))
    if rol is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Role {payload.rol.value} is not configured.")
    user = Usuario(id_rol=rol.id_rol, nombre=payload.nombre, apellido=payload.apellido,
                   usuario=payload.usuario, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return a_usuario_read(user)


@router.get(
    "/usuarios",
    response_model=list[UsuarioRead],
    summary="List system users (Administrator only)",
    responses=error_responses(401, 403),
)
def listar_usuarios(db: DbSession, _: AdminUser) -> list[UsuarioRead]:
    return [a_usuario_read(u) for u in db.scalars(select(Usuario).order_by(Usuario.id_usuario)).unique()]
