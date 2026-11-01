# SITRAL API — Sistema de Trazabilidad y Control por Lotes para Droguerías

Backend REST en **Python + FastAPI + SQLAlchemy 2.0 + MySQL 8** que soporta la aplicación móvil multiplataforma
(Android / iOS) de SITRAL. Permite registrar lotes de medicamentos escaneando **códigos de barras o QR**, generar
**alertas automáticas de vencimiento** con una ventana crítica estricta de **10 días**, consultar la trazabilidad de
cada lote y hacer preguntas sobre el inventario a un **asistente de IA (Google Gemini + RAG)**.

Desde la **Guía 6** el backend usa **arquitectura hexagonal** con *bounded contexts* (DDD), integra dos **APIs públicas
colombianas** de datos.gov.co (INVIMA CUM y DANE DIVIPOLA) protegidas con **circuit breaker** y **reintentos con
backoff exponencial**, y ofrece **analítica SQL con DuckDB** visualizada en un **dashboard web**.

> Guía de Laboratorio 6 (Unidad Didáctica 6, Sesiones 11 y 12) — Taller de Programación, Ingeniería de Software,
> Universidad Manuela Beltrán. Continuación de la Guía 5 y de la Propuesta de Proyecto — Fase 1.

| | |
|---|---|
| **Integrantes** | Cristian Camilo Girata Ravelo · Gabriel Leonardo Nieves Bello · Zharick Yojana Puentes Rodríguez |
| **Tutor** | Juan José Osorio Tabares |
| **Video (inglés)** | https://youtu.be/KuO54yw3fBc_ |
| **Documentación interactiva** | `http://127.0.0.1:8000/docs` (Swagger UI) con la API en ejecución |
| **Dashboard analítico** | `http://127.0.0.1:8000/dashboard` |
| **Decisiones de arquitectura** | [`docs/adr/`](docs/adr/README.md) (ADR en inglés) |

---

## Contenido

