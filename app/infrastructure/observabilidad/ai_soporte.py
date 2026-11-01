"""Límite de solicitudes por usuario y bitácora de llamadas al LLM."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.config import settings

logger = logging.getLogger("sitral.ai")


class LimitadorPorMinuto:
    """Ventana deslizante de 60 s por usuario (protege la cuota y el costo)."""

    def __init__(self, maximo: int):
        self.maximo = maximo
        self._eventos: dict[int, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def verificar(self, usuario_id: int) -> int | None:
        """Registra la solicitud; devuelve segundos de espera si se superó el límite."""
        ahora = time.monotonic()
        with self._lock:
            cola = self._eventos[usuario_id]
            while cola and ahora - cola[0] >= 60:
                cola.popleft()
            if len(cola) >= self.maximo:
                return max(1, int(60 - (ahora - cola[0])) + 1)
            cola.append(ahora)
            return None


limitador = LimitadorPorMinuto(settings.AI_RATE_LIMIT_PER_MINUTE)


class BitacoraJsonl:
    """Adaptador de BitacoraPort: una línea JSON por llamada al LLM."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)

    def registrar(self, evento: dict[str, Any]) -> None:
        registrar_llamada(evento, self.ruta)


def registrar_llamada(evento: dict[str, Any], ruta: str | Path | None = None) -> None:
    """Agrega una línea JSON a la bitácora (evidencia de ≥ 10 llamadas reales)."""
    try:
        ruta = Path(ruta or settings.AI_LOG_PATH)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        evento = {"timestamp": datetime.now(timezone.utc).isoformat(), **evento}
        with ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("No se pudo escribir la bitácora de IA")
