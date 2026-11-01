"""Caché en disco (JSON) con la última respuesta exitosa de cada consulta.

Si la API falla o el circuito está abierto, el adaptador devuelve esta copia
(degradación elegante) en lugar de un error.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CacheJson:
    def __init__(self, directorio: str | Path):
        self.directorio = Path(directorio)

    def _ruta(self, fuente: str, clave: str) -> Path:
        h = hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]
        return self.directorio / fuente / f"{h}.json"

    def guardar(self, fuente: str, clave: str, registros: list[dict[str, Any]]) -> None:
        ruta = self._ruta(fuente, clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = {"clave": clave, "guardado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "registros": registros}
        ruta.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")

    def leer(self, fuente: str, clave: str) -> tuple[list[dict[str, Any]], str] | None:
        ruta = self._ruta(fuente, clave)
        if not ruta.exists():
            return None
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
            return contenido["registros"], contenido.get("guardado_en", "")
        except (OSError, ValueError, KeyError):
            return None
