"""Interpretación de códigos escaneados (RQF005, RQNF007).

Formatos soportados:
1. Código de barras lineal EAN-8 / UPC-A / EAN-13 / GTIN-14 (solo dígitos).
2. GS1 DataMatrix / GS1 QR / GS1-128 en formato legible: "(01)07701234567890(17)271231(10)LT-45".
3. GS1 en formato crudo con separador FNC1 (ASCII 29, <GS>) y prefijo de simbología
   opcional (]d2, ]Q3, ]C1).
4. QR interno de SITRAL en JSON: {"codigo_barras": "...", "numero_lote": "...",
   "fecha_vencimiento": "AAAA-MM-DD"} — útil para lotes rotulados por la droguería.

Identificadores de aplicación (AI) GS1 usados: 01 GTIN, 10 lote, 11 fecha de
producción, 17 fecha de vencimiento, 21 serial.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field
from datetime import date

GS = "\x1d"
_PREFIJOS_SIMBOLOGIA = ("]d2", "]Q3", "]C1", "]e0")
_AI_FIJOS = {"01": 14, "11": 6, "15": 6, "17": 6}
_AI_VARIABLES = {"10": 20, "21": 20}


class CodigoInvalidoError(ValueError):
    """El contenido escaneado no corresponde a ningún formato soportado."""


@dataclass
class ResultadoEscaneo:
    formato: str
    codigo_barras: str | None = None
    numero_lote: str | None = None
    fecha_vencimiento: date | None = None
    fecha_produccion: date | None = None
    serial: str | None = None
    advertencias: list[str] = field(default_factory=list)

    def codigos_candidatos(self) -> list[str]:
        """Variantes del GTIN para buscar en el catálogo (GTIN-14 ↔ EAN-13)."""
        if not self.codigo_barras:
            return []
        c = self.codigo_barras
        candidatos = [c]
        if len(c) == 14 and c.startswith("0"):
            candidatos.append(c[1:])
        if len(c) == 13:
            candidatos.append("0" + c)
        return candidatos


def digito_control_gs1_valido(codigo: str) -> bool:
    """Verifica el dígito de control módulo 10 de GTIN-8/12/13/14."""
    if not codigo.isdigit() or len(codigo) not in (8, 12, 13, 14):
        return False
    cuerpo, control = codigo[:-1], int(codigo[-1])
    suma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(cuerpo)))
    return (10 - suma % 10) % 10 == control


def _fecha_gs1(valor: str, ai: str) -> date:
    """AAMMDD; DD = 00 significa último día del mes (regla GS1)."""
    if not re.fullmatch(r"\d{6}", valor):
        raise CodigoInvalidoError(f"Fecha inválida en AI ({ai}): {valor!r}")
    anio, mes, dia = 2000 + int(valor[:2]), int(valor[2:4]), int(valor[4:6])
    if not 1 <= mes <= 12:
        raise CodigoInvalidoError(f"Mes inválido en AI ({ai}): {valor!r}")
    if dia == 0:
        dia = calendar.monthrange(anio, mes)[1]
    try:
        return date(anio, mes, dia)
    except ValueError as exc:
        raise CodigoInvalidoError(f"Fecha inválida en AI ({ai}): {valor!r}") from exc


def _asignar(resultado: ResultadoEscaneo, ai: str, valor: str) -> None:
    if ai == "01":
        resultado.codigo_barras = valor
        if not digito_control_gs1_valido(valor):
            resultado.advertencias.append("El dígito de control del GTIN no es válido.")
    elif ai == "10":
        resultado.numero_lote = valor
    elif ai == "17":
        resultado.fecha_vencimiento = _fecha_gs1(valor, ai)
    elif ai in ("11", "15"):
        resultado.fecha_produccion = _fecha_gs1(valor, ai)
    elif ai == "21":
        resultado.serial = valor


def _parse_gs1_legible(texto: str) -> ResultadoEscaneo:
    resultado = ResultadoEscaneo(formato="GS1_LEGIBLE")
    pares = re.findall(r"\((\d{2,4})\)([^()]*)", texto)
    if not pares:
        raise CodigoInvalidoError("No se encontraron identificadores GS1.")
    for ai, valor in pares:
        _asignar(resultado, ai, valor.strip())
    return resultado


def _parse_gs1_crudo(texto: str) -> ResultadoEscaneo:
    resultado = ResultadoEscaneo(formato="GS1_CRUDO")
    i = 0
    while i < len(texto):
        if texto[i] == GS:
            i += 1
            continue
        ai = texto[i:i + 2]
        i += 2
        if ai in _AI_FIJOS:
            largo = _AI_FIJOS[ai]
            valor = texto[i:i + largo]
            if len(valor) != largo:
                raise CodigoInvalidoError(f"Longitud incompleta en AI ({ai}).")
            i += largo
        elif ai in _AI_VARIABLES:
            fin = texto.find(GS, i)
            fin = len(texto) if fin == -1 else fin
            valor = texto[i:fin][: _AI_VARIABLES[ai]]
            i = fin
        else:
            raise CodigoInvalidoError(f"Identificador GS1 no soportado: ({ai}).")
        _asignar(resultado, ai, valor)
    return resultado


def _parse_json_sitral(texto: str) -> ResultadoEscaneo:
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise CodigoInvalidoError("El QR no contiene un JSON válido.") from exc
    if not isinstance(datos, dict) or "codigo_barras" not in datos:
        raise CodigoInvalidoError("El QR SITRAL debe incluir 'codigo_barras'.")
    resultado = ResultadoEscaneo(formato="QR_SITRAL", codigo_barras=str(datos["codigo_barras"]))
    if datos.get("numero_lote"):
        resultado.numero_lote = str(datos["numero_lote"])
    if datos.get("fecha_vencimiento"):
        try:
            resultado.fecha_vencimiento = date.fromisoformat(str(datos["fecha_vencimiento"]))
        except ValueError as exc:
            raise CodigoInvalidoError("fecha_vencimiento debe tener formato AAAA-MM-DD.") from exc
    return resultado


def interpretar_codigo(contenido: str) -> ResultadoEscaneo:
    """Punto de entrada: detecta el formato y extrae los datos del lote."""
    texto = (contenido or "").strip()
    if not texto:
        raise CodigoInvalidoError("El código escaneado está vacío.")

    for prefijo in _PREFIJOS_SIMBOLOGIA:
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
            break

    if texto.startswith("{"):
        return _parse_json_sitral(texto)
    if texto.startswith("("):
        return _parse_gs1_legible(texto)
    if texto.isdigit() and len(texto) in (8, 12, 13, 14):
        resultado = ResultadoEscaneo(formato="CODIGO_BARRAS", codigo_barras=texto)
        if not digito_control_gs1_valido(texto):
            resultado.advertencias.append("El dígito de control del código no es válido.")
        return resultado
    if texto[:2] in _AI_FIJOS or GS in texto:
        return _parse_gs1_crudo(texto)
    raise CodigoInvalidoError("Formato de código no reconocido (se espera EAN/GTIN, GS1 o QR SITRAL).")