1. [Requisitos](#1-requisitos)
2. [Instalación y ejecución](#2-instalación-y-ejecución)
3. [Primer uso en Swagger UI](#3-primer-uso-en-swagger-ui)
4. [Arquitectura hexagonal y estructura](#4-arquitectura-hexagonal-y-estructura)
5. [Regla de vencimiento a 10 días](#5-regla-de-vencimiento-a-10-días-rqf008)
6. [Endpoints](#6-endpoints-prefijo-apiv1)
7. [Seguridad y manejo de errores](#7-seguridad-y-manejo-de-errores)
8. [Asistente IA: Gemini + RAG](#8-asistente-ia-gemini--rag)
   - 8.1 [Datos abiertos colombianos y resiliencia](#81-datos-abiertos-colombianos-y-resiliencia-guía-6)
   - 8.2 [Analítica con DuckDB y dashboard](#82-analítica-con-duckdb-y-dashboard-guía-6)
9. [Pruebas y CI/CD](#9-pruebas-y-cicd)
10. [Solución de problemas](#10-solución-de-problemas)
11. [Cambios respecto a la Fase 1](#11-cambios-respecto-a-la-fase-1)
12. [Uso de inteligencia artificial](#12-uso-de-inteligencia-artificial)
13. [Próximas iteraciones](#13-próximas-iteraciones)

---

## 1. Requisitos

- **Python 3.11 o 3.12** (`python --version`)
- **Git**
- *(Opcional)* **MySQL 8** o Docker. Sin MySQL se puede usar SQLite, que no requiere instalación.
- *(Opcional)* **API key de Google Gemini**, gratuita en <https://aistudio.google.com/apikey>. Solo la necesita el asistente IA.

## 2. Instalación y ejecución

### 2.1 Clonar e instalar (solo la primera vez)

**Windows (PowerShell):**
```powershell
git clone <URL_DEL_REPOSITORIO>
cd sitral-api
python -m venv .venv
.venv\Scripts\activate          # si PowerShell lo bloquea: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
copy .env.example .env
```

**Linux / macOS:**
```bash
git clone <URL_DEL_REPOSITORIO> && cd sitral-api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2.2 Configurar el archivo `.env`

El archivo `.env` guarda las credenciales y **nunca se sube al repositorio**, porque está en `.gitignore`. Variables principales:

| Variable | Ejemplo | Descripción |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./sitral.db` | Base de datos. Para MySQL: `mysql+pymysql://usuario:clave@localhost:3306/sitral_v2?charset=utf8mb4` |
| `JWT_SECRET_KEY` | *(texto aleatorio de más de 40 caracteres)* | Clave para firmar los tokens. **No puede estar vacía.** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Vigencia del token JWT |
| `DEFAULT_ALERT_THRESHOLD_DAYS` | `30` | Umbral preventivo inicial (el crítico de 10 días es fijo) |
| `ALERT_JOB_ENABLED` | `true` | Ejecuta la generación automática de alertas cada `ALERT_JOB_INTERVAL_HOURS` |
| `GEMINI_API_KEY` | `AIza...` | Clave de Google AI Studio (solo para `/api/v1/ai`) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Modelo de Gemini |
| `LLM_MAX_RETRIES` | `2` | Reintentos ante 429/5xx/timeout (use `0` en experimentos para no gastar cuota) |
| `AI_RATE_LIMIT_PER_MINUTE` | `10` | Límite propio de consultas de IA por usuario |
| `SOCRATA_APP_TOKEN` | *(vacío)* | Opcional. App Token gratuito de datos.gov.co; sube el límite de solicitudes |
| `DATASET_CUM_ID` / `DATASET_DIVIPOLA_ID` | `i7cb-raxc` / `gdxc-w37w` | Identificadores de los datasets en datos.gov.co |
| `CB_FAILURE_THRESHOLD` / `CB_RECOVERY_SECONDS` | `3` / `20` | Fallos para abrir el circuito y segundos hasta HALF_OPEN |
| `RETRY_ATTEMPTS` / `RETRY_BASE_SECONDS` | `3` / `0.5` | Intentos totales y espera base del backoff exponencial |

Para generar una clave JWT segura: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

Si va a usar MySQL, cree primero una base **nueva**. La API crea las tablas sola, pero no modifica tablas que ya existen:
```sql
CREATE DATABASE sitral_v2 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
También puede levantar MySQL con Docker: `docker compose up -d`.

### 2.3 Crear el administrador y cargar datos de demostración

```bash
python -m scripts.crear_admin --usuario admin --nombre Ana --apellido Rojas   # pide la contraseña (mín. 10 caracteres)
python -m scripts.sembrar_datos_demo                                           # opcional: datos ficticios
```

`sembrar_datos_demo` carga **103 medicamentos, 6 proveedores y unos 170 lotes ficticios** con vencimientos variados
(vencidos, críticos, preventivos y vigentes) y genera sus alertas. Los proveedores quedan ubicados con su **código DANE**
(Bogotá 11001, Chía 25175, Mosquera 25473, Itagüí 05360, Cali 76001) para la analítica regional.

Si ya tenía los datos de la Guía 5, no necesita recargarlos: la API agrega sola la columna `proveedor.cod_municipio`
al arrancar, y este comando asigna los códigos DANE a los proveedores existentes:
```bash
python -m scripts.sembrar_datos_demo --solo-municipios
```

### 2.3.1 Verificar los datasets de datos.gov.co (recomendado la primera vez)
```bash
python -m scripts.explorar_datos_abiertos
```
Muestra los nombres de columna reales de cada dataset y qué porcentaje de los campos de SITRAL se pudo llenar.
Si un campo importante aparece en 0 %, agregue el nombre real en `app/infrastructure/datos_abiertos/normalizacion.py`.

### 2.4 Iniciar la API

Cualquiera de estas tres formas es equivalente:
```bash
python main.py
uvicorn main:app --reload
uvicorn app.main:app --reload
```

| URL | Contenido |
|---|---|
| <http://127.0.0.1:8000/docs> | Swagger UI (documentación interactiva en inglés) |
| <http://127.0.0.1:8000/redoc> | ReDoc |
| <http://127.0.0.1:8000/openapi.json> | Especificación OpenAPI 3.1 |
| <http://127.0.0.1:8000/health> | Estado del servicio |
| <http://127.0.0.1:8000/dashboard> | Dashboard analítico (gráficos DuckDB y estados del circuit breaker) |

Para detener la API: `Ctrl + C`. Las siguientes veces solo hay que activar el entorno (`.venv\Scripts\activate`) e iniciarla.

## 3. Primer uso en Swagger UI

1. Abra <http://127.0.0.1:8000/docs> y haga clic en **Authorize** 🔓.
2. Escriba el **username** y el **password** del administrador. Deje vacíos los demás campos. Luego **Authorize** → **Close**.
3. Pruebe el flujo principal con **Try it out → Execute**:
   - `POST /api/v1/lotes` con una fecha a menos de 10 días → **201** y `"nivel_alerta": "CRITICA"`:
     ```json
     { "id_medicamento": 1, "id_proveedor": 1, "numero_lote": "LT-DEMO-001",
       "cantidad_inicial": 30, "fecha_vencimiento": "2026-10-22" }
     ```
   - `GET /api/v1/alertas` → aparece la alerta **CRITICA**.
   - `GET /api/v1/lotes/{id}/validacion` → días restantes, nivel y acción recomendada.
   - `GET /api/v1/ai/contexto?pregunta=¿Qué lotes vencen pronto?` → contexto del RAG, sin gastar cuota de Gemini.

## 4. Arquitectura hexagonal y estructura

```
                    ┌───────────────────────── app/api (adaptador de entrada) ─────────────────────────┐
  App móvil /       │ routers FastAPI · esquemas Pydantic · errores · dashboard                         │
  Swagger / ──HTTP──▶ deps.py = raíz de composición (crea los casos de uso e inyecta los puertos)      │
  dashboard         └──────────────────────────────────────┬────────────────────────────────────────────┘
                                                           ▼
                    ┌──────────────── app/application (casos de uso) ────────────────┐
                    │ ServicioAlertas · ServicioAsistenteIA · ServicioDatosAbiertos  │
                    └──────────────────────────────┬─────────────────────────────────┘
                                                   ▼ usa solo puertos (typing.Protocol)
                    ┌──────────────── app/domain (sin frameworks) ───────────────────┐
                    │ inventario · alertas · asistente · datos_abiertos · shared     │
                    │ reglas puras (10 días, GS1) + puertos                          │
                    └──────────────────────────────▲─────────────────────────────────┘
                                                   │ implementan los puertos
                    ┌──────────────── app/infrastructure (adaptadores de salida) ────┐
                    │ persistence (SQLAlchemy/MySQL) · llm (Gemini) · observabilidad │
                    │ datos_abiertos (Socrata) · resiliencia (circuit breaker,       │
                    │ reintentos) · analitica (DuckDB) · config · security           │
                    └────────────────────────────────────────────────────────────────┘
```

- **Las dependencias apuntan hacia adentro:** el dominio y la aplicación no importan FastAPI, SQLAlchemy, httpx, DuckDB ni Gemini.
- **Inyección por constructor:** por ejemplo, `ServicioAlertas(lotes, alertas, configuracion, uow)`. En las pruebas
  esos puertos se reemplazan por `Mock(spec=Puerto)`.
- **Bounded contexts (DDD):** Inventario, Alertas, Asistente IA y Datos abiertos (ver [ADR 0002](docs/adr/0002-bounded-contexts.md)).

```
sitral-api/
├── main.py                       # Atajo: python main.py
├── app/
│   ├── main.py                   # Compatibilidad: uvicorn app.main:app
│   ├── domain/                   # Capa de dominio (sin dependencias externas)
│   │   ├── shared/enums.py
│   │   ├── inventario/           # LoteVista, vencimiento (10 días), escaneo GS1/QR, puerto LoteRepositorio
│   │   ├── alertas/              # AlertaRegistro, ResumenGeneracion, puertos de repositorio
│   │   ├── asistente/            # LLMPort, BitacoraPort, LimitadorPort, BM25
│   │   └── datos_abiertos/       # ResultadoFuente, FuenteNoDisponibleError, puertos de fuentes y analítica
│   ├── application/              # Casos de uso
│   │   ├── alertas/servicio.py
│   │   ├── asistente/            # servicio, contexto RAG, plantillas de prompt
│   │   └── datos_abiertos/servicio.py
│   ├── infrastructure/           # Adaptadores
│   │   ├── persistence/          # database, models (10 tablas), repositorios SQL, bootstrap/migración
│   │   ├── llm/gemini.py
│   │   ├── observabilidad/       # límite por minuto y bitácora JSONL
│   │   ├── datos_abiertos/       # cliente Socrata, adaptadores INVIMA/DANE, normalización, caché JSON
│   │   ├── resiliencia/          # circuit_breaker.py, reintentos.py
│   │   ├── analitica/duckdb_motor.py
│   │   ├── config.py · security.py
│   └── api/                      # FastAPI
│       ├── main.py · deps.py · contenedor.py · errors.py · mappers.py
│       ├── routers/              # auth, medicamentos, proveedores, lotes, alertas, ai, datos_abiertos, analitica
│       ├── schemas/
│       └── static/dashboard.html
├── docs/adr/                     # Architecture Decision Records (inglés)
├── tests/                        # Unitarias (dominio, resiliencia, Mocks) e integración (TestClient)
├── scripts/                      # crear_admin, sembrar_datos_demo, experimento_prompting, explorar_datos_abiertos
├── resultados/                   # Evidencia del experimento con el LLM
├── .github/workflows/ci.yml
├── requirements.txt · .env.example · docker-compose.yml
```

## 5. Regla de vencimiento a 10 días (RQF008)

La Fase 1 fijó una **línea base de 30 días**, a partir de la entrevista con la droguería piloto, y el planteamiento
del proyecto exige alertar **como máximo 10 días antes** del vencimiento. SITRAL cumple ambas con dos umbrales:

| Nivel | Condición | ¿Editable? | Efecto |
|---|---|---|---|
| `VENCIDO` | días < 0 | — | No apto para venta; cuarentena y baja |
| `CRITICA` | 0 ≤ días ≤ **10** | **No** (constante del código) | Alerta inmediata; priorizar la venta (FEFO) o devolver al proveedor |
| `PREVENTIVA` | 10 < días ≤ umbral | Sí, Administrador (10–180; base 30) | Alerta temprana |
| — | días > umbral | — | Lote `VIGENTE` |

- Si el Administrador intenta fijar un umbral **menor a 10**, la API responde **422**: la ventana crítica siempre se cumple.
- Un lote **ya vencido** no se puede registrar (**400**). Si vence en 10 días o menos, se acepta y se crea de inmediato una alerta **CRÍTICA**.
- La generación de alertas es **idempotente**: no duplica alertas y **escala** una alerta pendiente cuando el lote sube de nivel (PREVENTIVA → CRÍTICA → VENCIDO).
- Los días se calculan con la fecha de **America/Bogota**, no con la del servidor.

## 6. Endpoints (prefijo `/api/v1`)

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| POST | `/auth/login` | Público | Login (OAuth2 *password*) → token JWT |
| GET | `/auth/me` | Autenticado | Perfil del usuario del token |
| POST · GET | `/usuarios` | Admin | Crear / listar usuarios |
| GET · POST | `/medicamentos` | Admin, Farm. | Listar / crear medicamento |
| GET · PUT · DELETE | `/medicamentos/{id}` | GET ambos · PUT/DELETE Admin | Consultar, actualizar (parcial), desactivar (borrado lógico) |
| GET · POST · GET · PUT · DELETE | `/proveedores[/{id}]` | PUT/DELETE solo Admin | CRUD de proveedores |
| POST | `/lotes/escanear` | Admin, Farm. | Interpreta EAN/GTIN, GS1 (DataMatrix/QR) o QR SITRAL y prevalida el vencimiento |
| POST | `/lotes` | Admin, Farm. | Registra el lote, el movimiento de ENTRADA y la alerta si aplica |
| GET | `/lotes` | Admin, Farm. | Inventario por lote en orden **FEFO** con filtros (`vence_en_dias`, `estado`…) |
| GET | `/lotes/{id}` | Admin, Farm. | Consultar lote |
| GET | `/lotes/{id}/validacion` | Admin, Farm. | **Validación a 10 días** |
| GET | `/lotes/{id}/trazabilidad` | Admin, Farm. | Historial completo del lote (RQF012) |
| PATCH | `/lotes/{id}` | Admin | Corrección auditada (movimiento AJUSTE) |
| DELETE | `/lotes/{id}` | Admin | Baja lógica (movimiento BAJA → KPI de pérdidas) |
| POST | `/alertas/generar` | Admin, Farm. | Evaluación idempotente de vencimientos |
| GET | `/alertas` | Admin, Farm. | Alertas ordenadas por urgencia |
| PATCH | `/alertas/{id}/atender` | Admin, Farm. | Marcar alerta como ATENDIDA |
| GET · PUT | `/alertas/configuracion` | GET ambos · PUT Admin | Umbral preventivo (10–180 días) |
| POST | `/ai/consultas` | Admin, Farm. | Pregunta al asistente IA (`zero_shot`, `few_shot` o `cot`) |
| POST | `/ai/comparar` | Admin, Farm. | Misma pregunta con las 3 técnicas |
| GET | `/ai/contexto` | Admin, Farm. | Contexto que recupera el RAG (no llama al LLM) |
| GET | `/datos-abiertos/medicamentos?q=` | Admin, Farm. | Búsqueda en el CUM del INVIMA (datos.gov.co) |
| GET | `/datos-abiertos/medicamentos/registro?registro=` | Admin, Farm. | Verifica un registro sanitario INVIMA |
| GET | `/datos-abiertos/municipios?cod_departamento=` | Admin, Farm. | Municipios DIVIPOLA del DANE |
| GET | `/datos-abiertos/circuitos` | Admin, Farm. | Estado de los circuit breakers |
| POST | `/datos-abiertos/circuitos/{fuente}/simular-falla` | Admin | Simula la caída de una API (demo) |
| POST | `/datos-abiertos/circuitos/{fuente}/reiniciar` | Admin | Cierra el circuito manualmente |
| GET | `/analitica/inventario` | Admin, Farm. | Consulta DuckDB 1: estadísticas por nivel de vencimiento |
| GET | `/analitica/oferta-mercado` | Admin, Farm. | Consulta DuckDB 2: oferta INVIMA por principio activo |
| GET | `/analitica/cobertura-regional` | Admin, Farm. | Consulta DuckDB 3: inventario × DIVIPOLA |
| GET | `/health` *(sin prefijo)* | Público | Estado del servicio |
| GET | `/dashboard` *(sin prefijo)* | Login en la página | Dashboard analítico |

En total son **39 operaciones** bajo `/api/v1`. Medicamentos y proveedores tienen **CRUD completo** de 5 endpoints cada uno.

## 7. Seguridad y manejo de errores

- **Contraseñas:** se guardan solo como hash **Argon2id** (`argon2-cffi`, perfil RFC 9106).
- **Autenticación:** token **JWT HS256** con el usuario y el rol, vigente 60 minutos. Se envía en `Authorization: Bearer <token>`.
- **Roles:** `ADMINISTRADOR` (control total) y `FARMACEUTA` (operación diaria), según la matriz de permisos de la Fase 1.
- **Credenciales:** la clave JWT, la cadena de conexión y la API key se leen del archivo `.env`, que no se versiona.

Todos los errores devuelven el mismo cuerpo JSON:
```json
{ "status_code": 404, "error": "Not Found", "message": "Batch 9999 was not found.",
  "path": "/api/v1/lotes/9999", "timestamp": "2026-10-14T23:00:00Z", "details": null }
```

| Código | Ejemplo en SITRAL |
|---|---|
| 200 / 201 | Consulta de inventario / registro de un lote |
| 400 | Registrar un lote ya vencido o escanear un código ilegible |
| 401 | Petición sin token o con token expirado |
| 403 | Un Farmaceuta intenta modificar el catálogo o el umbral |
| 404 | Lote o medicamento inexistente |
| 409 | Lote o código de barras duplicado |
| 422 | Datos inválidos (precio negativo, umbral < 10 días…) |
| 429 · 503 · 504 | Asistente IA: cuota agotada, servicio no configurado o *timeout* |
| 503 | Datos abiertos: la API externa falló o el circuito está abierto y no hay copia en caché |

## 8. Asistente IA: Gemini + RAG

### Funcionamiento
1. **Retrieve:** cada lote con existencias se convierte en un documento de texto. Un recuperador **BM25**, con un refuerzo por urgencia cuando la pregunta trata de vencimientos, selecciona los `top_k` más relevantes.
2. **Augment:** los documentos y un resumen del inventario se insertan como CONTEXTO, junto con un *system prompt* que contiene las reglas de negocio, la instrucción de no inventar datos y la prohibición de dar recomendaciones clínicas.
3. **Generate:** **Google Gemini 3.8 Flash** responde usando solo ese contexto.

**Técnicas de prompting:** `zero_shot` (solo instrucciones), `few_shot` (3 ejemplos resueltos que fijan el formato) y
`cot` (razonamiento paso a paso con verificación).

**Robustez:** *timeout* de 30 s, reintentos con espera exponencial, límite propio de 10 consultas por minuto por usuario
y bitácora de cada llamada en `logs/llamadas_ia.jsonl`.

### Experimento (12 llamadas reales)
```bash
uvicorn app.main:app                                          # terminal 1
python -m scripts.experimento_prompting --usuario admin       # terminal 2
# repetir solo las llamadas que fallaron (por ejemplo, por cuota 429):
python -m scripts.experimento_prompting --usuario admin --completar resultados/experimento_<fecha>.json --pausa 30
```

Resultados (`resultados/experimento_20261014_172806.*`, 9 llamadas exitosas de 12; las otras 3 recibieron 429 por la cuota diaria del plan gratuito):

| Técnica | Cobertura promedio | Latencia promedio | Costo por consulta | Uso recomendado |
|---|---|---|---|---|
| Zero-shot | 100 % | 13,0 s | USD 0,0086 | Respaldo económico |
| Few-shot | 90 % | 19,4 s | USD 0,0110 | **Por defecto en la app** (formato uniforme y accionable) |
| CoT | 80 % | 18,6 s | USD 0,0144 | Consultas analíticas del Administrador |

Ninguna técnica inventó datos. La menor cobertura en la pregunta sobre lotes a 10 días se debió a la **recuperación**
y no al modelo: el refuerzo por urgencia priorizó los lotes vencidos.

### Costos estimados
Gemini 3.8 Flash, plan de pago: USD 0,75 por millón de tokens de entrada y USD 3,75 por millón de salida, incluidos
los de razonamiento, hasta el 31-12-2026; el doble desde 2027. Para **4 usuarios × 20 consultas/día**, unos
**USD 21–35 al mes**, según la técnica. El plan gratuito de AI Studio no tiene costo dentro de su cuota, pero no
alcanza para ese volumen.

## 8.1 Datos abiertos colombianos y resiliencia (Guía 6)

| Fuente | Dataset | Uso en SITRAL |
|---|---|---|
| INVIMA — Código Único de Medicamentos (CUM) | `i7cb-raxc` | Verificar registros sanitarios y medir la oferta por principio activo |
| DANE — DIVIPOLA | `gdxc-w37w` | Ubicar a los proveedores por código DANE y hacer analítica regional |

Cada llamada sigue este camino:
```
Adaptador ─▶ Circuit breaker ─▶ Reintentos (0,5 s, 1 s + jitter) ─▶ Cliente Socrata ─▶ datos.gov.co
    └── si falla o el circuito está OPEN ─▶ última copia en caché (origen = "cache") ─▶ si no hay copia: 503
```

**Estados del circuito:** `CLOSED` (normal) → 3 fallos seguidos → `OPEN` (rechaza sin llamar a la red) → pasan 20 s →
`HALF_OPEN` (deja pasar 1 llamada de prueba) → si funciona `CLOSED`, si falla vuelve a `OPEN`. Los errores 4xx por una
consulta mal formada no se reintentan ni abren el circuito.

**Demostración (video):** en el dashboard o en Swagger, como Administrador:
1. `POST /datos-abiertos/circuitos/dane_divipola/simular-falla?activar=true`
2. Llame 3 veces a `GET /datos-abiertos/municipios` → el estado pasa a **OPEN** (las respuestas salen de la caché).
3. Espere 20 s → **HALF_OPEN**.
4. Desactive la falla (`activar=false`) y llame de nuevo → **CLOSED**.

Detalles y alternativas: [ADR 0003](docs/adr/0003-resilient-open-data-integration.md).

## 8.2 Analítica con DuckDB y dashboard (Guía 6)

Los registros JSON de las APIs y del inventario se cargan en DuckDB con `read_json_auto` y se consultan con SQL:

| Endpoint | Pregunta de negocio | Estadísticas |
|---|---|---|
| `/analitica/inventario` | ¿Cuánto inventario hay en cada nivel de vencimiento y cuánto dinero está en riesgo? | conteo, suma, media, mediana, desviación estándar, mín., máx., P25, P75 |
| `/analitica/oferta-mercado` | ¿Hay suficientes productos equivalentes registrados en el INVIMA para reemplazar un lote crítico? | presentaciones, titulares, moda de la forma farmacéutica, % vigentes; media, mediana, desviación |
| `/analitica/cobertura-regional` | ¿De qué municipios vienen los lotes en riesgo? | lotes, unidades y % en riesgo por municipio; media, mediana y desviación de municipios por departamento |

Cada respuesta incluye el SQL ejecutado. El **dashboard** (<http://127.0.0.1:8000/dashboard>) inicia sesión con JWT,
muestra los tres análisis con gráficos Chart.js y los estados de los circuitos, con botones para simular la caída,
probar la llamada y reiniciar. Ver [ADR 0004](docs/adr/0004-duckdb-analytics.md).

## 9. Pruebas y CI/CD

```bash
pytest -v
```

- Más de **58 casos**: autenticación y roles, CRUD, códigos HTTP, límites de **10 y 11 días**, escaneo GS1, alertas idempotentes, RAG, las tres técnicas de prompting y errores 429/503/504.
- **Guía 6** agrega:
  - `test_servicios_di.py`: pruebas estilo **Mockito** de los casos de uso con `unittest.mock.Mock(spec=Puerto)`; programan respuestas y verifican interacciones.
  - `test_resiliencia.py`: los tres estados del circuit breaker con un reloj falso y el backoff exponencial.
  - `test_adaptadores_datos_abiertos.py`: adaptadores con un servidor HTTP simulado (`httpx.MockTransport`), sin Internet.
  - `test_analitica_duckdb.py`: las consultas SQL reales en DuckDB.
  - `test_api_datos_abiertos.py`: endpoints y dashboard con fuentes falsas inyectadas.
  - `test_normalizacion.py`.
- Usan **SQLite en memoria** y una **fecha fija** (2026-10-14), así que no requieren MySQL y dan resultados deterministas.
- El asistente IA se prueba con un **LLM simulado**: las pruebas no gastan cuota ni dinero.
- **GitHub Actions** (`.github/workflows/ci.yml`) ejecuta la suite en cada *push* y *pull request*.

## 10. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `500` en el login con `HMAC key must not be empty` | `JWT_SECRET_KEY` vacía en `.env` | Asigne una clave y reinicie la API |
| `503` *Model … is not available* | El modelo configurado ya no está disponible | Use `GEMINI_MODEL=gemini-3.8-flash` |
| `503` *AI service is not configured* | Falta `GEMINI_API_KEY` | Agregue la clave en `.env` y reinicie |
| `429` en `/ai/consultas` | Cuota de Gemini agotada o límite propio superado | Espere el tiempo de `Retry-After`; la cuota diaria se renueva a las 2:00 a. m. (hora de Colombia) |
| *La ejecución de scripts está deshabilitada* (PowerShell) | Política de Windows | `Set-ExecutionPolicy -Scope Process Bypass` |
| `python-dotenv could not parse statement` | Línea del `.env` sin `=` ni `#` | Comente la línea con `#` |
| `503` en `/datos-abiertos/*` | datos.gov.co no responde, o el circuito está OPEN y no hay copia en caché | Revise `GET /datos-abiertos/circuitos`; espere el tiempo de recuperación o use *reiniciar* |
| Campos vacíos en los datos de datos.gov.co | El dataset cambió los nombres de sus columnas | `python -m scripts.explorar_datos_abiertos` y ajuste `normalizacion.py` o el `DATASET_*_ID` |
| `ModuleNotFoundError: duckdb` | Faltan dependencias nuevas | `pip install -r requirements.txt` |
| GitHub dice que el repositorio es muy pesado | Se intentó subir `.venv` | Use `git add .`, que respeta `.gitignore`; nunca suba `.venv` ni `.env` |

## 11. Cambios respecto a la Fase 1

- Credenciales movidas a `.env`, que era una mejora pendiente de la sección 10.12 de la propuesta.
- Nueva columna `medicamento.registro_sanitario` (registro INVIMA) para la trazabilidad que verifica la Secretaría de Salud.
- Nuevo estado de lote `BAJA` y nuevo estado de alerta `ESCALADA`.
- Restricción única (`id_medicamento`, `numero_lote`) e índice por `fecha_vencimiento`.
- Regla de vencimiento con dos umbrales: el crítico de 10 días, fijo, y el preventivo configurable con base de 30 días.
- **Guía 6:** nueva columna `proveedor.cod_municipio` (código DANE DIVIPOLA), que se agrega sola al arrancar.

## 12. Uso de inteligencia artificial

El código base, los scripts y parte de la documentación se elaboraron con apoyo del asistente **Claude (Anthropic)**.
El equipo revisó el código, lo ejecutó, corrigió la configuración, validó las pruebas, ejecutó las llamadas reales
al LLM y verificó manualmente sus respuestas. El uso de **GitHub Copilot** y la evaluación de una de sus
sugerencias se documentan en el informe de laboratorio.

## 13. Próximas iteraciones

1. **Circuit breaker compartido** (Redis) si se despliegan varios workers; ahora cada proceso tiene el suyo.
2. **Recuperador sensible a la intención:** filtrar por el rango de días que menciona la pregunta (hallazgo del experimento).
3. Facturación de entrada y salida (RQF006 y RQF007) con descuento FEFO y bloqueo de lotes vencidos.
4. Ampliar el dashboard con los KPIs de RQF010 (rotación de inventario).
5. Migración de datos desde Navasoft en CSV o Excel (RQF011).
6. Despliegue con HTTPS (proxy Nginx con certificado TLS).
