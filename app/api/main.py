"""Punto de entrada de la API REST de SITRAL.

Este módulo pertenece a la capa API (adaptador de entrada HTTP) de la
arquitectura hexagonal. Crea la aplicación FastAPI, la configura (documentación
OpenAPI, CORS, manejo de errores), registra todos los routers bajo /api/v1,
sirve el dashboard analítico y programa la tarea automática que genera las
alertas de vencimiento (RQF008).

Capas (Guía 6):
    app/domain          → reglas de negocio puras y puertos (Protocol), sin frameworks
    app/application     → casos de uso; reciben los puertos por constructor
    app/infrastructure  → adaptadores: SQLAlchemy, Gemini, datos.gov.co, DuckDB, resiliencia
    app/api             → FastAPI: routers, esquemas y raíz de composición (deps.py)

Ejecutar:  uvicorn app.main:app --reload     (app/main.py reexporta este objeto)
Swagger UI: http://127.0.0.1:8000/docs   ·   ReDoc: /redoc   ·   OpenAPI JSON: /openapi.json
"""

# ---------------------------------------------------------------------------
# Importaciones
# ---------------------------------------------------------------------------
# Librería estándar: tareas asíncronas, utilidades de contexto y bitácora (logs).
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

# FastAPI y Starlette (el framework web sobre el que está construido FastAPI).
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

# Módulos propios del proyecto.
from app.infrastructure.config import settings                       # variables del archivo .env
from app.infrastructure.persistence.database import Base, SessionLocal, engine   # conexión a MySQL/SQLite con SQLAlchemy
from app.api.deps import get_today                        # fecha actual en zona America/Bogota
from app.api.errors import register_exception_handlers    # formato uniforme de errores HTTP
from app.api.routers import (                              # endpoints por módulo (adaptadores de entrada)
    ai, alertas, analitica, auth, datos_abiertos, lotes, medicamentos, proveedores,
)
from app.application.alertas.servicio import ServicioAlertas   # caso de uso (regla de 10 días)
from app.infrastructure.persistence.bootstrap import migrar_columnas, sembrar_datos_base  # esquema y datos base
from app.infrastructure.persistence.repositorios import (    # adaptadores de salida SQL
    SqlAlertaRepositorio, SqlConfiguracionAlertaRepositorio, SqlLoteRepositorio, SqlUnidadDeTrabajo,
)
# Importar los modelos registra las 10 tablas en Base.metadata; sin esta línea
# create_all() no sabría qué tablas crear. El alias _models indica que no se usa directamente.
from app.infrastructure.persistence import models as _models  # noqa: F401

# ---------------------------------------------------------------------------
# Bitácora (logging)
# ---------------------------------------------------------------------------
# Muestra en consola la fecha, el nivel (INFO, ERROR...) y el mensaje de cada evento.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sitral")

