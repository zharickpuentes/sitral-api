"""Adaptador LLM (Google Gemini) con timeout, reintentos y mapeo de errores.

Implementa el puerto `LLMPort` del dominio: en pruebas se inyecta un cliente
falso y no se gastan llamadas reales.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache

from app.domain.asistente.puertos import LLMError, LLMPort, LLMResult
from app.infrastructure.config import settings

__all__ = ["GeminiClient", "LLMClient", "LLMError", "LLMResult", "get_llm"]

logger = logging.getLogger("sitral.llm")


# Los modelos LLMResult/LLMError y el puerto LLMPort viven en el dominio;
# este módulo es solo el ADAPTADOR concreto de Google Gemini.
LLMClient = LLMPort


class GeminiClient:
    """Implementación con el SDK oficial `google-genai`."""

    _REINTENTABLES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model: str, timeout_s: float, max_retries: int):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
        self.max_retries = max_retries
        self._client = genai.Client(api_key=api_key,
                                    http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    def generate(self, system: str, prompt: str, *, temperature: float | None = None) -> LLMResult:
        import httpx
        from google.genai import errors

        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        ultimo: LLMError | None = None
        for intento in range(self.max_retries + 1):
            inicio = time.perf_counter()
            try:
                resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
                latencia = int((time.perf_counter() - inicio) * 1000)
                texto = (resp.text or "").strip()
                if not texto:
                    motivo = resp.candidates[0].finish_reason if resp.candidates else "desconocido"
                    raise LLMError(502, f"The model returned an empty answer (finish_reason={motivo}).")
                uso = resp.usage_metadata
                return LLMResult(
                    text=texto, model=self.model, latency_ms=latencia,
                    input_tokens=getattr(uso, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(uso, "candidates_token_count", 0) or 0,
                    thinking_tokens=getattr(uso, "thoughts_token_count", 0) or 0,
                )
            except httpx.TimeoutException:
                ultimo = LLMError(504, f"The AI provider did not answer within {settings.LLM_TIMEOUT_SECONDS:.0f} s.")
            except errors.APIError as exc:
                code = getattr(exc, "code", 502) or 502
                if code == 429:
                    ultimo = LLMError(429, "AI provider rate limit reached (free tier quota). Try again later.",
                                      retry_after=30)
                elif code in (401, 403):
                    raise LLMError(503, "AI provider rejected the API key. Check GEMINI_API_KEY.") from exc
                elif code == 404:
                    raise LLMError(503, f"Model '{self.model}' is not available. Check GEMINI_MODEL.") from exc
                elif code >= 500:
                    ultimo = LLMError(503, "AI provider is temporarily unavailable.")
                else:
                    raise LLMError(502, f"AI provider error {code}: {getattr(exc, 'message', exc)}") from exc
            if ultimo.status_code not in self._REINTENTABLES or intento == self.max_retries:
                break
            espera = min(2 ** intento, 8)
            logger.warning("LLM intento %s falló (%s); reintento en %ss", intento + 1, ultimo.status_code, espera)
            time.sleep(espera)
        raise ultimo  # type: ignore[misc]


@lru_cache
def _cliente_gemini() -> GeminiClient:
    return GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL,
                        settings.LLM_TIMEOUT_SECONDS, settings.LLM_MAX_RETRIES)


def get_llm() -> LLMPort:
    """Dependencia FastAPI. Lanza 503 si la IA no está configurada."""
    if settings.LLM_PROVIDER.lower() != "gemini":
        raise LLMError(503, f"LLM provider '{settings.LLM_PROVIDER}' is not supported.")
    if not settings.GEMINI_API_KEY:
        raise LLMError(503, "AI service is not configured: set GEMINI_API_KEY in .env.")
    return _cliente_gemini()
