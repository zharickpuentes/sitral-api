"""Capa de DOMINIO (núcleo del hexágono).

Contiene las reglas de negocio y los puertos (interfaces) de cada bounded context.
Solo depende de la librería estándar de Python: no importa FastAPI, SQLAlchemy,
httpx, DuckDB ni ningún otro framework.

Bounded contexts:
    shared/          Tipos compartidos (enumeraciones).
    inventario/      Lotes, regla de vencimiento a 10 días y lectura de códigos GS1/QR.
    alertas/         Alertas de vencimiento y su configuración.
    asistente/       Asistente de inventario con LLM + RAG.
    datos_abiertos/  Datos públicos colombianos (INVIMA CUM, DANE DIVIPOLA) y analítica.
"""
