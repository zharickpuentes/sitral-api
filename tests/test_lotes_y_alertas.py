"""Lotes, validación estricta a 10 días y alertas de vencimiento (RQF005, RQF008, RQF012)."""
from datetime import timedelta

import pytest

from app.api.deps import get_today
from app.main import app
from tests.conftest import HOY


def _alertas(client, headers, **params):
    r = client.get("/api/v1/alertas", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ registro de lotes
def test_registrar_lote_vigente_crea_movimiento_de_entrada(client, farma_headers, crear_lote):
    r = crear_lote("LT-2026-001", dias=200)
    assert r.status_code == 201, r.text
    lote = r.json()
    assert lote["estado"] == "VIGENTE" and lote["nivel_alerta"] is None and lote["apto_para_venta"]
    assert lote["cantidad_disponible"] == 40

    traza = client.get(f"/api/v1/lotes/{lote['id_lote']}/trazabilidad", headers=farma_headers).json()
    assert [m["tipo_movimiento"] for m in traza["movimientos"]] == ["ENTRADA"]
    assert _alertas(client, farma_headers) == []


def test_no_se_puede_ingresar_lote_vencido_400(crear_lote):
    r = crear_lote("LT-VENCIDO", dias=-1)
    assert r.status_code == 400
    assert "expired" in r.json()["message"]


def test_lote_duplicado_409(crear_lote):
    assert crear_lote("LT-DUP", dias=100).status_code == 201
    assert crear_lote("LT-DUP", dias=100).status_code == 409


def test_lote_con_medicamento_inexistente_404(client, farma_headers, proveedor):
    r = client.post("/api/v1/lotes", headers=farma_headers, json={
        "id_medicamento": 999, "id_proveedor": proveedor["id_proveedor"], "numero_lote": "X1",
        "cantidad_inicial": 1, "fecha_vencimiento": (HOY + timedelta(days=90)).isoformat()})
    assert r.status_code == 404


@pytest.mark.parametrize("dias, nivel_esperado", [
    (1, "CRITICA"),       # vence mañana
    (10, "CRITICA"),      # límite exacto de la regla estricta
    (11, "PREVENTIVA"),   # fuera de los 10 días, dentro de la línea base de 30
    (30, "PREVENTIVA"),
    (31, None),
])
def test_limites_de_la_regla_de_10_dias(client, farma_headers, crear_lote, dias, nivel_esperado):
    r = crear_lote(f"LT-{dias}", dias=dias)
    assert r.status_code == 201, r.text
    assert r.json()["nivel_alerta"] == nivel_esperado
    alertas = _alertas(client, farma_headers)
    assert [a["tipo"] for a in alertas] == ([nivel_esperado] if nivel_esperado else [])


def test_endpoint_validacion_a_10_dias(client, farma_headers, crear_lote):
    lote = crear_lote("LT-077", dias=8).json()
    r = client.get(f"/api/v1/lotes/{lote['id_lote']}/validacion", headers=farma_headers)
    assert r.status_code == 200
    v = r.json()
    assert v["dias_para_vencer"] == 8 and v["umbral_critico_dias"] == 10
    assert v["dentro_umbral_critico"] is True and v["nivel_alerta"] == "CRITICA"
    assert v["apto_para_venta"] is True and "FEFO" in v["recomendacion"]


def test_listado_fefo_y_filtro_vence_en_10_dias(client, farma_headers, crear_lote):
    for numero, dias in (("A", 60), ("B", 5), ("C", 10), ("D", 11)):
        assert crear_lote(numero, dias=dias).status_code == 201
    todos = client.get("/api/v1/lotes", headers=farma_headers).json()
    assert [l["numero_lote"] for l in todos] == ["B", "C", "D", "A"]  # FEFO
    criticos = client.get("/api/v1/lotes", params={"vence_en_dias": 10}, headers=farma_headers).json()
    assert {l["numero_lote"] for l in criticos} == {"B", "C"}


# ------------------------------------------------------------ escaneo
def test_escanear_gs1_identifica_medicamento_y_ventana_critica(client, farma_headers, medicamento):
    vence = HOY + timedelta(days=7)
    codigo = f"(01)0{medicamento['codigo_barras']}(17){vence:%y%m%d}(10)LT-QR-01"
    r = client.post("/api/v1/lotes/escanear", headers=farma_headers, json={"codigo": codigo})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["medicamento_registrado"] and d["medicamento"]["id_medicamento"] == medicamento["id_medicamento"]
    assert d["numero_lote"] == "LT-QR-01" and d["dias_para_vencer"] == 7
    assert d["nivel_alerta"] == "CRITICA" and d["puede_ingresar"] is True


def test_escanear_codigo_ilegible_400(client, farma_headers):
    r = client.post("/api/v1/lotes/escanear", headers=farma_headers, json={"codigo": "hola-mundo"})
    assert r.status_code == 400


# ------------------------------------------------------------ baja de lotes
def test_baja_de_lote_solo_admin(client, admin_headers, farma_headers, crear_lote):
    lote = crear_lote("LT-BAJA", dias=3).json()
    assert client.delete(f"/api/v1/lotes/{lote['id_lote']}", headers=farma_headers).status_code == 403
    r = client.delete(f"/api/v1/lotes/{lote['id_lote']}", headers=admin_headers, params={"motivo": "Vencimiento"})
    assert r.status_code == 200 and r.json()["estado"] == "BAJA" and r.json()["cantidad_disponible"] == 0
    traza = client.get(f"/api/v1/lotes/{lote['id_lote']}/trazabilidad", headers=admin_headers).json()
    assert traza["unidades_dadas_de_baja"] == 40


# ------------------------------------------------------------ alertas
def test_generacion_de_alertas_es_idempotente(client, farma_headers, crear_lote):
    crear_lote("L1", dias=5)
    crear_lote("L2", dias=25)
    crear_lote("L3", dias=200)
    primera = client.post("/api/v1/alertas/generar", headers=farma_headers).json()
    segunda = client.post("/api/v1/alertas/generar", headers=farma_headers).json()
    assert primera["lotes_evaluados"] == 3
    assert sum(segunda["alertas_nuevas"].values()) == 0
    assert len(_alertas(client, farma_headers)) == 2


def test_alerta_preventiva_escala_a_critica_y_luego_a_vencido(client, farma_headers, crear_lote):
    crear_lote("L-ESC", dias=25)
    assert [a["tipo"] for a in _alertas(client, farma_headers)] == ["PREVENTIVA"]

    app.dependency_overrides[get_today] = lambda: HOY + timedelta(days=16)  # quedan 9 días
    r = client.post("/api/v1/alertas/generar", headers=farma_headers).json()
    assert r["alertas_nuevas"]["CRITICA"] == 1 and r["alertas_escaladas"] == 1
    assert [a["tipo"] for a in _alertas(client, farma_headers)] == ["CRITICA"]

    app.dependency_overrides[get_today] = lambda: HOY + timedelta(days=26)  # venció ayer
    client.post("/api/v1/alertas/generar", headers=farma_headers)
    pendientes = _alertas(client, farma_headers)
    assert [a["tipo"] for a in pendientes] == ["VENCIDO"] and pendientes[0]["dias_restantes"] == -1
    lote = client.get("/api/v1/lotes", headers=farma_headers).json()[0]
    assert lote["estado"] == "VENCIDO" and lote["apto_para_venta"] is False


def test_atender_alerta(client, farma_headers, crear_lote):
    crear_lote("L-AT", dias=4)
    alerta = _alertas(client, farma_headers)[0]
    r = client.patch(f"/api/v1/alertas/{alerta['id_alerta']}/atender", headers=farma_headers)
    assert r.status_code == 200 and r.json()["estado"] == "ATENDIDA"
    assert client.patch(f"/api/v1/alertas/{alerta['id_alerta']}/atender", headers=farma_headers).status_code == 400
    client.post("/api/v1/alertas/generar", headers=farma_headers)
    assert _alertas(client, farma_headers) == []  # no se repite una alerta ya atendida


def test_configuracion_de_umbral(client, admin_headers, farma_headers, crear_lote):
    r = client.get("/api/v1/alertas/configuracion", headers=farma_headers)
    assert r.status_code == 200 and r.json()["dias_anticipacion"] == 30 and r.json()["umbral_critico_dias"] == 10

    assert client.put("/api/v1/alertas/configuracion", headers=farma_headers,
                      json={"dias_anticipacion": 20}).status_code == 403
    assert client.put("/api/v1/alertas/configuracion", headers=admin_headers,
                      json={"dias_anticipacion": 9}).status_code == 422  # regla estricta de 10 días
    r = client.put("/api/v1/alertas/configuracion", headers=admin_headers, json={"dias_anticipacion": 20})
    assert r.status_code == 200 and r.json()["dias_anticipacion"] == 20

    assert crear_lote("L-25", dias=25).json()["nivel_alerta"] is None       # ya no es preventiva
    assert crear_lote("L-10", dias=10).json()["nivel_alerta"] == "CRITICA"  # la crítica no cambia
