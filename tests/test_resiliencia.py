"""Circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED) y reintentos con backoff exponencial.

Se inyecta un reloj falso y una función `dormir` falsa: las pruebas no esperan
tiempo real y los estados se pueden demostrar de forma determinista.
"""
import pytest

from app.infrastructure.resiliencia.circuit_breaker import CircuitBreaker, CircuitoAbiertoError, EstadoCircuito
from app.infrastructure.resiliencia.reintentos import PoliticaReintento


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def avanzar(self, s):
        self.t += s


def _falla():
    raise ConnectionError("datos.gov.co caído")


def _breaker(reloj, umbral=3, recuperacion=20):
    return CircuitBreaker("prueba", umbral_fallos=umbral, tiempo_recuperacion=recuperacion, reloj=reloj)


def test_cerrado_deja_pasar_y_reinicia_contador_con_exito():
    reloj = Reloj()
    cb = _breaker(reloj)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.llamar(_falla)
    assert cb.llamar(lambda: "ok") == "ok"
    assert cb.estado is EstadoCircuito.CERRADO and cb.snapshot()["fallos_consecutivos"] == 0


def test_tres_fallos_abren_el_circuito_y_rechaza_sin_llamar():
    reloj = Reloj()
    cb = _breaker(reloj)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.llamar(_falla)
    assert cb.estado is EstadoCircuito.ABIERTO

    llamadas = []
    with pytest.raises(CircuitoAbiertoError):
        cb.llamar(lambda: llamadas.append(1))
    assert llamadas == []                      # no se tocó la API externa
    assert cb.snapshot()["total_rechazadas"] == 1


def test_open_pasa_a_half_open_y_cierra_si_la_prueba_funciona():
    reloj = Reloj()
    cb = _breaker(reloj)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.llamar(_falla)
    reloj.avanzar(19.9)
    assert cb.estado is EstadoCircuito.ABIERTO
    reloj.avanzar(0.2)
    assert cb.estado is EstadoCircuito.SEMIABIERTO
    assert cb.llamar(lambda: 42) == 42
    assert cb.estado is EstadoCircuito.CERRADO
    transiciones = [(h["desde"], h["hacia"]) for h in reversed(cb.snapshot()["historial"])]
    assert transiciones == [("CLOSED", "OPEN"), ("OPEN", "HALF_OPEN"), ("HALF_OPEN", "CLOSED")]


def test_half_open_vuelve_a_open_si_la_prueba_falla():
    reloj = Reloj()
    cb = _breaker(reloj)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.llamar(_falla)
    reloj.avanzar(21)
    assert cb.estado is EstadoCircuito.SEMIABIERTO
    with pytest.raises(ConnectionError):
        cb.llamar(_falla)
    assert cb.estado is EstadoCircuito.ABIERTO
    assert cb.segundos_para_reintentar() == pytest.approx(20)


def test_errores_no_reintentables_no_abren_el_circuito():
    cb = CircuitBreaker("x", umbral_fallos=1, reloj=Reloj(), es_fallo=lambda e: not isinstance(e, ValueError))

    def consulta_mal_formada():
        raise ValueError("400 Bad Request")

    with pytest.raises(ValueError):
        cb.llamar(consulta_mal_formada)
    assert cb.estado is EstadoCircuito.CERRADO


def test_reinicio_manual():
    cb = _breaker(Reloj(), umbral=1)
    with pytest.raises(ConnectionError):
        cb.llamar(_falla)
    cb.reiniciar()
    assert cb.estado is EstadoCircuito.CERRADO


def test_backoff_exponencial_sin_jitter():
    p = PoliticaReintento(base=0.5, factor=2, maximo=8, jitter=0)
    assert [p.espera(n) for n in range(1, 7)] == [0.5, 1, 2, 4, 8, 8]


def test_reintenta_hasta_tener_exito_y_espera_lo_esperado():
    esperas, intentos = [], []

    def inestable():
        intentos.append(1)
        if len(intentos) < 3:
            raise ConnectionError("timeout")
        return "datos"

    p = PoliticaReintento(intentos=3, base=0.5, jitter=0, dormir=esperas.append)
    assert p.ejecutar(inestable) == "datos"
    assert esperas == [0.5, 1.0] and len(intentos) == 3


def test_agota_intentos_y_propaga_el_error():
    esperas = []
    p = PoliticaReintento(intentos=3, jitter=0, dormir=esperas.append)
    with pytest.raises(ConnectionError):
        p.ejecutar(_falla)
    assert len(esperas) == 2


def test_no_reintenta_errores_no_reintentables():
    esperas = []
    p = PoliticaReintento(intentos=5, es_reintentable=lambda e: False, dormir=esperas.append)
    with pytest.raises(ConnectionError):
        p.ejecutar(_falla)
    assert esperas == []

# El circuito pasa a HALF_OPEN cuando transcurre CB_RECOVERY_SECONDS
def test_circuito_pasa_a_half_open_tras_recuperacion():
    reloj = Reloj()
    cb = _breaker(reloj)  # configuración real: 3 fallos y 20 s
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.llamar(_falla)
    assert cb.estado is EstadoCircuito.ABIERTO
    reloj.avanzar(19.9)
    assert cb.estado is EstadoCircuito.ABIERTO       # aún no se cumplen los 20 s
    reloj.avanzar(0.2)
    assert cb.estado is EstadoCircuito.SEMIABIERTO   # pasados 20 s → HALF_OPEN