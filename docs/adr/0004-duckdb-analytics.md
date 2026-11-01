# ADR 0004 — DuckDB for analytical SQL over JSON

* **Status:** Accepted
* **Date:** 2026-10-30
* **Related:** ADR 0003

## Context

Guide 6 asks for JSON processing with DuckDB and at least two analytical SQL queries with descriptive statistics
shown in a user interface. The transactional store (MySQL, accessed through SQLAlchemy) is optimized for
single-row reads and writes, not for aggregations that combine local data with JSON coming from external APIs.

## Decision

Use **DuckDB** as an embedded, in-process analytical engine behind the `MotorAnaliticoPort` port
(`infrastructure/analitica/duckdb_motor.py`):

1. For every analysis, the normalized records (inventory rows, INVIMA CUM, DANE DIVIPOLA) are written to temporary
   JSON files and loaded with `read_json_auto`; a fresh in-memory connection is used per request (no shared state,
   thread-safe).
2. Three analytical queries are exposed:

| Endpoint | SQL highlights | Descriptive statistics |
|---|---|---|
| `GET /api/v1/analitica/inventario` | `GROUP BY nivel` | `COUNT`, `SUM`, `AVG`, `MEDIAN`, `STDDEV_SAMP`, `MIN`, `MAX`, `QUANTILE_CONT` (P25, P75) of days to expiry; value at risk in COP |
| `GET /api/v1/analitica/oferta-mercado` | CUM JSON `GROUP BY` active ingredient, `MODE`, `COUNT(DISTINCT)` | mean, median, standard deviation, min, max of registered presentations per ingredient |
| `GET /api/v1/analitica/cobertura-regional` | inventory `LEFT JOIN` DIVIPOLA on DANE code | % of batches at risk per municipality; mean/median/std of municipalities per department |

3. Each response includes the executed SQL so it can be audited and shown in the report.
4. The UI is a static page (`GET /dashboard`) that authenticates with JWT and draws the results with Chart.js.

## Consequences

* Zero infrastructure: DuckDB is a pip package (`duckdb`), no server.
* Analytical load never competes with transactional queries in MySQL.
* Data volume is small (hundreds of batches, a few thousand CUM rows), so loading JSON per request is cheap
  (tens of milliseconds). For large volumes we would persist Parquet files and refresh them on a schedule.
* The use case depends only on the port; tests use a fake engine, and `tests/test_analitica_duckdb.py` checks the
  real SQL when DuckDB is installed.

## Alternatives considered

* **SQL in MySQL** — would require copying the external JSON into tables and writing statistics such as the median
  by hand (MySQL has no `MEDIAN`).
* **pandas** — fine for statistics, but the guide explicitly asks for SQL with DuckDB.
