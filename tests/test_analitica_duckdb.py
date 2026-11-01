"""Consultas analíticas SQL en DuckDB sobre JSON (requiere `pip install duckdb`)."""
import pytest

pytest.importorskip("duckdb")

from app.infrastructure.analitica.duckdb_motor import MotorDuckDB  # noqa: E402

INVENTARIO = [
    {"id_lote": 1, "proveedor": "A", "cod_municipio": "11001", "cantidad": 10, "dias": -2, "nivel": "VENCIDO", "valor": 1000},
    {"id_lote": 2, "proveedor": "A", "cod_municipio": "11001", "cantidad": 20, "dias": 4, "nivel": "CRITICA", "valor": 2000},
    {"id_lote": 3, "proveedor": "B", "cod_municipio": "25175", "cantidad": 30, "dias": 8, "nivel": "CRITICA", "valor": 3000},
    {"id_lote": 4, "proveedor": "B", "cod_municipio": "25175", "cantidad": 40, "dias": 200, "nivel": "VIGENTE", "valor": 4000},
    {"id_lote": 5, "proveedor": "C", "cod_municipio": None, "cantidad": 50, "dias": 300, "nivel": "VIGENTE", "valor": 5000},
]
DIVIPOLA = [
    {"cod_departamento": "11", "departamento": "BOGOTÁ, D.C.", "cod_municipio": "11001", "municipio": "BOGOTÁ, D.C."},
    {"cod_departamento": "25", "departamento": "CUNDINAMARCA", "cod_municipio": "25175", "municipio": "CHÍA"},
    {"cod_departamento": "25", "departamento": "CUNDINAMARCA", "cod_municipio": "25473", "municipio": "MOSQUERA"},
    {"cod_departamento": "25", "departamento": "CUNDINAMARCA", "cod_municipio": "25754", "municipio": "SOACHA"},
]
CUM = [
    {"principio_buscado": "ACETAMINOFEN", "titular": "LAB A", "forma_farmaceutica": "TABLETA", "estado_registro": "Vigente"},
    {"principio_buscado": "ACETAMINOFEN", "titular": "LAB B", "forma_farmaceutica": "TABLETA", "estado_registro": "Vigente"},
    {"principio_buscado": "ACETAMINOFEN", "titular": "LAB B", "forma_farmaceutica": "JARABE", "estado_registro": "Vencido"},
    {"principio_buscado": "LOSARTAN", "titular": "LAB C", "forma_farmaceutica": "TABLETA", "estado_registro": "Vigente"},
]

motor = MotorDuckDB()


def test_estadisticas_descriptivas_del_inventario():
    r = motor.estadisticas_inventario(INVENTARIO)
    criticos = next(f for f in r["filas"] if f["nivel"] == "CRITICA")
    assert criticos["lotes"] == 2 and criticos["media_dias"] == 6 and criticos["mediana_dias"] == 6
    assert criticos["min_dias"] == 4 and criticos["max_dias"] == 8 and criticos["desviacion_dias"] == pytest.approx(2.8, 0.01)
    assert r["resumen"]["valor_total_cop"] == 15000
    assert r["resumen"]["valor_en_riesgo_cop"] == 6000 and r["resumen"]["perdida_vencidos_cop"] == 1000
    assert "MEDIAN" in r["sql"]["filas"]


def test_oferta_por_principio_activo():
    r = motor.oferta_por_principio(CUM)
    acet = next(f for f in r["filas"] if f["principio_activo"] == "ACETAMINOFEN")
    assert acet["presentaciones"] == 3 and acet["titulares"] == 2 and acet["forma_mas_comun"] == "TABLETA"
    assert acet["pct_registros_vigentes"] == pytest.approx(66.7, 0.01)
    assert r["resumen"]["principios"] == 2 and r["resumen"]["mediana"] == 2


def test_cobertura_regional_con_join_divipola():
    r = motor.cobertura_regional(INVENTARIO, DIVIPOLA)
    por_mpio = {f["cod_municipio"]: f for f in r["filas"]}
    assert por_mpio["11001"]["lotes_en_riesgo"] == 2 and por_mpio["11001"]["pct_en_riesgo"] == 100
    assert por_mpio["25175"]["municipio"] == "CHÍA"
    assert any(f["municipio"] == "SIN UBICACIÓN" for f in r["filas"])
    assert r["resumen_divipola"]["departamentos"] == 2 and r["resumen_divipola"]["municipios"] == 4


def test_tablas_vacias_no_fallan():
    assert motor.estadisticas_inventario([])["filas"] == []
    assert motor.oferta_por_principio([])["filas"] == []
