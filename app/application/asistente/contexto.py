"""Construcción del contexto RAG a partir de lotes (sin dependencias de base de datos)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from app.application.alertas.servicio import evaluar_lote
from app.domain.asistente.rag import DocumentoRAG, Recuperado, recuperar
from app.domain.inventario.modelos import LoteVista
from app.domain.inventario.vencimiento import UMBRAL_CRITICO_DIAS


@dataclass
class ContextoRAG:
    texto: str
    recuperados: list[Recuperado]
    umbral: int


def documento_lote(lote: LoteVista, hoy: date, umbral: int) -> DocumentoRAG:
    ev = evaluar_lote(lote, hoy, umbral)
    plazo = (f"VENCIÓ hace {-ev.dias_para_vencer} día(s)" if ev.dias_para_vencer < 0
             else f"vence en {ev.dias_para_vencer} día(s)")
    conc = f" {lote.concentracion}" if lote.concentracion and lote.concentracion not in lote.medicamento else ""
    texto = (
        f"Lote {lote.numero_lote} de {lote.medicamento}{conc} ({lote.presentacion or 'sin presentación'}), "
        f"código de barras {lote.codigo_barras}. Proveedor: {lote.proveedor}. Disponibles: "
        f"{lote.cantidad_disponible} de {lote.cantidad_inicial} unidades. Ingresó el {lote.fecha_ingreso.isoformat()}. "
        f"Fecha de vencimiento {lote.fecha_vencimiento.isoformat()}: {plazo}. Estado: {ev.estado_lote.value}. "
        f"Nivel de alerta: {ev.nivel_alerta.value if ev.nivel_alerta else 'NINGUNA'}. "
        f"Precio unitario: {lote.precio:.2f} COP."
    )
    return DocumentoRAG(
        id=f"lote:{lote.id_lote}", texto=texto,
        metadatos={
            "tipo": "lote", "id_lote": lote.id_lote, "numero_lote": lote.numero_lote,
            "medicamento": lote.medicamento, "proveedor": lote.proveedor,
            "dias_para_vencer": ev.dias_para_vencer,
            "nivel_alerta": ev.nivel_alerta.value if ev.nivel_alerta else None,
            "cantidad_disponible": lote.cantidad_disponible,
        },
    )


def _resumen(docs: list[DocumentoRAG], hoy: date, umbral: int) -> str:
    niveles = Counter(d.metadatos["nivel_alerta"] for d in docs)
    unidades = sum(d.metadatos["cantidad_disponible"] for d in docs)
    meds = len({d.metadatos["medicamento"] for d in docs})
    return (
        f"Resumen del inventario al {hoy.isoformat()}: {len(docs)} lotes con existencias de {meds} medicamentos, "
        f"{unidades} unidades en total. Lotes VENCIDOS: {niveles.get('VENCIDO', 0)}; "
        f"CRÍTICOS (≤ {UMBRAL_CRITICO_DIAS} días): {niveles.get('CRITICA', 0)}; "
        f"PREVENTIVOS (11 a {umbral} días): {niveles.get('PREVENTIVA', 0)}."
    )


def construir_contexto(lotes: list[LoteVista], pregunta: str, hoy: date, umbral: int, k: int = 8) -> ContextoRAG:
    docs = [documento_lote(l, hoy, umbral) for l in lotes]
    recuperados = recuperar(docs, pregunta, k=k)
    partes = [_resumen(docs, hoy, umbral)] if docs else ["El inventario no tiene lotes con existencias."]
    partes += [f"[{i}] {r.documento.texto}" for i, r in enumerate(recuperados, start=1)]
    return ContextoRAG("\n".join(partes), recuperados, umbral)
