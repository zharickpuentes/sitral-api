"""Configuración centralizada (variables de entorno / archivo .env).

Atiende la mejora pendiente de la Fase 1 (sección 10.12): la cadena de conexión
y la clave JWT ya no están escritas en el código fuente.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.inventario.vencimiento import UMBRAL_PREVENTIVO_DEFECTO

_CLAVE_INSEGURA = "change-me-in-.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "SITRAL API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | test | production
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "mysql+pymysql://sitral:sitral@localhost:3306/sitral?charset=utf8mb4"
    AUTO_CREATE_TABLES: bool = True

    JWT_SECRET_KEY: str = _CLAVE_INSEGURA
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    TIMEZONE: str = "America/Bogota"
    DEFAULT_ALERT_THRESHOLD_DAYS: int = UMBRAL_PREVENTIVO_DEFECTO

    ALERT_JOB_ENABLED: bool = False
    ALERT_JOB_INTERVAL_HOURS: int = 24

    CORS_ORIGINS: list[str] = ["*"]

    # --- Integración LLM (Guía 5, Sesión 10) ---
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    # Precios USD por 1M tokens (Google, plan de pago, vigentes hasta 2026-12-31)
    LLM_PRICE_INPUT_PER_1M: float = 0.75
    LLM_PRICE_OUTPUT_PER_1M: float = 3.75   # incluye tokens de razonamiento (thinking)
    AI_RATE_LIMIT_PER_MINUTE: int = 10      # límite propio por usuario para controlar costos
    AI_LOG_PATH: str = "logs/llamadas_ia.jsonl"

    # --- Datos abiertos colombianos (Guía 6, Sesiones 11-12) ---
    DATOS_ABIERTOS_BASE_URL: str = "https://www.datos.gov.co/resource"
    SOCRATA_APP_TOKEN: str = ""                 # opcional: sube el límite de solicitudes
    DATASET_CUM_ID: str = "i7cb-raxc"           # INVIMA — CUM medicamentos vigentes
    DATASET_DIVIPOLA_ID: str = "gdxc-w37w"      # DANE — DIVIPOLA municipios
    OPENDATA_TIMEOUT_SECONDS: float = 10.0
    OPENDATA_CACHE_DIR: str = "data/opendata"
    CB_FAILURE_THRESHOLD: int = 3               # fallos seguidos para abrir el circuito
    CB_RECOVERY_SECONDS: float = 20.0           # tiempo en OPEN antes de pasar a HALF_OPEN
    RETRY_ATTEMPTS: int = 3
    RETRY_BASE_SECONDS: float = 0.5
    ANALYTICS_MAX_PRINCIPIOS: int = 8

    @model_validator(mode="after")
    def _validar_produccion(self) -> "Settings":
        if not self.JWT_SECRET_KEY.strip():
            raise ValueError("JWT_SECRET_KEY está vacía en el archivo .env: asigne una clave larga y aleatoria.")
        if self.ENVIRONMENT == "production" and self.JWT_SECRET_KEY == _CLAVE_INSEGURA:
            raise ValueError("Defina JWT_SECRET_KEY en el archivo .env antes de desplegar.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
