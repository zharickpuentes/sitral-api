"""Motor analítico con DuckDB sobre datos JSON.

Los registros normalizados (INVIMA CUM, DANE DIVIPOLA e inventario de SITRAL)
se escriben como archivos JSON y DuckDB los lee con `read_json_auto`; luego se
ejecutan consultas SQL analíticas con estadísticas descriptivas.
Cada análisis usa una conexión en memoria nueva (sin estado compartido).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import duckdb

# ---------------------------------------------------------------- consultas SQL
SQL_OFERTA_POR_PRINCIPIO = """
SELECT principio_buscado                                   AS principio_activo,
       COUNT(*)                                            AS presentaciones,
       COUNT(DISTINCT titular)                             AS titulares,
       COUNT(DISTINCT forma_farmaceutica)                  AS formas_farmaceuticas,
       MODE(forma_farmaceutica)                            AS forma_mas_comun,
       MODE(titular)                                       AS titular_principal,
       ROUND(100.0 * AVG(CASE WHEN upper(coalesce(estado_registro, '')) LIKE 'VIGENTE%'
                              THEN 1 ELSE 0 END), 1)       AS pct_registros_vigentes
FROM cum
GROUP BY principio_buscado
ORDER BY presentaciones DESC, principio_activo
"""

SQL_RESUMEN_OFERTA = """
WITH t AS (SELECT principio_buscado, COUNT(*) AS n FROM cum GROUP BY principio_buscado)
SELECT COUNT(*)                          AS principios,
       SUM(n)                            AS presentaciones_totales,
       ROUND(AVG(n), 2)                  AS media,
       MEDIAN(n)                         AS mediana,
       ROUND(STDDEV_SAMP(n), 2)          AS desviacion_estandar,
       MIN(n)                            AS minimo,
       MAX(n)                            AS maximo
FROM t
"""

SQL_ESTADISTICAS_INVENTARIO = """
SELECT nivel,
       COUNT(*)                                   AS lotes,
       SUM(cantidad)                              AS unidades,
       ROUND(AVG(dias), 1)                        AS media_dias,
       MEDIAN(dias)                               AS mediana_dias,
       ROUND(STDDEV_SAMP(dias), 1)                AS desviacion_dias,
       MIN(dias)                                  AS min_dias,
       MAX(dias)                                  AS max_dias,
       QUANTILE_CONT(dias, 0.25)                  AS p25_dias,
       QUANTILE_CONT(dias, 0.75)                  AS p75_dias,
       ROUND(SUM(valor), 0)                       AS valor_cop
FROM inventario
GROUP BY nivel
ORDER BY CASE nivel WHEN 'VENCIDO' THEN 0 WHEN 'CRITICA' THEN 1 WHEN 'PREVENTIVA' THEN 2 ELSE 3 END
"""

SQL_RESUMEN_INVENTARIO = """
SELECT COUNT(*)                                   AS lotes,
       SUM(cantidad)                              AS unidades,
       ROUND(AVG(cantidad), 1)                    AS media_unidades_por_lote,
       MEDIAN(cantidad)                           AS mediana_unidades_por_lote,
       ROUND(STDDEV_SAMP(cantidad), 1)            AS desviacion_unidades,
       ROUND(SUM(valor), 0)                       AS valor_total_cop,
       ROUND(SUM(CASE WHEN nivel = 'VENCIDO' THEN valor ELSE 0 END), 0)            AS perdida_vencidos_cop,
       ROUND(SUM(CASE WHEN nivel IN ('CRITICA', 'VENCIDO') THEN valor ELSE 0 END), 0) AS valor_en_riesgo_cop
FROM inventario
"""

SQL_COBERTURA_REGIONAL = """
SELECT coalesce(d.departamento, 'SIN UBICACIÓN')   AS departamento,
       coalesce(d.municipio, 'SIN UBICACIÓN')      AS municipio,
       CAST(i.cod_municipio AS VARCHAR)            AS cod_municipio,
       COUNT(DISTINCT i.proveedor)                 AS proveedores,
       COUNT(*)                                    AS lotes,
       SUM(i.cantidad)                             AS unidades,
       SUM(CASE WHEN i.nivel IN ('CRITICA', 'VENCIDO') THEN 1 ELSE 0 END) AS lotes_en_riesgo,
       ROUND(100.0 * AVG(CASE WHEN i.nivel IN ('CRITICA', 'VENCIDO') THEN 1 ELSE 0 END), 1) AS pct_en_riesgo
