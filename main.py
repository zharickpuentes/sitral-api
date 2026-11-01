"""Punto de arranque rápido de SITRAL API.

    python main.py          → inicia el servidor en http://127.0.0.1:8000
    Swagger UI              → http://127.0.0.1:8000/docs
    Dashboard analítico     → http://127.0.0.1:8000/dashboard

Equivale a:  uvicorn app.main:app --reload
La aplicación se define en app/api/main.py (capa API de la arquitectura hexagonal).
"""
import uvicorn

from app.api.main import app  # noqa: F401  (se importa para fallar rápido si hay errores de configuración)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
