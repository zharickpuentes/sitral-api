"""Hash de contraseñas con Argon2id y emisión/validación de JWT."""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.infrastructure.config import settings

# Parámetros por defecto de argon2-cffi = perfil RFC 9106 de bajo consumo de
# memoria (Argon2id, t=3, m=64 MiB, p=4).
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(subject: str | int, rol: str, extra: dict[str, Any] | None = None) -> str:
    ahora = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "rol": rol,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Lanza jwt.PyJWTError si el token es inválido o expiró."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["sub", "exp"]},
    )
