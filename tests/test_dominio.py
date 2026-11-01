"""Pruebas unitarias de las reglas puras (sin base de datos ni HTTP)."""
from datetime import date

import pytest

from app.domain.shared.enums import EstadoLote, NivelAlerta
from app.domain.inventario.escaneo import CodigoInvalidoError, digito_control_gs1_valido, interpretar_codigo
from app.domain.inventario.vencimiento import evaluar_vencimiento

HOY = date(2026, 10, 14)


@pytest.mark.parametrize("vence, nivel, estado, vendible", [
    (date(2026, 10, 13), NivelAlerta.VENCIDO, EstadoLote.VENCIDO, False),
    (date(2026, 10, 14), NivelAlerta.CRITICA, EstadoLote.PROXIMO_VENCER, True),
    (date(2026, 10, 24), NivelAlerta.CRITICA, EstadoLote.PROXIMO_VENCER, True),     # 10 días
    (date(2026, 10, 25), NivelAlerta.PREVENTIVA, EstadoLote.PROXIMO_VENCER, True),  # 11 días
    (date(2026, 11, 13), NivelAlerta.PREVENTIVA, EstadoLote.PROXIMO_VENCER, True),  # 30 días
    (date(2026, 11, 14), None, EstadoLote.VIGENTE, True),                           # 31 días
])
def test_clasificacion_por_dias(vence, nivel, estado, vendible):
    ev = evaluar_vencimiento(vence, HOY, 30)
    assert (ev.nivel_alerta, ev.estado_lote, ev.apto_para_venta) == (nivel, estado, vendible)


def test_umbral_preventivo_nunca_menor_a_10():
    assert evaluar_vencimiento(date(2026, 10, 20), HOY, umbral_preventivo=3).nivel_alerta is NivelAlerta.CRITICA


def test_agotado_y_baja_no_son_vendibles():
    assert evaluar_vencimiento(date(2027, 1, 1), HOY, cantidad_disponible=0).estado_lote is EstadoLote.AGOTADO
    assert evaluar_vencimiento(date(2027, 1, 1), HOY, dado_de_baja=True).estado_lote is EstadoLote.BAJA


def test_digito_control_ean13():
    assert digito_control_gs1_valido("7702057070014") is True
    assert digito_control_gs1_valido("7702057070019") is False


def test_gs1_legible():
    r = interpretar_codigo("(01)07702057070014(17)271231(10)LT-2026-001")
    assert r.formato == "GS1_LEGIBLE" and r.codigo_barras == "07702057070014"
    assert r.numero_lote == "LT-2026-001" and r.fecha_vencimiento == date(2027, 12, 31)
    assert "7702057070014" in r.codigos_candidatos() and r.advertencias == []


def test_gs1_crudo_con_fnc1_y_dia_00():
    r = interpretar_codigo("]d2010770205707001417270200" + "10ABC123\x1d21SN99")
    assert r.formato == "GS1_CRUDO" and r.numero_lote == "ABC123" and r.serial == "SN99"
    assert r.fecha_vencimiento == date(2027, 2, 28)  # DD=00 → último día del mes


def test_ean_simple_y_qr_json():
    assert interpretar_codigo("7702057070014").formato == "CODIGO_BARRAS"
    r = interpretar_codigo('{"codigo_barras":"7702057070014","numero_lote":"L9","fecha_vencimiento":"2027-05-01"}')
    assert r.formato == "QR_SITRAL" and r.fecha_vencimiento == date(2027, 5, 1)


@pytest.mark.parametrize("codigo", ["", "hola", "(17)271331", '{"x":1}'])
def test_codigos_invalidos(codigo):
    with pytest.raises(CodigoInvalidoError):
        interpretar_codigo(codigo)


def test_rag_prioriza_coincidencia_lexica_y_urgencia():
    from app.domain.asistente.rag import DocumentoRAG, recuperar

    docs = [
        DocumentoRAG("a", "Lote A1 de Amoxicilina 500 mg. Disponibles: 30.", {"nivel_alerta": None, "dias_para_vencer": 200}),
        DocumentoRAG("b", "Lote B2 de Loratadina 10 mg. Disponibles: 5.", {"nivel_alerta": "CRITICA", "dias_para_vencer": 3}),
        DocumentoRAG("c", "Lote C3 de Omeprazol 20 mg. Disponibles: 8.", {"nivel_alerta": "VENCIDO", "dias_para_vencer": -2}),
    ]
    assert recuperar(docs, "¿Cuánta amoxicilina tengo?", k=1)[0].documento.id == "a"
    assert [r.documento.id for r in recuperar(docs, "¿Qué está vencido o por vencer?", k=2)] == ["c", "b"]
    assert recuperar(docs, "xyz", k=1)[0].documento.id == "c"  # sin coincidencias: el más urgente


def test_lote_a_11_dias_es_preventivo():
    """Prueba sugerida por GitHub Copilot (Guía 6) y revisada por el equipo: frontera 10/11 días."""
    ev = evaluar_vencimiento(date(2026, 10, 25), HOY, 30)
    assert ev.dias_para_vencer == 11
    assert ev.nivel_alerta is NivelAlerta.PREVENTIVA
