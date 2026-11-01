# ADR 0002 — DDD bounded contexts

* **Status:** Accepted
* **Date:** 2026-10-30
* **Related:** ADR 0001

## Context

SITRAL serves independent drugstores. The same word means different things depending on who uses it:
a *lote* (batch) is stock to sell for the pharmacist, the subject of an alert for the "System" actor, a retrieval
document for the AI assistant, and a row to be enriched with INVIMA/DANE data for analytics. Mixing these concerns in
one model made the Guide 5 `services/` package grow without clear boundaries.

## Decision

Split the domain and application layers into four **bounded contexts**, each with its own models and ports, plus a
small shared kernel:

| Context | Domain package | Ubiquitous language | Main use case |
|---|---|---|---|
| **Inventory** (*Inventario*) | `domain/inventario` | lote, medicamento, FEFO, escaneo GS1/QR, vencimiento | rules used by batch endpoints |
| **Expiry alerts** (*Alertas*) | `domain/alertas` | alerta PREVENTIVA / CRITICA / VENCIDO, umbral, escalamiento | `ServicioAlertas` |
| **AI assistant** (*Asistente*) | `domain/asistente` | pregunta, contexto RAG, técnica de prompting, costo | `ServicioAsistenteIA` |
| **Open data** (*Datos abiertos*) | `domain/datos_abiertos` | fuente, registro sanitario, CUM, municipio DIVIPOLA, origen api/caché | `ServicioDatosAbiertos` |
| Shared kernel | `domain/shared` | enums (`EstadoLote`, `NivelAlerta`, `RolNombre`) | — |

Context map:

```
Inventory ──(LoteRepositorio, LoteVista)──▶ Alerts          [customer/supplier]
Inventory ──(LoteRepositorio)────────────▶ AI assistant     [customer/supplier]
Inventory ──(LoteRepositorio)────────────▶ Open data        [customer/supplier]
Open data ──(normalization)──────────────▶ datos.gov.co     [anti-corruption layer]
```

* `LoteVista` is the **published language** of the Inventory context; other contexts never see ORM entities.
* The open-data context protects the model with an **anti-corruption layer**
  (`infrastructure/datos_abiertos/normalizacion.py`): Socrata column names (`cod_mpio`, `c_digo_dane_del_municipio`,
  `registrosanitario`, …) are translated into canonical names before reaching the application layer.
* The critical window of **10 days** is an invariant of the Inventory context (`UMBRAL_CRITICO_DIAS`) and is reused,
  not redefined, by Alerts.

## Consequences

* Each context can evolve independently (e.g. changing the RAG ranking does not touch alert rules).
* Persistence is still a single MySQL schema shared by all contexts (one deployable, academic scope).
  Splitting into services would require separate schemas and events; out of scope.
* New developers find code by business concept rather than by technical layer.
