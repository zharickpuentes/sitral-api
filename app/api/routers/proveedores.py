"""CRUD de proveedores (RQF003) — 5 endpoints."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, StaffUser
from app.api.errors import error_responses
from app.domain.shared.enums import EstadoRegistro
from app.infrastructure.persistence.models import Proveedor
from app.api.schemas.catalogo import ProveedorCreate, ProveedorRead, ProveedorUpdate

router = APIRouter(prefix="/proveedores", tags=["Suppliers"])

IdProveedor = Annotated[int, Path(gt=0, description="Supplier identifier (id_proveedor).", examples=[1])]


def _obtener(db, id_proveedor: int) -> Proveedor:
    prov = db.get(Proveedor, id_proveedor)
    if prov is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Supplier {id_proveedor} was not found.")
    return prov


@router.get("", response_model=list[ProveedorRead], summary="List suppliers",
            description="Returns active suppliers ordered by name.", responses=error_responses(401, 403, 422))
def listar(db: DbSession, _: StaffUser, incluir_inactivos: bool = False,
           skip: Annotated[int, Query(ge=0)] = 0,
           limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[Proveedor]:
    stmt = select(Proveedor).order_by(Proveedor.nombre)
    if not incluir_inactivos:
        stmt = stmt.where(Proveedor.estado == EstadoRegistro.ACTIVO)
    return list(db.scalars(stmt.offset(skip).limit(limit)))


@router.get("/{id_proveedor}", response_model=ProveedorRead, summary="Get a supplier by id",
            responses=error_responses(401, 403, 404, 422))
def obtener(id_proveedor: IdProveedor, db: DbSession, _: StaffUser) -> Proveedor:
    return _obtener(db, id_proveedor)


@router.post("", response_model=ProveedorRead, status_code=status.HTTP_201_CREATED,
             summary="Create a supplier", description="Registers a supplier. The NIT must be unique.",
             responses=error_responses(401, 403, 409, 422))
def crear(payload: ProveedorCreate, db: DbSession, _: StaffUser) -> Proveedor:
    if db.scalar(select(Proveedor.id_proveedor).where(Proveedor.nit == payload.nit)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"NIT '{payload.nit}' is already registered.")
    prov = Proveedor(**payload.model_dump())
    db.add(prov)
    db.commit()
    db.refresh(prov)
    return prov


@router.put("/{id_proveedor}", response_model=ProveedorRead, summary="Update a supplier (Administrator only)",
            responses=error_responses(401, 403, 404, 409, 422))
def actualizar(id_proveedor: IdProveedor, payload: ProveedorUpdate, db: DbSession, _: AdminUser) -> Proveedor:
    prov = _obtener(db, id_proveedor)
    cambios = payload.model_dump(exclude_unset=True)
    if "nit" in cambios and db.scalar(select(Proveedor.id_proveedor).where(
            Proveedor.nit == cambios["nit"], Proveedor.id_proveedor != id_proveedor)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"NIT '{cambios['nit']}' is already registered.")
    for campo, valor in cambios.items():
        setattr(prov, campo, valor)
    db.commit()
    db.refresh(prov)
    return prov


@router.delete("/{id_proveedor}", response_model=ProveedorRead,
               summary="Deactivate a supplier (logical delete, Administrator only)",
               responses=error_responses(401, 403, 404, 422))
def desactivar(id_proveedor: IdProveedor, db: DbSession, _: AdminUser) -> Proveedor:
    prov = _obtener(db, id_proveedor)
    prov.estado = EstadoRegistro.INACTIVO
    db.commit()
    db.refresh(prov)
    return prov
