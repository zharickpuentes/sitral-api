"""Pruebas unitarias estilo Mockito de los casos de uso (capa de aplicación).

Cada servicio recibe sus puertos por constructor, así que aquí se reemplazan por
`unittest.mock.Mock(spec=Puerto)`: se programan respuestas (when → thenReturn),
se verifican las interacciones (verify) y nunca se toca la base de datos, la red
ni el LLM.
"""
from datetime import date, timedelta
from unittest.mock import Mock, call

import pytest

from app.application.alertas.servicio import ServicioAlertas
from app.application.asistente.prompts import Tecnica
from app.application.asistente.servicio import PreciosLLM, ServicioAsistenteIA
from app.application.datos_abiertos.servicio import ServicioDatosAbiertos
from app.domain.alertas.modelos import AlertaRegistro, ConfiguracionAlerta
from app.domain.alertas.puertos import AlertaRepositorio, ConfiguracionAlertaRepositorio, UnidadDeTrabajo
from app.domain.asistente.puertos import LimiteExcedidoError, LLMError, LLMResult
from app.domain.datos_abiertos.modelos import FuenteNoDisponibleError, ResultadoFuente
from app.domain.datos_abiertos.puertos import CatalogoMedicamentosPort, DivisionPoliticaPort, MotorAnaliticoPort
from app.domain.inventario.modelos import LoteVista
from app.domain.inventario.puertos import LoteRepositorio
from app.domain.shared.enums import EstadoAlerta, EstadoLote

HOY = date(2026, 10, 14)


def lote(id_lote=1, dias=5, cantidad=20, estado=EstadoLote.VIGENTE, nombre="Acetaminofén 500 mg", conc="500 mg",
         precio=3500.0, mpio="11001"):
    return LoteVista(id_lote=id_lote, numero_lote=f"L-{id_lote}", medicamento=nombre, codigo_barras="7702057070014",
                     proveedor="Distribuidora Andina", cantidad_inicial=40, cantidad_disponible=cantidad,
                     fecha_ingreso=HOY - timedelta(days=90), fecha_vencimiento=HOY + timedelta(days=dias),
                     estado=estado, precio=precio, concentracion=conc, cod_municipio_proveedor=mpio)


# ===================================================================== Alertas
@pytest.fixture()
def puertos_alertas():
    lotes = Mock(spec=LoteRepositorio)
    alertas = Mock(spec=AlertaRepositorio)
    config = Mock(spec=ConfiguracionAlertaRepositorio)
    uow = Mock(spec=UnidadDeTrabajo)
    config.obtener.return_value = ConfiguracionAlerta(1, 30)
    alertas.listar_por_lote.return_value = []
    alertas.crear.side_effect = lambda id_lote, tipo, msg, dias: AlertaRegistro(99, id_lote, tipo,
                                                                                EstadoAlerta.PENDIENTE, dias, msg)
    return lotes, alertas, config, uow


def test_generar_crea_alerta_critica_actualiza_estado_y_confirma(puertos_alertas):
    lotes, alertas, config, uow = puertos_alertas
    lotes.listar_no_dados_de_baja.return_value = [lote(dias=5)]

    resumen = ServicioAlertas(lotes, alertas, config, uow).generar(HOY)

    lotes.actualizar_estado.assert_called_once_with(1, EstadoLote.PROXIMO_VENCER)
    id_lote, tipo, mensaje, dias = alertas.crear.call_args.args
    assert (id_lote, tipo, dias) == (1, "CRITICA", 5) and "L-1" in mensaje
    uow.commit.assert_called_once()
    assert resumen.alertas_nuevas["CRITICA"] == 1 and resumen.lotes_actualizados == 1


