"""Carga datos FICTICIOS pero realistas para demos, pruebas del RAG y capturas.

* ~100 medicamentos genéricos de venta habitual en droguerías de barrio.
* 6 proveedores ficticios (NIT inventados).
* ~170 lotes con vencimientos distribuidos: vencidos, críticos (≤ 10 días),
  preventivos (11–30 días) y vigentes. Fechas relativas a HOY.
* Movimientos de ENTRADA y alertas generadas con la misma lógica de la API.

Uso (requiere haber creado el administrador):
    python -m scripts.sembrar_datos_demo            # solo si el catálogo está vacío
    python -m scripts.sembrar_datos_demo --forzar   # agrega aunque ya existan datos
    python -m scripts.sembrar_datos_demo --solo-municipios   # solo asigna el código DANE a los proveedores
                                                             # (útil si los datos se cargaron con la Guía 5)
"""
import argparse
import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.infrastructure.persistence.database import Base, SessionLocal, engine
from app.api.deps import get_today
from app.domain.shared.enums import RolNombre, TipoMovimiento
from app.domain.inventario.escaneo import digito_control_gs1_valido
from app.domain.inventario.vencimiento import evaluar_vencimiento
from app.infrastructure.persistence.models import Lote, Medicamento, MovimientoInventario, Proveedor, Rol, Usuario
from app.application.alertas.servicio import ServicioAlertas
from app.infrastructure.persistence.bootstrap import migrar_columnas, sembrar_datos_base
from app.infrastructure.persistence.repositorios import (
    SqlAlertaRepositorio, SqlConfiguracionAlertaRepositorio, SqlLoteRepositorio, SqlUnidadDeTrabajo,
)

# (nombre, NIT, teléfono, correo, dirección, código DANE DIVIPOLA del municipio)
PROVEEDORES = [
    ("Distribuidora Farmacéutica Andina S.A.S.", "900123456-7", "6015550101", "ventas@farmandina.example", "Cra 7 # 45-10, Bogotá", "11001"),
    ("Droguería Mayorista del Centro Ltda.", "830456789-1", "6015550202", "pedidos@mayocentro.example", "Cl 13 # 9-40, Bogotá", "11001"),
    ("Medisuministros La Sabana S.A.S.", "901234567-3", "6018520303", "comercial@medisabana.example", "Av. Pradilla # 4-20, Chía", "25175"),
    ("Laboratorios Genéricos Unidos S.A.", "860345678-5", "6044440404", "clientes@genunidos.example", "Cl 50 # 40-20, Itagüí", "05360"),
    ("Coopfarma Distribuciones", "800567890-2", "6027330505", "despachos@coopfarma.example", "Cl 15 # 26-40, Cali", "76001"),
    ("Biofarma Express S.A.S.", "901765432-8", "6018220606", "servicio@biofarmaexp.example", "Cl 13 # 5-20, Mosquera", "25473"),
]

