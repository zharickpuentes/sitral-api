from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.shared.enums import EstadoRegistro, RolNombre


class Token(BaseModel):
    """JWT access token issued after a successful login."""

    access_token: str = Field(..., description="Signed JWT (HS256). Send it as `Authorization: Bearer <token>`.")
    token_type: str = Field("bearer", examples=["bearer"])
    expires_in: int = Field(..., description="Token lifetime in seconds.", examples=[3600])
    rol: RolNombre = Field(..., description="Role of the authenticated user.")


class UsuarioCreate(BaseModel):
    """Payload to register a new system user (Administrator only, RQF002)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Laura", "apellido": "Gómez", "usuario": "lgomez",
        "password": "Farma#2026Segura", "rol": "FARMACEUTA",
    }]})

    nombre: str = Field(..., min_length=2, max_length=100, description="First name.")
    apellido: str = Field(..., min_length=2, max_length=100, description="Last name.")
    usuario: str = Field(..., min_length=4, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$",
                         description="Unique username used to log in.")
    password: str = Field(..., min_length=10, max_length=128,
                          description="Plain password (min. 10 chars). Stored only as an Argon2id hash.")
    rol: RolNombre = Field(..., description="ADMINISTRADOR or FARMACEUTA.")


class UsuarioRead(BaseModel):
    """Public representation of a user (the password hash is never exposed)."""

    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nombre: str
    apellido: str
    usuario: str
    rol: RolNombre
    estado: EstadoRegistro
    fecha_creacion: datetime | None = None
