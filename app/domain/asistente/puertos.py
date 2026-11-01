"""Puertos y modelos del bounded context Asistente IA."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thinking_tokens


class LLMError(Exception):
    """Error del proveedor del LLM traducido a un código HTTP de SITRAL."""

    def __init__(self, status_code: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


class LimiteExcedidoError(Exception):
    """El usuario superó el límite propio de consultas por minuto."""

    def __init__(self, maximo: int, retry_after: int):
        super().__init__(f"SITRAL AI limit of {maximo} requests per minute reached.")
        self.maximo = maximo
        self.retry_after = retry_after


class LLMPort(Protocol):
    model: str

    def generate(self, system: str, prompt: str, *, temperature: float | None = None) -> LLMResult: ...


class BitacoraPort(Protocol):
    def registrar(self, evento: dict[str, Any]) -> None: ...


class LimitadorPort(Protocol):
    maximo: int

    def verificar(self, usuario_id: int) -> int | None:
        """Registra la solicitud; devuelve los segundos de espera si se superó el límite."""