# (principio activo, concentraciones, forma, unidades por caja, precio base COP)
BASES = [
    ("Acetaminofén", ["500 mg", "650 mg"], "tabletas", 20, 3500), ("Ibuprofeno", ["400 mg", "800 mg"], "tabletas", 10, 4200),
    ("Naproxeno", ["250 mg", "500 mg"], "tabletas", 10, 5200), ("Diclofenaco", ["50 mg", "75 mg"], "tabletas", 10, 4800),
    ("Amoxicilina", ["500 mg"], "cápsulas", 21, 9800), ("Amoxicilina", ["250 mg/5 mL"], "suspensión 100 mL", 1, 11500),
    ("Cefalexina", ["500 mg"], "cápsulas", 12, 14500), ("Azitromicina", ["500 mg"], "tabletas", 3, 12900),
    ("Ciprofloxacino", ["500 mg"], "tabletas", 10, 10200), ("Trimetoprim/Sulfametoxazol", ["160/800 mg"], "tabletas", 10, 6800),
    ("Metronidazol", ["500 mg"], "tabletas", 20, 7400), ("Nitrofurantoína", ["100 mg"], "cápsulas", 20, 15800),
    ("Loratadina", ["10 mg"], "tabletas", 10, 3900), ("Cetirizina", ["10 mg"], "tabletas", 10, 4300),
    ("Desloratadina", ["5 mg"], "tabletas", 10, 9600), ("Clorfeniramina", ["4 mg"], "tabletas", 20, 2900),
    ("Omeprazol", ["20 mg", "40 mg"], "cápsulas", 14, 5600), ("Esomeprazol", ["40 mg"], "tabletas", 14, 16800),
    ("Ranitidina", ["150 mg"], "tabletas", 20, 4500), ("Hidróxido de aluminio y magnesio", ["—"], "suspensión 360 mL", 1, 12500),
    ("Loperamida", ["2 mg"], "tabletas", 6, 3800), ("Sales de rehidratación oral", ["—"], "sobres", 4, 6200),
    ("Metoclopramida", ["10 mg"], "tabletas", 20, 4100), ("Bromuro de hioscina", ["10 mg"], "tabletas", 20, 7900),
    ("Losartán", ["50 mg", "100 mg"], "tabletas", 30, 8900), ("Enalapril", ["10 mg", "20 mg"], "tabletas", 30, 5400),
    ("Amlodipino", ["5 mg", "10 mg"], "tabletas", 30, 6700), ("Hidroclorotiazida", ["25 mg"], "tabletas", 30, 4600),
    ("Metoprolol", ["50 mg"], "tabletas", 30, 7200), ("Atorvastatina", ["20 mg", "40 mg"], "tabletas", 30, 11800),
    ("Metformina", ["850 mg", "500 mg"], "tabletas", 30, 6900), ("Glibenclamida", ["5 mg"], "tabletas", 30, 4700),
    ("Ácido acetilsalicílico", ["100 mg"], "tabletas", 30, 4900), ("Levotiroxina", ["50 mcg", "100 mcg"], "tabletas", 30, 13400),
    ("Salbutamol", ["100 mcg/dosis"], "inhalador 200 dosis", 1, 15900), ("Beclometasona", ["250 mcg/dosis"], "inhalador 200 dosis", 1, 32500),
    ("Prednisolona", ["5 mg"], "tabletas", 20, 8400), ("Dexametasona", ["4 mg/mL"], "ampolla 1 mL", 1, 3600),
    ("Betametasona", ["0,05 %"], "crema 40 g", 1, 9900), ("Clotrimazol", ["1 %"], "crema 20 g", 1, 6900),
    ("Fluconazol", ["150 mg"], "cápsula", 1, 4900), ("Aciclovir", ["5 %"], "crema 10 g", 1, 8200),
    ("Ácido fólico", ["1 mg"], "tabletas", 30, 3200), ("Sulfato ferroso", ["300 mg"], "tabletas", 30, 4400),
    ("Complejo B", ["—"], "tabletas", 30, 7600), ("Vitamina C", ["500 mg"], "tabletas masticables", 30, 8900),
    ("Calcio + Vitamina D", ["600 mg/400 UI"], "tabletas", 30, 14200), ("Albendazol", ["400 mg"], "tableta", 1, 2600),
    ("Dimenhidrinato", ["50 mg"], "tabletas", 12, 5100), ("Sertralina", ["50 mg"], "tabletas", 30, 21500),
    ("Acetaminofén", ["150 mg/5 mL"], "jarabe 60 mL", 1, 5900), ("Ibuprofeno", ["100 mg/5 mL"], "suspensión 120 mL", 1, 8700),
    ("Dextrometorfano", ["15 mg/5 mL"], "jarabe 120 mL", 1, 9300), ("Ambroxol", ["30 mg/5 mL"], "jarabe 120 mL", 1, 8100),
    ("Guaifenesina", ["100 mg/5 mL"], "jarabe 120 mL", 1, 7800), ("Solución salina 0,9 %", ["—"], "bolsa 500 mL", 1, 4900),
    ("Lidocaína", ["2 %"], "gel 30 g", 1, 9800), ("Mupirocina", ["2 %"], "ungüento 15 g", 1, 18900),
    ("Diclofenaco", ["1 %"], "gel 60 g", 1, 10800), ("Clonazepam", ["2 mg"], "tabletas", 30, 9900),
    ("Fluoxetina", ["20 mg"], "cápsulas", 28, 12600), ("Tramadol", ["50 mg"], "cápsulas", 10, 9700),
    ("Meloxicam", ["15 mg"], "tabletas", 10, 6300), ("Ketorolaco", ["10 mg"], "tabletas", 10, 5500),
    ("Insulina NPH", ["100 UI/mL"], "vial 10 mL", 1, 38900), ("Enoxaparina", ["40 mg"], "jeringa prellenada", 1, 24900),
    ("Warfarina", ["5 mg"], "tabletas", 30, 9200), ("Furosemida", ["40 mg"], "tabletas", 20, 3900),
    ("Espironolactona", ["25 mg"], "tabletas", 20, 6600), ("Carvedilol", ["12,5 mg"], "tabletas", 30, 10900),
    ("Montelukast", ["10 mg"], "tabletas", 30, 19800), ("Tamsulosina", ["0,4 mg"], "cápsulas", 30, 23900),
    ("Ondansetrón", ["8 mg"], "tabletas", 10, 13500), ("Butilbromuro de hioscina + Metamizol", ["10/250 mg"], "tabletas", 10, 8900),
    ("Metamizol", ["500 mg"], "tabletas", 10, 4300), ("Nistatina", ["100.000 UI/mL"], "suspensión 60 mL", 1, 11800),
    ("Permetrina", ["5 %"], "loción 60 mL", 1, 15800), ("Óxido de zinc", ["25 %"], "crema 60 g", 1, 7900),
    ("Clindamicina", ["300 mg"], "cápsulas", 16, 21900), ("Doxiciclina", ["100 mg"], "cápsulas", 10, 9900),
    ("Levofloxacino", ["500 mg"], "tabletas", 7, 18500), ("Pantoprazol", ["40 mg"], "tabletas", 14, 15200),
    ("Simeticona", ["80 mg"], "tabletas masticables", 20, 6800), ("Bisacodilo", ["5 mg"], "tabletas", 20, 5200),
    ("Lactulosa", ["65 %"], "jarabe 200 mL", 1, 16900), ("Propranolol", ["40 mg"], "tabletas", 30, 5100),
    ("Valsartán", ["160 mg"], "tabletas", 30, 21800), ("Rosuvastatina", ["20 mg"], "tabletas", 30, 24500),
    ("Clopidogrel", ["75 mg"], "tabletas", 30, 18900), ("Alopurinol", ["300 mg"], "tabletas", 30, 7300),
    ("Colchicina", ["0,5 mg"], "tabletas", 30, 12400), ("Hidroxicloroquina", ["200 mg"], "tabletas", 30, 39800),
]


