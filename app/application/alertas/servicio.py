"""Caso de uso: alertas de vencimiento (RQF008) con inyección de dependencias.

Reglas de idempotencia:
* Una alerta por (lote, nivel). Si ya fue ATENDIDA no se repite.
* Si el lote sube de nivel (PREVENTIVA → CRITICA → VENCIDO), la alerta pendiente
  anterior pasa a ESCALADA y se crea la nueva.
* Las alertas pendientes actualizan `dias_restantes` en cada ejecución.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from app.domain.alertas.modelos import PRIORIDAD_NIVEL, AlertaRegistro, ConfiguracionAlerta, ResumenGeneracion
from app.domain.alertas.puertos import AlertaRepositorio, ConfiguracionAlertaRepositorio, UnidadDeTrabajo
from app.domain.inventario.modelos import LoteVista
from app.domain.inventario.puertos import LoteRepositorio
from app.domain.inventario.vencimiento import (
    UMBRAL_CRITICO_DIAS, UMBRAL_PREVENTIVO_MAXIMO, EvaluacionVencimiento, evaluar_vencimiento,
)
from app.domain.shared.enums import EstadoAlerta, NivelAlerta


def evaluar_lote(lote: LoteVista, hoy: date, umbral: int) -> EvaluacionVencimiento:
    return evaluar_vencimiento(lote.fecha_vencimiento, hoy, umbral,
                               cantidad_disponible=lote.cantidad_disponible,
                               dado_de_baja=lote.dado_de_baja)


def mensaje_alerta(lote: LoteVista, ev: EvaluacionVencimiento) -> str:
    if ev.nivel_alerta is NivelAlerta.VENCIDO:
        texto = f"VENCIDO: {lote.medicamento} lote {lote.numero_lote} venció hace {-ev.dias_para_vencer} día(s)"
    else:
        texto = (f"{ev.nivel_alerta.value}: {lote.medicamento} lote {lote.numero_lote} "
                 f"vence en {ev.dias_para_vencer} día(s)")
    return f"{texto} ({lote.fecha_vencimiento.isoformat()}). Disponibles: {lote.cantidad_disponible}."[:255]


class ServicioAlertas:
    """Genera y sincroniza alertas. Dependencias inyectadas por constructor."""

    def __init__(self, lotes: LoteRepositorio, alertas: AlertaRepositorio,
                 configuracion: ConfiguracionAlertaRepositorio, uow: UnidadDeTrabajo):
        self._lotes = lotes
        self._alertas = alertas
        self._configuracion = configuracion
        self._uow = uow

    # ------------------------------------------------------------ configuración
    def configuracion(self) -> ConfiguracionAlerta:
        return self._configuracion.obtener()

    def umbral_preventivo(self) -> int:
        return max(self._configuracion.obtener().dias_anticipacion, UMBRAL_CRITICO_DIAS)

    def actualizar_umbral(self, dias: int) -> ConfiguracionAlerta:
        if not UMBRAL_CRITICO_DIAS <= dias <= UMBRAL_PREVENTIVO_MAXIMO:
            raise ValueError(f"dias_anticipacion must be between {UMBRAL_CRITICO_DIAS} and {UMBRAL_PREVENTIVO_MAXIMO}.")
        config = self._configuracion.actualizar_dias(dias)
        self._uow.commit()
        return config

    # ------------------------------------------------------------ sincronización
    def sincronizar_lote(self, lote: LoteVista, ev: EvaluacionVencimiento) -> tuple[AlertaRegistro | None, int]:
        """Crea o actualiza la alerta de un lote. No confirma la transacción (lo hace quien llama).

        Retorna (alerta_nueva | None, cantidad_de_alertas_escaladas).
        """
        if ev.nivel_alerta is None:
            return None, 0
        nivel = ev.nivel_alerta.value
        existentes = self._alertas.listar_por_lote(lote.id_lote)

        escaladas = 0
        for alerta in existentes:
            if alerta.estado == EstadoAlerta.PENDIENTE and PRIORIDAD_NIVEL.get(alerta.tipo, 0) < PRIORIDAD_NIVEL[nivel]:
                self._alertas.actualizar(alerta.id_alerta, estado=EstadoAlerta.ESCALADA)
                escaladas += 1

        mismo_nivel = [a for a in existentes if a.tipo == nivel and a.estado != EstadoAlerta.ESCALADA]
        if mismo_nivel:
            for alerta in mismo_nivel:
                if alerta.estado == EstadoAlerta.PENDIENTE:
                    self._alertas.actualizar(alerta.id_alerta, dias_restantes=ev.dias_para_vencer,
                                             mensaje=mensaje_alerta(lote, ev))
            return None, escaladas

        nueva = self._alertas.crear(lote.id_lote, nivel, mensaje_alerta(lote, ev), ev.dias_para_vencer)
        return nueva, escaladas

    # ------------------------------------------------------------ generación masiva
    def generar(self, hoy: date) -> ResumenGeneracion:
        """Evalúa todos los lotes no dados de baja (actor «Sistema») y confirma los cambios."""
        umbral = self.umbral_preventivo()
        lotes = self._lotes.listar_no_dados_de_baja()
        nuevas: Counter[str] = Counter({n.value: 0 for n in NivelAlerta})
        actualizados = escaladas_total = 0

        for lote in lotes:
            ev = evaluar_lote(lote, hoy, umbral)
            if lote.estado != ev.estado_lote:
                self._lotes.actualizar_estado(lote.id_lote, ev.estado_lote)
                actualizados += 1
            if lote.cantidad_disponible <= 0:
                continue
            nueva, escaladas = self.sincronizar_lote(lote, ev)
            escaladas_total += escaladas
            if nueva is not None:
                nuevas[nueva.tipo] += 1

        self._uow.commit()
        return ResumenGeneracion(
            fecha_evaluacion=hoy, umbral_critico_dias=UMBRAL_CRITICO_DIAS, umbral_preventivo_dias=umbral,
            lotes_evaluados=len(lotes), lotes_actualizados=actualizados,
            alertas_nuevas=dict(nuevas), alertas_escaladas=escaladas_total,
        )
