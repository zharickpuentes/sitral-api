"""Caso de uso: asistente de inventario con LLM + RAG (inyección por constructor)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.application.asistente.contexto import ContextoRAG, construir_contexto
from app.application.asistente.prompts import Tecnica, construir_prompt, system_prompt
from app.domain.asistente.puertos import BitacoraPort, LimiteExcedidoError, LimitadorPort, LLMError, LLMPort
from app.domain.inventario.puertos import LoteRepositorio


@dataclass
class RespuestaAsistente:
    respuesta: str
    tecnica: Tecnica
    modelo: str
    fuentes: list[dict[str, Any]]
    uso: dict[str, int]
    latencia_ms: int
    costo_estimado_usd: float
    prompt: str | None = None


@dataclass
class PreciosLLM:
    """Precios en USD por millón de tokens (los de razonamiento se cobran como salida)."""

    entrada_por_millon: float
    salida_por_millon: float

    def costo(self, entrada: int, salida: int, razonamiento: int) -> float:
        return round(entrada * self.entrada_por_millon / 1e6
                     + (salida + razonamiento) * self.salida_por_millon / 1e6, 8)


@dataclass
class ServicioAsistenteIA:
    """Responde preguntas sobre el inventario. Todas sus dependencias llegan por constructor."""

    lotes: LoteRepositorio
    umbral_preventivo: int
    llm: LLMPort
    bitacora: BitacoraPort
    limitador: LimitadorPort
    precios: PreciosLLM = field(default_factory=lambda: PreciosLLM(0.75, 3.75))

    def contexto(self, pregunta: str, hoy: date, top_k: int = 8) -> ContextoRAG:
        return construir_contexto(self.lotes.listar_con_existencias(), pregunta, hoy, self.umbral_preventivo, top_k)

    @staticmethod
    def fuentes(ctx: ContextoRAG) -> list[dict[str, Any]]:
        return [{
            "id_lote": r.documento.metadatos["id_lote"], "numero_lote": r.documento.metadatos["numero_lote"],
            "medicamento": r.documento.metadatos["medicamento"],
            "dias_para_vencer": r.documento.metadatos["dias_para_vencer"],
            "nivel_alerta": r.documento.metadatos["nivel_alerta"], "puntaje": r.puntaje,
        } for r in ctx.recuperados]

    def consultar(self, usuario_id: int, pregunta: str, tecnica: Tecnica, hoy: date,
                  top_k: int = 8, incluir_prompt: bool = False) -> RespuestaAsistente:
        espera = self.limitador.verificar(usuario_id)
        if espera is not None:
            raise LimiteExcedidoError(self.limitador.maximo, espera)

        ctx = self.contexto(pregunta, hoy, top_k)
        prompt = construir_prompt(tecnica, ctx.texto, pregunta)
        base_log = {"usuario": usuario_id, "tecnica": tecnica.value, "pregunta": pregunta, "modelo": self.llm.model}
        try:
            res = self.llm.generate(system_prompt(hoy, ctx.umbral), prompt)
        except LLMError as exc:
            self.bitacora.registrar({**base_log, "estado": exc.status_code, "error": exc.message})
            raise

        uso = {"input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
               "thinking_tokens": res.thinking_tokens, "total_tokens": res.total_tokens}
        respuesta = RespuestaAsistente(
            respuesta=res.text, tecnica=tecnica, modelo=res.model, fuentes=self.fuentes(ctx), uso=uso,
            latencia_ms=res.latency_ms,
            costo_estimado_usd=self.precios.costo(res.input_tokens, res.output_tokens, res.thinking_tokens),
            prompt=prompt if incluir_prompt else None,
        )
        self.bitacora.registrar({
            **base_log, "estado": 200, "uso": uso, "latencia_ms": res.latency_ms,
            "costo_estimado_usd": respuesta.costo_estimado_usd,
            "fuentes": [f["numero_lote"] for f in respuesta.fuentes], "respuesta": res.text,
        })
        return respuesta