def ean13(rng: random.Random, usados: set[str]) -> str:
    while True:
        cuerpo = "770" + "".join(str(rng.randint(0, 9)) for _ in range(9))
        for d in range(10):
            codigo = cuerpo + str(d)
            if digito_control_gs1_valido(codigo):
                break
        if codigo not in usados:
            usados.add(codigo)
            return codigo


def dias_vencimiento(rng: random.Random) -> int:
    """Distribución pensada para que el RAG y las alertas tengan casos de todo tipo."""
    r = rng.random()
    if r < 0.06:
        return -rng.randint(1, 45)     # vencidos aún en estantería
    if r < 0.15:
        return rng.randint(0, 10)      # críticos
    if r < 0.28:
        return rng.randint(11, 30)     # preventivos
    return rng.randint(31, 720)        # vigentes


def servicio_alertas(db) -> ServicioAlertas:
    """Raíz de composición del script: mismos adaptadores SQL que usa la API."""
    return ServicioAlertas(SqlLoteRepositorio(db), SqlAlertaRepositorio(db),
                           SqlConfiguracionAlertaRepositorio(db), SqlUnidadDeTrabajo(db))


def asignar_municipios(db) -> None:
    """Asigna códigos DANE a los proveedores ficticios (por NIT) y, al resto, Bogotá (11001)."""
    por_nit = {p[1]: p[5] for p in PROVEEDORES}
    n = 0
    for prov in db.scalars(select(Proveedor)):
        if not prov.cod_municipio:
            prov.cod_municipio = por_nit.get(prov.nit, "11001")
            n += 1
    db.commit()
    print(f"Proveedores actualizados con código DANE: {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cargar datos ficticios de demostración en SITRAL")
    parser.add_argument("--forzar", action="store_true")
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--solo-municipios", action="store_true",
                        help="Solo asigna cod_municipio (DANE) a los proveedores existentes y termina.")
    args = parser.parse_args()
    rng = random.Random(args.semilla)
    hoy = get_today()

    Base.metadata.create_all(bind=engine)
    migrar_columnas(engine)
    with SessionLocal() as db:
        sembrar_datos_base(db)
        if args.solo_municipios:
            asignar_municipios(db)
            return
        admin = db.scalar(select(Usuario).join(Rol).where(Rol.nombre == RolNombre.ADMINISTRADOR))
        if admin is None:
            raise SystemExit("Primero cree el administrador: python -m scripts.crear_admin ...")
        if db.scalar(select(func.count(Medicamento.id_medicamento))) and not args.forzar:
            raise SystemExit("El catálogo ya tiene datos. Use --forzar para agregar más.")

        proveedores = []
        for nombre, nit, tel, correo, dir_, mpio in PROVEEDORES:
            prov = db.scalar(select(Proveedor).where(Proveedor.nit == nit))
            if prov is None:
                prov = Proveedor(nombre=nombre, nit=nit, telefono=tel, correo=correo, direccion=dir_,
                                 cod_municipio=mpio)
                db.add(prov)
            elif not prov.cod_municipio:
                prov.cod_municipio = mpio
            proveedores.append(prov)
        db.flush()

        usados = set(db.scalars(select(Medicamento.codigo_barras)))
        medicamentos = []
        for activo, concentraciones, forma, unidades, precio in BASES:
            for conc in concentraciones:
                nombre = activo if conc == "—" else f"{activo} {conc}"
                presentacion = f"Caja x {unidades} {forma}" if unidades > 1 else forma.capitalize()
                med = Medicamento(
                    nombre=nombre, presentacion=presentacion, concentracion=None if conc == "—" else conc,
                    codigo_barras=ean13(rng, usados),
                    registro_sanitario=f"INVIMA {rng.randint(2015, 2025)}M-{rng.randint(1000000, 9999999)}",
                    precio=Decimal(precio + rng.choice([0, 0, 200, 500, -100])),
                )
                db.add(med)
                medicamentos.append(med)
        db.flush()

        servicio = servicio_alertas(db)
        umbral = servicio.umbral_preventivo()
        n_lotes = 0
        for med in medicamentos:
            for _ in range(rng.choices([1, 2, 3], weights=[45, 40, 15])[0]):
                dias = dias_vencimiento(rng)
                vence = hoy + timedelta(days=dias)
                ingreso = min(hoy - timedelta(days=rng.randint(5, 240)), vence - timedelta(days=rng.randint(60, 540)))
                inicial = rng.choice([10, 12, 20, 24, 30, 36, 40, 50, 60, 100])
                disponible = max(1, int(inicial * rng.uniform(0.1, 1.0)))
                prov = rng.choice(proveedores)
                ev = evaluar_vencimiento(vence, hoy, umbral, disponible)
                lote = Lote(
                    id_medicamento=med.id_medicamento, id_proveedor=prov.id_proveedor,
                    numero_lote=f"L{ingreso:%y%m}-{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJK')}",
                    cantidad_inicial=inicial, cantidad_disponible=disponible,
                    fecha_ingreso=ingreso, fecha_vencimiento=vence, estado=ev.estado_lote,
                )
                db.add(lote)
                db.flush()
                db.add(MovimientoInventario(id_lote=lote.id_lote, id_usuario=admin.id_usuario,
                                            tipo_movimiento=TipoMovimiento.ENTRADA, cantidad=inicial,
                                            descripcion="Carga inicial (datos de demostración)"))
                if disponible < inicial:
                    db.add(MovimientoInventario(id_lote=lote.id_lote, id_usuario=admin.id_usuario,
                                                tipo_movimiento=TipoMovimiento.SALIDA, cantidad=inicial - disponible,
                                                descripcion="Ventas acumuladas (datos de demostración)"))
                n_lotes += 1
        db.commit()

        resumen = servicio.generar(hoy)
        print(f"Proveedores: {len(proveedores)} | Medicamentos: {len(medicamentos)} | Lotes: {n_lotes}")
        print(f"Alertas generadas: {resumen.alertas_nuevas} (fecha de evaluación {hoy})")


if __name__ == "__main__":
    main()
