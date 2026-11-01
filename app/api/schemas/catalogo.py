from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.shared.enums import EstadoRegistro


# ----------------------------- Medicamentos (RQF004) -----------------------------
class MedicamentoBase(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150, description="Commercial or generic name.")
    presentacion: str | None = Field(None, max_length=100, description="Packaging, e.g. 'Box x 20 tablets'.")
    concentracion: str | None = Field(None, max_length=50, description="Strength, e.g. '500 mg'.")
    codigo_barras: str = Field(..., min_length=4, max_length=100,
                               description="EAN-13/GTIN-14 barcode or QR content that identifies the product.")
    registro_sanitario: str | None = Field(None, max_length=50,
                                           description="INVIMA sanitary registration number.")
    precio: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2, description="Retail price in COP.")


class MedicamentoCreate(MedicamentoBase):
    """Payload to add a medicine to the catalog."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Acetaminofén 500 mg", "presentacion": "Caja x 20 tabletas",
        "concentracion": "500 mg", "codigo_barras": "7701234567890",
        "registro_sanitario": "INVIMA 2019M-0012345", "precio": 3500,
    }]})


class MedicamentoUpdate(BaseModel):
    """Partial update: only the fields sent are modified."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"precio": 3800, "estado": "ACTIVO"}]})

    nombre: str | None = Field(None, min_length=2, max_length=150)
    presentacion: str | None = Field(None, max_length=100)
    concentracion: str | None = Field(None, max_length=50)
    codigo_barras: str | None = Field(None, min_length=4, max_length=100)
    registro_sanitario: str | None = Field(None, max_length=50)
    precio: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)
    estado: EstadoRegistro | None = None


class MedicamentoRead(MedicamentoBase):
    model_config = ConfigDict(from_attributes=True)

    id_medicamento: int
    estado: EstadoRegistro


# ----------------------------- Proveedores (RQF003) ------------------------------
class ProveedorBase(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150, description="Supplier legal name.")
    nit: str = Field(..., pattern=r"^\d{6,10}(-\d)?$",
                     description="Colombian tax ID (NIT), optionally with check digit: 900123456-7.")
    telefono: str | None = Field(None, max_length=30)
    correo: EmailStr | None = None
    direccion: str | None = Field(None, max_length=200)
    cod_municipio: str | None = Field(None, pattern=r"^\d{5}$",
                                      description="DANE DIVIPOLA municipality code (5 digits), e.g. 11001 = Bogotá D.C.")


class ProveedorCreate(ProveedorBase):
    """Payload to register a medicine supplier."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Distribuidora Farmacéutica Andina S.A.S.", "nit": "900123456-7",
        "telefono": "6015550101", "correo": "ventas@farmaandina.co", "direccion": "Cra 7 # 45-10, Bogotá",
        "cod_municipio": "11001",
    }]})


class ProveedorUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"telefono": "6015550202"}]})

    nombre: str | None = Field(None, min_length=2, max_length=150)
    nit: str | None = Field(None, pattern=r"^\d{6,10}(-\d)?$")
    telefono: str | None = Field(None, max_length=30)
    correo: EmailStr | None = None
    direccion: str | None = Field(None, max_length=200)
    cod_municipio: str | None = Field(None, pattern=r"^\d{5}$")
    estado: EstadoRegistro | None = None


class ProveedorRead(ProveedorBase):
    model_config = ConfigDict(from_attributes=True)

    id_proveedor: int
    estado: EstadoRegistro
    correo: str | None = None
