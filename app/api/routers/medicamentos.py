"""CRUD del catálogo de medicamentos (RQF004) — 5 endpoints."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import or_, select

from app.api.deps import AdminUser, DbSession, StaffUser
from app.api.errors import error_responses
from app.domain.shared.enums import EstadoRegistro
from app.infrastructure.persistence.models import Medicamento
from app.api.schemas.catalogo import MedicamentoCreate, MedicamentoRead, MedicamentoUpdate

router = APIRouter(prefix="/medicamentos", tags=["Medicines (catalog)"])

IdMedicamento = Annotated[int, Path(gt=0, description="Medicine identifier (id_medicamento).", examples=[1])]


def _obtener(db, id_medicamento: int) -> Medicamento:
    med = db.get(Medicamento, id_medicamento)
    if med is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Medicine {id_medicamento} was not found.")
    return med


def _codigo_duplicado(db, codigo: str, excluir_id: int | None = None) -> bool:
    q = select(Medicamento.id_medicamento).where(Medicamento.codigo_barras == codigo)
    if excluir_id:
        q = q.where(Medicamento.id_medicamento != excluir_id)
    return db.scalar(q) is not None


@router.get(
    "",
    response_model=list[MedicamentoRead],
    summary="List catalog medicines",
    description="Returns medicines filtered by name or barcode. Inactive medicines are excluded unless `incluir_inactivos=true`.",
    responses=error_responses(401, 403, 422),
)
def listar(
    db: DbSession, _: StaffUser,
    q: Annotated[str | None, Query(max_length=100, description="Text contained in the name or barcode.")] = None,
    incluir_inactivos: bool = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Medicamento]:
    stmt = select(Medicamento).order_by(Medicamento.nombre)
    if q:
        stmt = stmt.where(or_(Medicamento.nombre.ilike(f"%{q}%"), Medicamento.codigo_barras.ilike(f"%{q}%")))
    if not incluir_inactivos:
        stmt = stmt.where(Medicamento.estado == EstadoRegistro.ACTIVO)
    return list(db.scalars(stmt.offset(skip).limit(limit)))


@router.get(
    "/{id_medicamento}",
    response_model=MedicamentoRead,
    summary="Get a medicine by id",
    responses=error_responses(401, 403, 404, 422),
)
def obtener(id_medicamento: IdMedicamento, db: DbSession, _: StaffUser) -> Medicamento:
    return _obtener(db, id_medicamento)


@router.post(
    "",
    response_model=MedicamentoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a medicine",
    description="Adds a medicine to the catalog. The barcode must be unique. Allowed for Administrator and Pharmacist.",
    responses=error_responses(401, 403, 409, 422),
)
def crear(payload: MedicamentoCreate, db: DbSession, _: StaffUser) -> Medicamento:
    if _codigo_duplicado(db, payload.codigo_barras):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Barcode '{payload.codigo_barras}' is already registered.")
    med = Medicamento(**payload.model_dump())
    db.add(med)
    db.commit()
    db.refresh(med)
    return med


@router.put(
    "/{id_medicamento}",
    response_model=MedicamentoRead,
    summary="Update a medicine (Administrator only)",
    description="Partially updates a medicine: only the fields sent are changed. A Pharmacist receives **403**.",
    responses=error_responses(401, 403, 404, 409, 422),
)
def actualizar(id_medicamento: IdMedicamento, payload: MedicamentoUpdate, db: DbSession, _: AdminUser) -> Medicamento:
    med = _obtener(db, id_medicamento)
    cambios = payload.model_dump(exclude_unset=True)
    if "codigo_barras" in cambios and _codigo_duplicado(db, cambios["codigo_barras"], id_medicamento):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Barcode '{cambios['codigo_barras']}' is already registered.")
    for campo, valor in cambios.items():
        setattr(med, campo, valor)
    db.commit()
    db.refresh(med)
    return med


@router.delete(
    "/{id_medicamento}",
    response_model=MedicamentoRead,
    summary="Deactivate a medicine (logical delete, Administrator only)",
    description="Sets the medicine status to INACTIVO instead of deleting the row, preserving batch and invoice traceability.",
    responses=error_responses(401, 403, 404, 422),
)
def desactivar(id_medicamento: IdMedicamento, db: DbSession, _: AdminUser) -> Medicamento:
    med = _obtener(db, id_medicamento)
    med.estado = EstadoRegistro.INACTIVO
    db.commit()
    db.refresh(med)
    return med
