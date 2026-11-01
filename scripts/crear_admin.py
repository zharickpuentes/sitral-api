"""Crea el primer Administrador (los demás usuarios se crean vía POST /api/v1/usuarios).

Uso:
    python -m scripts.crear_admin --usuario admin --nombre Ana --apellido Rojas
    (la contraseña se pide por consola y no queda en el historial)
"""
import argparse
import getpass

from sqlalchemy import select

from app.infrastructure.persistence.database import Base, SessionLocal, engine
from app.infrastructure.security import hash_password
from app.domain.shared.enums import RolNombre
from app.infrastructure.persistence.models import Rol, Usuario
from app.infrastructure.persistence.bootstrap import sembrar_datos_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear usuario Administrador de SITRAL")
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--nombre", required=True)
    parser.add_argument("--apellido", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Contraseña (mín. 10 caracteres): ")
    if len(password) < 10:
        raise SystemExit("La contraseña debe tener al menos 10 caracteres.")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        sembrar_datos_base(db)
        if db.scalar(select(Usuario).where(Usuario.usuario == args.usuario)):
            raise SystemExit(f"El usuario '{args.usuario}' ya existe.")
        rol = db.scalar(select(Rol).where(Rol.nombre == RolNombre.ADMINISTRADOR))
        db.add(Usuario(id_rol=rol.id_rol, nombre=args.nombre, apellido=args.apellido,
                       usuario=args.usuario, password_hash=hash_password(password)))
        db.commit()
    print(f"Administrador '{args.usuario}' creado.")


if __name__ == "__main__":
    main()
