# ADR 0003 — Resilient integration of Colombian open-data APIs

* **Status:** Accepted
* **Date:** 2026-10-30
* **Related:** ADR 0001, ADR 0004

## Context

Guide 6 requires integrating at least two Colombian public APIs. We chose two datasets published on
**datos.gov.co** (Socrata SODA API, `https://www.datos.gov.co/resource/<id>.json`):

| Source | Dataset (configurable) | Use in SITRAL |
|---|---|---|
| INVIMA — *Código Único de Medicamentos* (CUM) | `DATASET_CUM_ID` (default `i7cb-raxc`) | verify sanitary registrations; measure market supply per active ingredient |
| DANE — *DIVIPOLA* municipality codes | `DATASET_DIVIPOLA_ID` (default `gdxc-w37w`) | locate suppliers by DANE code; regional analytics |

Public APIs are outside our control: they throttle (HTTP 429), time out, return 5xx during maintenance, and rename
columns between dataset versions. A drugstore must keep selling and receiving alerts when datos.gov.co is down.

## Decision

Every external call goes through the same pipeline, implemented in `FuenteResiliente`:

```
router → ServicioDatosAbiertos → Adapter ──▶ CircuitBreaker ──▶ PoliticaReintento ──▶ ClienteSocrata ──▶ datos.gov.co
                                     │                 (OPEN: reject fast)
                                     └──── on failure ─▶ CacheJson (last good copy, origen="cache") ─▶ else HTTP 503
```

1. **Circuit breaker with three states** (`infrastructure/resiliencia/circuit_breaker.py`, own implementation):
   * **CLOSED** — calls pass; consecutive failures are counted.
   * **OPEN** — after `CB_FAILURE_THRESHOLD` (3) consecutive failures, calls are rejected immediately for
     `CB_RECOVERY_SECONDS` (20 s by default).
   * **HALF_OPEN** — after the recovery time, exactly one trial call is allowed; success → CLOSED, failure → OPEN.
   * Only *retryable* failures count (timeouts, network errors, 429, 5xx). A 4xx caused by a bad query does not open
     the circuit.
   * The clock is injectable, so the three states are unit-tested deterministically.
2. **Retry with exponential backoff and jitter** (`PoliticaReintento`): `RETRY_ATTEMPTS` = 3 total attempts, waits of
   `base · 2^(n-1)` + random jitter (0.5 s, 1 s), capped at 8 s. The retry policy runs *inside* the breaker, so one
   logical call = one breaker outcome.
3. **Graceful degradation**: each successful response is stored as JSON under `OPENDATA_CACHE_DIR`; when the call
   fails or the circuit is OPEN the cached copy is returned with `origen = "cache"` and a warning. Without a cached
   copy the API returns **503** with `Retry-After`.
4. **Anti-corruption layer**: field names are normalized from a list of candidates; `scripts/explorar_datos_abiertos.py`
   prints the real column names and the coverage of each canonical field.
5. **Observability & demo**: `GET /api/v1/datos-abiertos/circuitos` exposes state, counters and transitions;
   administrators can simulate an outage (`POST …/simular-falla`) and reset the breaker. The dashboard shows it live.
6. Breakers are **process-wide singletons** (`app/api/contenedor.py`) so their state survives across requests.

## Consequences

* Outages of datos.gov.co never block inventory or alert endpoints; analytics degrade to cached data.
* Breaker state is per process: with several Uvicorn workers each one keeps its own breaker. Acceptable for the
  expected load (≤ 4 users); a shared store (Redis) would be needed for horizontal scaling.
* Cached data may be stale; responses always state their `origen` and timestamp.

## Alternatives considered

* **`pybreaker` / `tenacity` libraries** — viable, but implementing ~150 lines ourselves makes the three states
  explicit for the course and avoids two dependencies. Can be swapped later behind the same adapter.
* **No cache, fail fast** — rejected: a demo or a drugstore without Internet would lose all analytics.
