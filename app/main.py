"""Compatibilidad: permite seguir ejecutando ``uvicorn app.main:app --reload``.

La aplicación real vive en la capa API de la arquitectura hexagonal (app/api/main.py).
"""
from app.api.main import app

__all__ = ["app"]