def test_generar_escala_la_preventiva_pendiente_cuando_pasa_a_critica(puertos_alertas):
    lotes, alertas, config, uow = puertos_alertas
    lotes.listar_no_dados_de_baja.return_value = [lote(dias=8, estado=EstadoLote.PROXIMO_VENCER)]
    alertas.listar_por_lote.return_value = [AlertaRegistro(7, 1, "PREVENTIVA", EstadoAlerta.PENDIENTE, 12)]

    resumen = ServicioAlertas(lotes, alertas, config, uow).generar(HOY)

    alertas.actualizar.assert_called_once_with(7, estado=EstadoAlerta.ESCALADA)
    assert resumen.alertas_escaladas == 1
    lotes.actualizar_estado.assert_not_called()          # el estado ya era correcto


def test_lote_agotado_no_genera_alerta(puertos_alertas):
    lotes, alertas, config, uow = puertos_alertas
    lotes.listar_no_dados_de_baja.return_value = [lote(dias=3, cantidad=0, estado=EstadoLote.AGOTADO)]
    ServicioAlertas(lotes, alertas, config, uow).generar(HOY)
    alertas.crear.assert_not_called()


def test_umbral_invalido_no_toca_la_base(puertos_alertas):
    lotes, alertas, config, uow = puertos_alertas
    servicio = ServicioAlertas(lotes, alertas, config, uow)
    with pytest.raises(ValueError):
        servicio.actualizar_umbral(5)
    config.actualizar_dias.assert_not_called()
    uow.commit.assert_not_called()


def test_umbral_preventivo_nunca_baja_de_10(puertos_alertas):
    lotes, alertas, config, uow = puertos_alertas
    config.obtener.return_value = ConfiguracionAlerta(1, 3)
    assert ServicioAlertas(lotes, alertas, config, uow).umbral_preventivo() == 10


# ===================================================================== Asistente IA
@pytest.fixture()
def asistente():
    lotes = Mock(spec=LoteRepositorio)
    lotes.listar_con_existencias.return_value = [lote(1, dias=4), lote(2, dias=200, nombre="Losartán 50 mg",
                                                                        conc="50 mg")]
    llm = Mock()
    llm.model = "gemini-mock"
    llm.generate.return_value = LLMResult("Retire L-1.", "gemini-mock", 1000, 100, 50, 15)
    limitador = Mock()
    limitador.maximo = 10
    limitador.verificar.return_value = None
    bitacora = Mock()
    servicio = ServicioAsistenteIA(lotes, 30, llm, bitacora, limitador, PreciosLLM(0.75, 3.75))
    return servicio, llm, bitacora, limitador


def test_asistente_inyecta_contexto_rag_y_calcula_costo(asistente):
    servicio, llm, bitacora, _ = asistente
    r = servicio.consultar(5, "¿Qué lotes vencen pronto?", Tecnica.ZERO_SHOT, HOY)
    system, prompt = llm.generate.call_args.args
    assert "L-1" in prompt and "10" in system
    assert r.costo_estimado_usd == pytest.approx(0.0013125)
    assert r.fuentes[0]["numero_lote"] == "L-1"
    bitacora.registrar.assert_called_once()
    assert bitacora.registrar.call_args.args[0]["estado"] == 200


def test_asistente_respeta_el_limite_sin_llamar_al_llm(asistente):
    servicio, llm, bitacora, limitador = asistente
    limitador.verificar.return_value = 42
    with pytest.raises(LimiteExcedidoError) as exc:
        servicio.consultar(5, "¿Qué vence?", Tecnica.COT, HOY)
    assert exc.value.retry_after == 42
    llm.generate.assert_not_called()
    bitacora.registrar.assert_not_called()


def test_asistente_registra_y_propaga_errores_del_llm(asistente):
    servicio, llm, bitacora, _ = asistente
    llm.generate.side_effect = LLMError(504, "timeout")
    with pytest.raises(LLMError):
        servicio.consultar(5, "¿Qué vence?", Tecnica.FEW_SHOT, HOY)
    evento = bitacora.registrar.call_args.args[0]
    assert evento["estado"] == 504 and evento["tecnica"] == "few_shot"


# ===================================================================== Datos abiertos
def resultado(fuente, registros, origen="api"):
    return ResultadoFuente(fuente, registros, origen, "CLOSED", "2026-10-30T12:00:00+00:00")


