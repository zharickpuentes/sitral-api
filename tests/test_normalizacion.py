"""Normalización de registros de datos.gov.co y extracción de principios activos."""
from app.application.datos_abiertos.servicio import normalizar_registro, principio_activo
from app.infrastructure.datos_abiertos.normalizacion import cobertura_campos, normalizar_cum, normalizar_municipio


def test_divipola_con_nombres_alternativos_y_ceros_a_la_izquierda():
    a = normalizar_municipio({"cod_dpto": "5", "dpto": "ANTIOQUIA", "cod_mpio": "5001", "nom_mpio": "MEDELLÍN",
                              "latitud": "6,25", "longitud": "-75.56"})
    b = normalizar_municipio({"c_digo_dane_del_departamento": "05", "departamento": "Antioquia",
                              "c_digo_dane_del_municipio": "05.001", "municipio": "Medellín"})
    assert a["cod_departamento"] == b["cod_departamento"] == "05"
    assert a["cod_municipio"] == b["cod_municipio"] == "05001"
    assert a["latitud"] == 6.25


def test_divipola_deduce_departamento_del_municipio():
    assert normalizar_municipio({"cod_mpio": "11001", "nom_mpio": "BOGOTÁ, D.C."})["cod_departamento"] == "11"


def test_cum_campos_canonicos():
    r = normalizar_cum({"producto": "DOLEX 500 MG", "titular": "GSK", "registrosanitario": "INVIMA 2019M-0012345",
                        "estadoregistro": "Vigente", "formafarmaceutica": "TABLETA", "principioactivo": "ACETAMINOFEN"})
    assert r["registro_sanitario"] == "INVIMA 2019M-0012345" and r["forma_farmaceutica"] == "TABLETA"
    assert r["atc"] is None
    assert cobertura_campos([r])["producto"] == 100.0 and cobertura_campos([r])["atc"] == 0.0


def test_principio_activo_para_buscar_en_el_cum():
    assert principio_activo("Acetaminofén 500 mg", "500 mg") == "ACETAMINOFEN"
    assert principio_activo("Hidróxido de aluminio y magnesio") == "HIDROXIDO DE ALUMINIO Y MAGNESIO"
    assert principio_activo("Losartán 50 mg") == "LOSARTAN"


def test_registro_sanitario_se_compara_sin_espacios_ni_guiones():
    assert normalizar_registro("INVIMA 2019M-0012345") == normalizar_registro("invima2019m0012345")