# ---------------------------------------------------------------------------
# Documentación OpenAPI (Swagger UI)
# ---------------------------------------------------------------------------
# La rúbrica exige la documentación en inglés, por eso este texto está en inglés.
# Se muestra en la parte superior de http://127.0.0.1:8000/docs (admite Markdown).
DESCRIPTION = """
**SITRAL — Batch Traceability and Control System for Drugstores.**

REST API that supports the SITRAL cross-platform mobile app (Android / iOS). It lets independent drugstores
register medicine batches by scanning **barcodes or QR codes**, link them to purchase and sales invoices,
and receive **automatic expiry alerts** so that no expired or near-expiry product stays unnoticed on the shelf.

### Expiry rule (RQF008)
* **Critical window — 10 days (strict, not editable):** every batch with 10 days or less to expiry raises a `CRITICA` alert.
* **Early-warning window — configurable:** baseline of 30 days (pilot drugstore interview), adjustable by the Administrator between 10 and 180 days.
* Expired batches raise a `VENCIDO` alert and are flagged as not sellable.

### Security
JWT bearer authentication (HS256) and Argon2id password hashing. Roles: `ADMINISTRADOR`, `FARMACEUTA`.
Use **POST /api/v1/auth/login** or the **Authorize** button to obtain a token.

### AI assistant
`/api/v1/ai/consultas` answers inventory questions with Google Gemini using retrieval-augmented generation over the
batches table. Errors from the provider are mapped to `429` (rate limit), `503` (not configured / unavailable) and
`504` (timeout).

### Colombian open data (Guide 6)
`/api/v1/datos-abiertos/*` integrates two public APIs from **datos.gov.co** (Socrata SODA): INVIMA's *Código Único de
Medicamentos* (CUM) and DANE's *DIVIPOLA* municipality codes. Every call is protected by a **circuit breaker**
(CLOSED → OPEN → HALF_OPEN) and **retry with exponential backoff**, with a JSON cache as fallback.

### Analytics (DuckDB)
`/api/v1/analitica/*` loads the JSON returned by the external APIs and the inventory into **DuckDB** and runs analytical
SQL with descriptive statistics (mean, median, standard deviation, percentiles). Charts: **GET /dashboard**.

### Architecture
Hexagonal (ports & adapters) with DDD bounded contexts — *Inventory*, *Alerts*, *AI assistant*, *Open data*.
See `docs/adr/`.

### Error format
Every error returns the same JSON body (`status_code`, `error`, `message`, `path`, `timestamp`, `details`).
"""

# Grupos (tags) en los que Swagger UI organiza los endpoints. Cada router usa
# uno de estos nombres; la descripción indica el requisito funcional de la Fase 1.
TAGS = [
    {"name": "Authentication & Users", "description": "Login with JWT and user management (RQF001, RQF002)."},
    {"name": "Medicines (catalog)", "description": "Medicine catalog CRUD (RQF004)."},
    {"name": "Suppliers", "description": "Supplier CRUD (RQF003)."},
    {"name": "Batches & expiry validation",
     "description": "Barcode/QR scanning, batch registration, FEFO inventory, 10-day validation and traceability "
                    "(RQF005, RQF009, RQF012)."},
    {"name": "Expiry alerts", "description": "Automatic expiry alerts and threshold configuration (RQF008)."},
    {"name": "AI assistant (LLM + RAG)",
     "description": "Google Gemini assistant grounded on live inventory data (basic RAG) with zero-shot, few-shot "
                    "and chain-of-thought prompting, timeout/rate-limit handling and cost metrics."},
    {"name": "Colombian open data (datos.gov.co)",
     "description": "INVIMA CUM and DANE DIVIPOLA via the Socrata SODA API, protected by circuit breaker + retry with "
                    "exponential backoff + JSON cache. Includes outage simulation to demo the circuit states."},
    {"name": "Analytics (DuckDB)",
     "description": "Analytical SQL over the open-data JSON and the inventory with descriptive statistics."},
    {"name": "Health", "description": "Service status."},
]


# ---------------------------------------------------------------------------
# Tarea programada: alertas de vencimiento automáticas
# ---------------------------------------------------------------------------
async def _tarea_alertas_diaria() -> None:
    """Representa al actor no humano «Sistema» de la Fase 1.

    Cada ALERT_JOB_INTERVAL_HOURS horas (24 por defecto) revisa todos los lotes,
    actualiza su estado (VIGENTE, PROXIMO_VENCER, VENCIDO...) y crea las alertas
    PREVENTIVA, CRITICA (≤ 10 días) o VENCIDO sin intervención humana.
    """
    def _ejecutar() -> None:
        # Abre una sesión de base de datos propia, porque la tarea corre fuera
        # de cualquier petición HTTP, y la cierra al terminar (bloque with).
        with SessionLocal() as db:
            # Raíz de composición local: el caso de uso recibe sus puertos por constructor.
            servicio = ServicioAlertas(SqlLoteRepositorio(db), SqlAlertaRepositorio(db),
                                       SqlConfiguracionAlertaRepositorio(db), SqlUnidadDeTrabajo(db))
            resumen = servicio.generar(get_today())
            logger.info("Alertas generadas automáticamente: %s", resumen.alertas_nuevas)

    while True:
        try:
            # SQLAlchemy trabaja de forma síncrona: se ejecuta en un hilo aparte
            # para no bloquear el servidor mientras atiende otras peticiones.
            await run_in_threadpool(_ejecutar)
        except Exception:  # noqa: BLE001 — la tarea no debe detenerse por un fallo puntual
            logger.exception("Fallo en la tarea programada de alertas")
        # Espera hasta la siguiente ejecución (horas → segundos).
        await asyncio.sleep(settings.ALERT_JOB_INTERVAL_HOURS * 3600)


# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación (arranque y apagado)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    # --- Al ARRANCAR el servidor ---
    if settings.AUTO_CREATE_TABLES:
        # Crea las tablas que todavía no existan (no modifica las que ya existen).
        Base.metadata.create_all(bind=engine)
        # Agrega columnas nuevas a tablas existentes (p. ej. proveedor.cod_municipio de la Guía 6).
        migrar_columnas(engine)
        # Inserta los roles ADMINISTRADOR y FARMACEUTA y la configuración de alertas (30 días) si faltan.
        with SessionLocal() as db:
            sembrar_datos_base(db)
    # Inicia la tarea diaria de alertas solo si está activada en el .env (ALERT_JOB_ENABLED=true).
    tarea = asyncio.create_task(_tarea_alertas_diaria()) if settings.ALERT_JOB_ENABLED else None

    yield  # <- aquí la API queda funcionando y atendiendo peticiones

    # --- Al APAGAR el servidor (Ctrl + C) ---
    # Cancela la tarea programada de forma ordenada para no dejar procesos colgados.
    if tarea:
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea


# ---------------------------------------------------------------------------
# Creación de la aplicación FastAPI
# ---------------------------------------------------------------------------
# Los metadatos (título, versión, descripción, contacto...) aparecen en Swagger UI
# y en el documento OpenAPI generado automáticamente en /openapi.json.
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    summary="Batch traceability and expiry control API for independent drugstores.",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    contact={"name": "SITRAL team — Universidad Manuela Beltrán", "url": "https://umb.edu.co"},
    license_info={"name": "Academic use"},
    lifespan=lifespan,
)

# CORS: permite que la app móvil o un frontend web en otro dominio llamen a la API.
# Los orígenes permitidos se configuran en el .env (CORS_ORIGINS); en producción
# conviene reemplazar "*" por los dominios reales.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Manejadores globales de errores: todas las respuestas de error (400, 401, 403,
# 404, 409, 422, 429, 503, 504, 500) usan el mismo formato JSON ErrorResponse.
register_exception_handlers(app)

# Registro de los routers. Cada uno agrupa los endpoints de un módulo y queda
# publicado bajo el prefijo /api/v1 (por ejemplo, /api/v1/lotes).
for r in (auth.router, medicamentos.router, proveedores.router, lotes.router, alertas.router, ai.router,
          datos_abiertos.router, analitica.router):
    app.include_router(r, prefix=settings.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Dashboard analítico (UI de la Guía 6)
# ---------------------------------------------------------------------------
# Página HTML estática que inicia sesión con JWT, consume /analitica y /datos-abiertos
# y dibuja los gráficos con Chart.js. No aparece en Swagger (include_in_schema=False).
_DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(_DASHBOARD, media_type="text/html")


# ---------------------------------------------------------------------------
# Endpoint de salud (health check)
# ---------------------------------------------------------------------------
# No requiere token. Sirve para comprobar rápidamente que el servidor está
# encendido (lo usan los pipelines de CI/CD y los monitores de disponibilidad).
@app.get("/health", tags=["Health"], summary="Health check",
         description="Returns 200 when the API process is running. Used by CI/CD and uptime monitors.")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}
