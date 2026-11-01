"""Normalización de registros de datos.gov.co a nombres de campo canónicos.

Los datasets de datos.gov.co (plataforma Socrata) cambian de nombres de columna
entre versiones y réplicas (por ejemplo `cod_mpio` o `c_digo_dane_del_municipio`).
Cada campo canónico acepta varios nombres candidatos; el primero presente gana.
Ejecute `python -m scripts.explorar_datos_abiertos` para ver los nombres reales.
"""
from __future__ import annotations

import re
from typing import Any

CAMPOS_CUM: dict[str, tuple[str, ...]] = {
    "producto": ("producto", "nombre_producto", "descripcion_producto"),
    "titular": ("titular", "nombre_titular", "nombrerol", "laboratorio"),
    "registro_sanitario": ("registrosanitario", "registro_sanitario", "registro"),
    "estado_registro": ("estadoregistro", "estado_registro"),
    "fecha_vencimiento_registro": ("fechavencimiento", "fecha_vencimiento", "fecha_de_vencimiento"),
    "expediente": ("expediente",),
    "consecutivo_cum": ("consecutivocum", "consecutivo_cum"),
    "descripcion_comercial": ("descripcioncomercial", "descripcion_comercial"),
    "estado_cum": ("estadocum", "estado_cum"),
    "atc": ("atc",),
    "descripcion_atc": ("descripcionatc", "descripcion_atc"),
    "via_administracion": ("viaadministracion", "via_administracion"),
    "principio_activo": ("principioactivo", "principio_activo"),
    "concentracion": ("concentracion",),
    "unidad_medida": ("unidadmedida", "unidad_medida"),
    "forma_farmaceutica": ("formafarmaceutica", "forma_farmaceutica"),
    "modalidad": ("modalidad",),
}

CAMPOS_DIVIPOLA: dict[str, tuple[str, ...]] = {
    "cod_departamento": ("cod_dpto", "c_digo_dane_del_departamento", "codigo_departamento", "dpto_ccdgo", "cod_depto"),
    "departamento": ("dpto", "departamento", "nom_dpto", "nombre_departamento"),
    "cod_municipio": ("cod_mpio", "c_digo_dane_del_municipio", "codigo_municipio", "cod_municipio", "mpio_ccdgo"),
    "municipio": ("nom_mpio", "municipio", "nombre_municipio", "mpio_cnmbr"),
    "region": ("region", "regi_n"),
    "tipo": ("tipo_municipio", "tipo"),
    "latitud": ("latitud", "lat"),
    "longitud": ("longitud", "lon", "long"),
}


def _primero(registro: dict[str, Any], candidatos: tuple[str, ...]) -> Any:
    for clave in candidatos:
        valor = registro.get(clave)
        if valor not in (None, ""):
            return valor
    return None


def _texto(valor: Any) -> str | None:
    return None if valor is None else str(valor).strip()


def _codigo(valor: Any, largo: int) -> str | None:
    """'5001' / '05.001' / 5001 → '05001' (los códigos DANE son texto con ceros a la izquierda)."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor).split(".")[0] if re.fullmatch(r"\d+\.0+", str(valor)) else str(valor))
    return digitos.zfill(largo) if digitos else None


def _numero(valor: Any) -> float | None:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalizar_cum(registro: dict[str, Any]) -> dict[str, Any]:
    return {campo: _texto(_primero(registro, candidatos)) for campo, candidatos in CAMPOS_CUM.items()}


def normalizar_municipio(registro: dict[str, Any]) -> dict[str, Any]:
    r = {campo: _primero(registro, candidatos) for campo, candidatos in CAMPOS_DIVIPOLA.items()}
    cod_mpio = _codigo(r["cod_municipio"], 5)
    cod_dpto = _codigo(r["cod_departamento"], 2) or (cod_mpio[:2] if cod_mpio else None)
    return {
        "cod_departamento": cod_dpto, "departamento": _texto(r["departamento"]),
        "cod_municipio": cod_mpio, "municipio": _texto(r["municipio"]),
        "region": _texto(r["region"]), "tipo": _texto(r["tipo"]),
        "latitud": _numero(r["latitud"]), "longitud": _numero(r["longitud"]),
    }


def cobertura_campos(registros: list[dict[str, Any]]) -> dict[str, float]:
    """Porcentaje de registros normalizados que tienen valor en cada campo (para diagnóstico)."""
    if not registros:
        return {}
    return {c: round(100 * sum(1 for r in registros if r.get(c) not in (None, "")) / len(registros), 1)
            for c in registros[0]}