FROM inventario i
LEFT JOIN divipola d ON CAST(d.cod_municipio AS VARCHAR) = CAST(i.cod_municipio AS VARCHAR)
GROUP BY 1, 2, 3
ORDER BY lotes DESC
"""

SQL_RESUMEN_DIVIPOLA = """
WITH m AS (SELECT cod_departamento, departamento, COUNT(*) AS municipios
           FROM divipola GROUP BY cod_departamento, departamento)
SELECT COUNT(*)                       AS departamentos,
       SUM(municipios)                AS municipios,
       ROUND(AVG(municipios), 1)      AS media_municipios_por_departamento,
       MEDIAN(municipios)             AS mediana,
       ROUND(STDDEV_SAMP(municipios), 1) AS desviacion_estandar,
       MIN(municipios)                AS minimo,
       MAX(municipios)                AS maximo
FROM m
"""

_COLUMNAS = {
    "cum": ("principio_buscado", "titular", "forma_farmaceutica", "estado_registro", "registro_sanitario", "producto"),
    "inventario": ("id_lote", "proveedor", "cod_municipio", "cantidad", "dias", "nivel", "valor"),
    "divipola": ("cod_departamento", "departamento", "cod_municipio", "municipio"),
}


class MotorDuckDB:
    """Implementa MotorAnaliticoPort."""

    @staticmethod
    def _filas(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
        cur = con.execute(sql)
        nombres = [c[0] for c in cur.description]
        return [dict(zip(nombres, (float(v) if hasattr(v, "is_finite") else v for v in fila)))
                for fila in cur.fetchall()]

    @staticmethod
    def _cargar(con: duckdb.DuckDBPyConnection, carpeta: Path, tabla: str, registros: list[dict[str, Any]]) -> None:
        """Escribe los registros en JSON y los carga con read_json_auto (procesamiento de JSON con DuckDB)."""
        columnas = _COLUMNAS[tabla]
        filas = [{c: r.get(c) for c in columnas} for r in registros]
        ruta = carpeta / f"{tabla}.json"
        ruta.write_text(json.dumps(filas, ensure_ascii=False, default=str), encoding="utf-8")
        if filas:
            con.execute(f"CREATE TABLE {tabla} AS SELECT * FROM read_json_auto(?)", [str(ruta)])
        else:  # tabla vacía con las columnas esperadas
            con.execute(f"CREATE TABLE {tabla} ({', '.join(f'{c} VARCHAR' for c in columnas)})")
            if tabla == "inventario":
                con.execute("DROP TABLE inventario")
                con.execute("CREATE TABLE inventario (id_lote INTEGER, proveedor VARCHAR, cod_municipio VARCHAR, "
                            "cantidad INTEGER, dias INTEGER, nivel VARCHAR, valor DOUBLE)")

    def _analizar(self, tablas: dict[str, list[dict[str, Any]]], consultas: dict[str, str]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="sitral_duckdb_") as tmp, duckdb.connect(":memory:") as con:
            for tabla, registros in tablas.items():
                self._cargar(con, Path(tmp), tabla, registros)
            resultado: dict[str, Any] = {}
            for nombre, sql in consultas.items():
                filas = self._filas(con, sql)
                resultado[nombre] = filas[0] if nombre.startswith("resumen") and filas else filas
            resultado["sql"] = {k: " ".join(v.split()) for k, v in consultas.items()}
            return resultado

    # ------------------------------------------------------------ puerto
    def oferta_por_principio(self, registros_cum: list[dict[str, Any]]) -> dict[str, Any]:
        return self._analizar({"cum": registros_cum},
                              {"filas": SQL_OFERTA_POR_PRINCIPIO, "resumen": SQL_RESUMEN_OFERTA})

    def estadisticas_inventario(self, inventario: list[dict[str, Any]]) -> dict[str, Any]:
        return self._analizar({"inventario": inventario},
                              {"filas": SQL_ESTADISTICAS_INVENTARIO, "resumen": SQL_RESUMEN_INVENTARIO})

    def cobertura_regional(self, inventario: list[dict[str, Any]],
                           municipios: list[dict[str, Any]]) -> dict[str, Any]:
        return self._analizar({"inventario": inventario, "divipola": municipios},
                              {"filas": SQL_COBERTURA_REGIONAL, "resumen_divipola": SQL_RESUMEN_DIVIPOLA})