@pytest.fixture()
def datos_abiertos():
    cum = Mock(spec=CatalogoMedicamentosPort)
    divipola = Mock(spec=DivisionPoliticaPort)
    motor = Mock(spec=MotorAnaliticoPort)
    lotes = Mock(spec=LoteRepositorio)
    lotes.listar_con_existencias.return_value = [
        lote(1, dias=-3), lote(2, dias=6, nombre="Losartán 50 mg", conc="50 mg"),
        lote(3, dias=300, nombre="Omeprazol 20 mg", conc="20 mg", mpio="25175"),
    ]
    servicio = ServicioDatosAbiertos(cum, divipola, motor, lotes, umbral_preventivo=30, max_principios=8)
    return servicio, cum, divipola, motor


def test_verificar_registro_filtra_coincidencias_exactas(datos_abiertos):
    servicio, cum, *_ = datos_abiertos
    cum.buscar.return_value = resultado("invima_cum", [
        {"registro_sanitario": "INVIMA 2019M-0012345", "producto": "A"},
        {"registro_sanitario": "INVIMA 2019M-0012345-R1", "producto": "B"},
    ])
    encontrado, res = servicio.verificar_registro("invima 2019m-0012345")
    assert encontrado and res.total == 1 and res.registros[0]["producto"] == "A"


def test_municipios_filtra_por_departamento(datos_abiertos):
    servicio, _, divipola, _ = datos_abiertos
    divipola.municipios.return_value = resultado("dane_divipola", [
        {"cod_departamento": "25", "cod_municipio": "25175"}, {"cod_departamento": "11", "cod_municipio": "11001"}])
    assert servicio.municipios("25").total == 1


def test_filas_inventario_clasifican_por_nivel_y_valor(datos_abiertos):
    servicio, *_ = datos_abiertos
    filas = {f["id_lote"]: f for f in servicio.filas_inventario(HOY)}
    assert (filas[1]["nivel"], filas[2]["nivel"], filas[3]["nivel"]) == ("VENCIDO", "CRITICA", "VIGENTE")
    assert filas[1]["valor"] == 20 * 3500 and filas[3]["cod_municipio"] == "25175"


def test_oferta_mercado_prioriza_riesgo_y_tolera_una_fuente_caida(datos_abiertos):
    servicio, cum, _, motor = datos_abiertos

    def buscar(principio, limite):
        if principio == "LOSARTAN":
            raise FuenteNoDisponibleError("invima_cum", "circuit OPEN")
        return resultado("invima_cum", [{"producto": principio}], origen="cache")

    cum.buscar.side_effect = buscar
    motor.oferta_por_principio.return_value = {"filas": [], "resumen": {}, "sql": {}}

    salida = servicio.oferta_mercado(HOY)

    assert cum.buscar.call_args_list == [call("ACETAMINOFEN", 200), call("LOSARTAN", 200), call("OMEPRAZOL", 200)]
    enviados = motor.oferta_por_principio.call_args.args[0]
    assert {r["principio_buscado"] for r in enviados} == {"ACETAMINOFEN", "OMEPRAZOL"}
    assert salida["origenes"]["ACETAMINOFEN"] == "cache" and salida["origenes"]["LOSARTAN"].startswith("no disponible")


def test_cobertura_regional_cruza_inventario_con_divipola(datos_abiertos):
    servicio, _, divipola, motor = datos_abiertos
    municipios = [{"cod_departamento": "11", "departamento": "BOGOTÁ", "cod_municipio": "11001", "municipio": "BOGOTÁ"}]
    divipola.municipios.return_value = resultado("dane_divipola", municipios)
    motor.cobertura_regional.return_value = {"filas": [], "resumen_divipola": {}, "sql": {}}

    salida = servicio.cobertura_regional(HOY)

    inventario, enviados = motor.cobertura_regional.call_args.args
    assert len(inventario) == 3 and enviados == municipios
    assert salida["origen_divipola"] == "api"
