# ADR 0001 — Hexagonal architecture with constructor dependency injection

* **Status:** Accepted
* **Date:** 2026-10-30
* **Deciders:** Cristian Camilo Girata Ravelo, Gabriel Leonardo Nieves Bello, Zharick Yojana Puentes Rodríguez
* **Supersedes:** the layered `routers / services / models` structure delivered in Guide 5

## Context

The Guide 5 version of SITRAL API organized code by technical type (`routers/`, `services/`, `models/`, `core/`).
Business rules such as the strict 10-day critical window lived in `services/alertas.py`, which received a SQLAlchemy
`Session` and queried ORM models directly. Consequences we observed:

* Unit-testing the alert rules required a database (SQLite in memory) even for pure logic.
* The AI assistant service imported the Gemini client and the JSON log writer directly, so replacing the LLM
  provider or mocking it required patching module globals.
* Guide 6 adds two external APIs (datos.gov.co) and an analytics engine (DuckDB). Wiring them the same way would
  couple the use cases to HTTP and to a specific database engine.

## Decision

Adopt **hexagonal architecture (ports & adapters)** with four top-level packages:

| Layer | Package | May depend on | Contents |
|---|---|---|---|
| Domain | `app/domain` | nothing (stdlib only) | Entities/value objects (`LoteVista`, `ResultadoFuente`), pure rules (`evaluar_vencimiento`, GS1 parsing) and **ports** declared as `typing.Protocol` |
| Application | `app/application` | domain | Use cases: `ServicioAlertas`, `ServicioAsistenteIA`, `ServicioDatosAbiertos` |
| Infrastructure | `app/infrastructure` | domain, third-party libs | Driven adapters: SQLAlchemy repositories, Gemini client, Socrata client, circuit breaker, DuckDB engine, JSON log |
| API | `app/api` | all of the above | Driving adapter: FastAPI routers, Pydantic schemas, error handlers and the **composition root** (`deps.py`, `contenedor.py`) |

Rules:

1. **Dependencies point inwards.** Domain and application never import FastAPI, SQLAlchemy, httpx, DuckDB or the
   Gemini SDK.
2. **Constructor injection.** Every use case receives its ports in `__init__` (e.g.
   `ServicioAlertas(lotes, alertas, configuracion, uow)`); there are no service locators or module-level singletons
   inside the application layer.
3. **Single composition root.** `app/api/deps.py` builds the use cases per request with FastAPI `Depends`;
   long-lived adapters that hold state (circuit breakers) are created once in `app/api/contenedor.py`.
4. **Ports are structural (`Protocol`)**, so adapters and test doubles do not need to inherit from anything.

## Consequences

**Positive**

* Use cases are tested with `unittest.mock.Mock(spec=Port)` — Mockito-style stubbing and verification — without a
  database or network (`tests/test_servicios_di.py`).
* Swapping Gemini for another LLM, MySQL for PostgreSQL or datos.gov.co for a mirror only touches one adapter and
  the composition root.
* FastAPI's `app.dependency_overrides` replaces whole use cases in integration tests.

**Negative / trade-offs**

* More files and one mapping step (ORM `Lote` → domain `LoteVista`) per repository call.
* Some CRUD endpoints (medicines, suppliers) still use the SQLAlchemy session directly from the router because they
  carry no business rules; this is a deliberate, documented exception to keep the change scope reasonable.
* `typing.Protocol` is not enforced at runtime; mismatches are caught by tests and static type checkers.

## Alternatives considered

* **Keep the layered structure** — rejected: does not satisfy Guide 6 and keeps tests coupled to the DB.
* **A DI framework (`dependency-injector`, `punq`)** — rejected for now: FastAPI `Depends` plus a small container
  covers our needs without another dependency.
