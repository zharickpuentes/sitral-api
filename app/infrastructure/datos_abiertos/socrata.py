"""Cliente HTTP de la API SODA (Socrata) de datos.gov.co.

URL: https://www.datos.gov.co/resource/<dataset_id>.json?$limit=...&$q=...
Un App Token es opcional, pero sube el límite de solicitudes (cabecera X-App-Token).
"""
from __future__ import annotations

from typing import Any

import httpx


class ErrorFuenteExterna(Exception):
    """Fallo al consultar una API externa. `reintentable` indica si vale la pena reintentar."""

    def __init__(self, mensaje: str, status: int | None = None, reintentable: bool = True):
        super().__init__(mensaje)
        self.status = status
        self.reintentable = reintentable


class ClienteSocrata:
    def __init__(self, base_url: str, app_token: str = "", timeout_s: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        headers = {"Accept": "application/json", "User-Agent": "SITRAL/1.0 (UMB academic project)"}
        if app_token:
            headers["X-App-Token"] = app_token
        self._cliente = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                                     timeout=timeout_s, transport=transport)

    def consultar(self, dataset_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = self._cliente.get(f"/{dataset_id}.json", params=params)
        except httpx.TimeoutException as exc:
            raise ErrorFuenteExterna(f"Timeout calling dataset {dataset_id}") from exc
        except httpx.TransportError as exc:
            raise ErrorFuenteExterna(f"Network error calling dataset {dataset_id}: {exc}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise ErrorFuenteExterna(f"datos.gov.co answered {resp.status_code}", resp.status_code, True)
        if resp.status_code >= 400:
            # 4xx (consulta mal formada, dataset inexistente): reintentar no sirve
            raise ErrorFuenteExterna(f"datos.gov.co answered {resp.status_code}: {resp.text[:200]}",
                                     resp.status_code, reintentable=False)
        try:
            datos = resp.json()
        except ValueError as exc:
            raise ErrorFuenteExterna("datos.gov.co returned invalid JSON") from exc
        if not isinstance(datos, list):
            raise ErrorFuenteExterna("Unexpected response format from datos.gov.co", resp.status_code, False)
        return datos
