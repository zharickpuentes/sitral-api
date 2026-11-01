"""Asistente IA sobre el inventario: RAG + prompt engineering (Guía 5, Sesión 10)."""
from fastapi import APIRouter, HTTPException

from app.api.deps import AsistenteDep, ContextoDep, StaffUser, Today
from app.api.errors import error_responses
from app.api.schemas.ai import (
    ComparacionRequest, ComparacionResponse, ConsultaIARequest, ConsultaIAResponse,
    ContextoRAGResponse, FuenteRAG, UsoTokens,
)
from app.application.asistente.prompts import Tecnica
from app.application.asistente.servicio import RespuestaAsistente, ServicioAsistenteIA
from app.infrastructure.config import settings

router = APIRouter(prefix="/ai", tags=["AI assistant (LLM + RAG)"])

_ERRORES_IA = {
    429: {"description": "Rate limit reached (SITRAL per-user limit or AI provider quota). See `Retry-After`."},
    502: {"description": "The AI provider returned an invalid or empty answer."},
    503: {"description": "AI service not configured, invalid API key, model unavailable or provider down."},
    504: {"description": "The AI provider did not answer before the timeout."},
}


def _a_respuesta(r: RespuestaAsistente) -> ConsultaIAResponse:
    return ConsultaIAResponse(
        respuesta=r.respuesta, tecnica=r.tecnica, modelo=r.modelo,
        fuentes=[FuenteRAG(**f) for f in r.fuentes], uso=UsoTokens(**r.uso),
        latencia_ms=r.latencia_ms, costo_estimado_usd=r.costo_estimado_usd, prompt=r.prompt,
    )


@router.post(
    "/consultas",
    response_model=ConsultaIAResponse,
    summary="Ask the inventory assistant (RAG + prompting technique)",
    description=(
        "Answers a natural-language question about stock, batches and expiry using **basic RAG**:\n"
        "1. **Retrieve** – every batch with stock becomes a text document; BM25 plus an urgency boost selects the "
        "`top_k` most relevant ones.\n"
        "2. **Augment** – those documents and an inventory summary are injected into the prompt as CONTEXT.\n"
        "3. **Generate** – Google Gemini answers using only that context.\n\n"
        "`tecnica` selects the prompt template: `zero_shot` (instructions only), `few_shot` (3 worked examples) or "
        "`cot` (explicit step-by-step reasoning). The response reports tokens, latency and estimated cost. "
        f"Each user may send up to {settings.AI_RATE_LIMIT_PER_MINUTE} requests per minute."
    ),
    responses={**error_responses(401, 403, 422), **_ERRORES_IA},
)
def consultar(payload: ConsultaIARequest, user: StaffUser, asistente: AsistenteDep, hoy: Today) -> ConsultaIAResponse:
    return _a_respuesta(asistente.consultar(user.id_usuario, payload.pregunta, payload.tecnica, hoy,
                                            payload.top_k, payload.incluir_prompt))


@router.post(
    "/comparar",
    response_model=ComparacionResponse,
    summary="Compare zero-shot, few-shot and chain-of-thought on the same question",
    description="Runs the same question with the three techniques (3 LLM calls) to build the comparison table.",
    responses={**error_responses(401, 403, 422), **_ERRORES_IA},
)
def comparar(payload: ComparacionRequest, user: StaffUser, asistente: AsistenteDep, hoy: Today) -> ComparacionResponse:
    resultados = [_a_respuesta(asistente.consultar(user.id_usuario, payload.pregunta, tecnica, hoy, payload.top_k, True))
                  for tecnica in Tecnica]
    return ComparacionResponse(pregunta=payload.pregunta, resultados=resultados)


@router.get(
    "/contexto",
    response_model=ContextoRAGResponse,
    summary="Preview the RAG context for a question (no LLM call)",
    description="Shows the documents the retriever would inject into the prompt. Free: it does not call the model.",
    responses=error_responses(401, 403, 422),
)
def contexto(pregunta: str, _: StaffUser, asistente: ContextoDep, hoy: Today, top_k: int = 8) -> ContextoRAGResponse:
    if not 5 <= len(pregunta) <= 500 or not 1 <= top_k <= 20:
        raise HTTPException(422, "pregunta must have 5-500 characters and top_k must be 1-20.")
    ctx = asistente.contexto(pregunta, hoy, top_k)
    return ContextoRAGResponse(pregunta=pregunta, umbral_preventivo_dias=ctx.umbral, contexto=ctx.texto,
                               fuentes=[FuenteRAG(**f) for f in ServicioAsistenteIA.fuentes(ctx)])
