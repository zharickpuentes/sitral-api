"""Caso de uso: datos abiertos colombianos + analítica (inyección por constructor).

Fuentes:
* INVIMA — Código Único de Medicamentos (CUM), publicado en datos.gov.co.
* DANE — División Político-Administrativa (DIVIPOLA), publicada en datos.gov.co.

El servicio no sabe si los datos vienen de la API, de la caché o de un Mock:
solo conoce los puertos del dominio.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from app.application.alertas.servicio import evaluar_lote
from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError, ResultadoFuente
from app.domain.datos_abiertos.puertos import CatalogoMedicamentosPort, DivisionPoliticaPort, MotorAnaliticoPort
from app.domain.inventario.modelos import LoteVista
from app.domain.inventario.puertos import LoteRepositorio

_PRIORIDAD_RIESGO = {"VENCIDO": 0, "CRITICA": 1, "PREVENTIVA": 2, None: 3}


def principio_activo(nombre: str, concentracion: str | None = None) -> str:
    """'Acetaminofén 500 mg' → 'ACETAMINOFEN' (formato de búsqueda en el CUM)."""
    texto = nombre
    if concentracion:
        texto = texto.replace(concentracion, " ")
    texto = re.split(r"\s\d", texto)[0]                      # corta en la primera cifra
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().upper()


def normalizar_registro(valor: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (valor or "").upper())


class ServicioDatosAbiertos:
    """Orquesta las dos APIs públicas y el motor analítico. Dependencias por constructor."""

    def __init__(self, catalogo_cum: CatalogoMedicamentosPort, divipola: DivisionPoliticaPort,
                 analitica: MotorAnaliticoPort, lotes: LoteRepositorio, umbral_preventivo: int,
                 max_principios: int = 8):
        self._cum = catalogo_cum
        self._divipola = divipola
        self._analitica = analitica
        self._lotes = lotes
        self._umbral = umbral_preventivo
        self._max_principios = max_principios

    # ------------------------------------------------------------ fuentes
    def fuentes(self) -> dict[str, Any]:
        return {"invima_cum": self._cum, "dane_divipola": self._divipola}

    def estado_circuitos(self) -> list[dict[str, Any]]:
        return [f.estado() for f in self.fuentes().values()]

    def buscar_medicamentos(self, termino: str, limite: int = 50) -> ResultadoFuente:
        return self._cum.buscar(termino, limite)

    def verificar_registro(self, registro_sanitario: str) -> tuple[bool, ResultadoFuente]:
        """Busca un registro sanitario INVIMA y filtra las coincidencias exactas."""
        buscado = normalizar_registro(registro_sanitario)
        res = self._cum.buscar(registro_sanitario, 100)
        exactos = [r for r in res.registros if normalizar_registro(r.get("registro_sanitario", "")) == buscado]
        res.registros = exactos
        res.total = len(exactos)
        return bool(exactos), res

    def municipios(self, cod_departamento: str | None = None) -> ResultadoFuente:
        res = self._divipola.municipios()
        if cod_departamento:
            cod = cod_departamento.zfill(2)
            res.registros = [m for m in res.registros if m.get("cod_departamento") == cod]
            res.total = len(res.registros)
        return res

    # ------------------------------------------------------------ inventario → filas analíticas
    def filas_inventario(self, hoy: date) -> list[dict[str, Any]]:
        filas = []
        for lote in self._lotes.listar_con_existencias():
            ev = evaluar_lote(lote, hoy, self._umbral)
            filas.append({
                "id_lote": lote.id_lote, "numero_lote": lote.numero_lote, "medicamento": lote.medicamento,
                "principio_activo": principio_activo(lote.medicamento, lote.concentracion),
                "proveedor": lote.proveedor, "cod_municipio": lote.cod_municipio_proveedor,
                "cantidad": lote.cantidad_disponible, "dias": ev.dias_para_vencer,
                "nivel": ev.nivel_alerta.value if ev.nivel_alerta else "VIGENTE",
                "precio": lote.precio, "valor": round(lote.cantidad_disponible * lote.precio, 2),
            })
        return filas

    def principios_prioritarios(self, filas: list[dict[str, Any]]) -> list[str]:
        """Principios activos del inventario, primero los que tienen lotes en riesgo."""
        mejor: dict[str, int] = {}
        for f in filas:
            nivel = f["nivel"] if f["nivel"] != "VIGENTE" else None
            p = f["principio_activo"]
            mejor[p] = min(mejor.get(p, 9), _PRIORIDAD_RIESGO[nivel])
        return [p for p, _ in sorted(mejor.items(), key=lambda x: (x[1], x[0]))][: self._max_principios]

    # ------------------------------------------------------------ analítica
    def oferta_mercado(self, hoy: date) -> dict[str, Any]:
        """Consulta 1: oferta registrada en el CUM para los principios activos del inventario."""
        principios = self.principios_prioritarios(self.filas_inventario(hoy))
        registros: list[dict[str, Any]] = []
        origenes: dict[str, str] = {}
        for p in principios:
            try:
                res = self._cum.buscar(p, 200)
            except FuenteNoDisponibleError as exc:
                origenes[p] = f"no disponible: {exc.mensaje}"
                continue
            origenes[p] = res.origen
            registros += [{**r, "principio_buscado": p} for r in res.registros]
        resultado = self._analitica.oferta_por_principio(registros)
        resultado["origenes"] = origenes
        return resultado

    def estadisticas_inventario(self, hoy: date) -> dict[str, Any]:
        """Consulta 2: estadísticas descriptivas del inventario por nivel de alerta."""
        return self._analitica.estadisticas_inventario(self.filas_inventario(hoy))

    def cobertura_regional(self, hoy: date) -> dict[str, Any]:
        """Consulta 3: inventario por departamento y municipio del proveedor (cruce con DIVIPOLA)."""
        res = self._divipola.municipios()
        resultado = self._analitica.cobertura_regional(self.filas_inventario(hoy), res.registros)
        resultado["origen_divipola"] = res.origen
        return resultado
