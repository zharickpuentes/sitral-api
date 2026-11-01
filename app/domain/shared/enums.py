"""Enumeraciones del dominio SITRAL.

Los valores coinciden con los ENUM definidos en el modelo relacional de la
Fase 1 (Figura 14 de la propuesta). Este módulo solo depende de la librería
estándar para poder probarse sin base de datos.
"""
from enum import Enum


class RolNombre(str, Enum):
    ADMINISTRADOR = "ADMINISTRADOR"
    FARMACEUTA = "FARMACEUTA"


class EstadoRegistro(str, Enum):
    """Estado lógico usado en usuario, proveedor y medicamento (borrado lógico)."""
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class EstadoLote(str, Enum):
    VIGENTE = "VIGENTE"
    PROXIMO_VENCER = "PROXIMO_VENCER"
    VENCIDO = "VENCIDO"
    AGOTADO = "AGOTADO"
    BAJA = "BAJA"  # retirado del inventario (p. ej. destrucción por vencimiento)


class NivelAlerta(str, Enum):
    """Se almacena en la columna `alerta.tipo`."""
    PREVENTIVA = "PREVENTIVA"  # dentro del umbral configurable (línea base 30 días)
    CRITICA = "CRITICA"        # dentro del umbral estricto de 10 días
    VENCIDO = "VENCIDO"        # la fecha de vencimiento ya pasó


class EstadoAlerta(str, Enum):
    PENDIENTE = "PENDIENTE"
    ATENDIDA = "ATENDIDA"
    ESCALADA = "ESCALADA"  # reemplazada por una alerta de mayor nivel


class TipoFactura(str, Enum):
    ENTRADA = "ENTRADA"
    SALIDA = "SALIDA"


class EstadoFactura(str, Enum):
    ACTIVA = "ACTIVA"
    ANULADA = "ANULADA"


class TipoMovimiento(str, Enum):
    ENTRADA = "ENTRADA"
    SALIDA = "SALIDA"
    AJUSTE = "AJUSTE"
    BAJA = "BAJA"


class EstadoConfiguracion(str, Enum):
    ACTIVA = "ACTIVA"
    INACTIVA = "INACTIVA"
