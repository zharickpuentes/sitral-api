"""Plantillas de prompt: Zero-shot, Few-shot y Chain-of-Thought (CoT)."""
from __future__ import annotations

from datetime import date
from enum import Enum

from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS


class Tecnica(str, Enum):
    ZERO_SHOT = "zero_shot"
    FEW_SHOT = "few_shot"
    COT = "cot"


def system_prompt(hoy: date, umbral: int) -> str:
    return (
        "Eres el asistente de inventario de SITRAL, un sistema de trazabilidad de lotes para una droguería "
        "independiente en Colombia. Respondes a la administradora y a los farmaceutas.\n"
        f"Fecha de hoy: {hoy.isoformat()} (America/Bogota).\n"
        "Reglas de negocio:\n"
        f"- Un lote con {UMBRAL_CRITICO_DIAS} días o menos para vencer es CRÍTICO: se prioriza su venta (FEFO) "
        "o se gestiona su devolución con el proveedor.\n"
        f"- Entre 11 y {umbral} días es PREVENTIVO.\n"
        "- Un lote vencido no se puede vender: se separa en cuarentena y se registra su baja.\n"
        "Instrucciones:\n"
        "- Usa EXCLUSIVAMENTE la información del CONTEXTO. Si el dato no está, di que no aparece en el inventario.\n"
        "- Cita siempre el número de lote, el medicamento y la cantidad disponible.\n"
        "- No inventes lotes, cifras ni fechas.\n"
        "- No des recomendaciones clínicas, de dosis ni de uso de medicamentos; solo información de inventario.\n"
        "- Responde en español, de forma clara y concisa."
    )


_EJEMPLOS_FEW_SHOT = """\
### Ejemplo 1
CONTEXTO:
[1] Lote LT-A1 de Loratadina 10 mg (Caja x 10 tabletas). Proveedor: Distribuciones Andes. Disponibles: 12 de 30 unidades. Vence en 3 día(s). Estado: PROXIMO_VENCER. Nivel de alerta: CRITICA.
[2] Lote LT-B7 de Loratadina 10 mg (Caja x 10 tabletas). Proveedor: Distribuciones Andes. Disponibles: 40 de 40 unidades. Vence en 268 día(s). Estado: VIGENTE. Nivel de alerta: NINGUNA.
PREGUNTA: ¿Qué lote de loratadina vendo primero?
RESPUESTA:
- **Vender primero: LT-A1** (Loratadina 10 mg) — 12 unidades, vence en 3 días (CRÍTICO).
- LT-B7 — 40 unidades, vigente (268 días).
Acción: aplicar FEFO; si LT-A1 no rota en 3 días, solicitar devolución a Distribuciones Andes.

### Ejemplo 2
CONTEXTO:
[1] Lote LT-C3 de Omeprazol 20 mg (Caja x 14 cápsulas). Proveedor: Farmaprov. Disponibles: 6 de 50 unidades. VENCIÓ hace 3 día(s). Estado: VENCIDO. Nivel de alerta: VENCIDO.
PREGUNTA: ¿Tengo productos vencidos?
RESPUESTA:
- **LT-C3** (Omeprazol 20 mg) — 6 unidades, venció hace 3 días.
Acción: retirar de la venta, separar en cuarentena y registrar la baja en SITRAL.

### Ejemplo 3
CONTEXTO:
[1] Lote LT-D9 de Ibuprofeno 400 mg (Caja x 10 tabletas). Proveedor: Farmaprov. Disponibles: 25 de 25 unidades. Estado: VIGENTE.
PREGUNTA: ¿Cuánta metformina tengo?
RESPUESTA:
- No aparece metformina en el inventario consultado.
"""


def construir_prompt(tecnica: Tecnica, contexto: str, pregunta: str) -> str:
    if tecnica is Tecnica.ZERO_SHOT:
        return f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}\nRESPUESTA:"

    if tecnica is Tecnica.FEW_SHOT:
        return (
            "Responde siguiendo exactamente el formato de los ejemplos: viñetas con lote en negrita, "
            "medicamento, cantidad y días, y una línea final de 'Acción'.\n\n"
            f"{_EJEMPLOS_FEW_SHOT}\n### Caso real\nCONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}\nRESPUESTA:"
        )

    return (
        f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}\n\n"
        "Resuelve paso a paso antes de responder:\n"
        "1. Identifica en el CONTEXTO los lotes relevantes para la pregunta.\n"
        "2. Para cada uno anota los días que faltan para vencer y la cantidad disponible.\n"
        f"3. Clasifícalos con la regla de negocio (vencido, crítico ≤ {UMBRAL_CRITICO_DIAS} días, preventivo, vigente).\n"
        "4. Decide la acción recomendada para cada lote y verifica que no omitiste ninguno.\n"
        "Formato de salida:\nRazonamiento:\n1. ...\n2. ...\n3. ...\n4. ...\nRespuesta final:\n- ..."
    )
