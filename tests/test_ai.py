"""Endpoint /api/v1/ai con un LLM simulado: RAG, técnicas de prompting y manejo de errores."""
import pytest

from app.main import app
from app.infrastructure.observabilidad import ai_soporte
from app.infrastructure.llm.gemini import LLMError, LLMResult, get_llm


class LLMFalso:
    model = "gemini-falso"

    def __init__(self, error: LLMError | None = None):
        self.error = error
        self.llamadas: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str, *, temperature=None) -> LLMResult:
        self.llamadas.append((system, prompt))
        if self.error:
            raise self.error
        return LLMResult(text="- **LT-CRIT** vence pronto.", model=self.model,
                         input_tokens=1000, output_tokens=100, thinking_tokens=50, latency_ms=12)


@pytest.fixture()
def llm_falso():
    falso = LLMFalso()
    app.dependency_overrides[get_llm] = lambda: falso
    return falso


@pytest.fixture()
def inventario(crear_lote):
    assert crear_lote("LT-CRIT", dias=4).status_code == 201
    assert crear_lote("LT-PREV", dias=20).status_code == 201
    assert crear_lote("LT-OK", dias=300).status_code == 201


PREGUNTA = "¿Qué lotes vencen pronto y qué debo hacer?"


def test_consulta_rag_inyecta_contexto_y_reporta_costos(client, farma_headers, inventario, llm_falso):
    r = client.post("/api/v1/ai/consultas", headers=farma_headers,
                    json={"pregunta": PREGUNTA, "tecnica": "zero_shot", "incluir_prompt": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fuentes"][0]["numero_lote"] == "LT-CRIT"          # el más urgente primero
    assert body["uso"] == {"input_tokens": 1000, "output_tokens": 100, "thinking_tokens": 50, "total_tokens": 1150}
    # 1000 × 0.75/1M + (100 + 50) × 3.75/1M
    assert body["costo_estimado_usd"] == pytest.approx(0.0013125)
    system, prompt = llm_falso.llamadas[0]
    assert "LT-CRIT" in prompt and "vence en 4 día(s)" in prompt and "CONTEXTO" in prompt
    assert "10 días o menos" in system and "No des recomendaciones clínicas" in system


@pytest.mark.parametrize("tecnica, marca", [
    ("zero_shot", "RESPUESTA:"),
    ("few_shot", "### Ejemplo 3"),
    ("cot", "Resuelve paso a paso"),
])
def test_cada_tecnica_usa_su_plantilla(client, farma_headers, inventario, llm_falso, tecnica, marca):
    r = client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA, "tecnica": tecnica})
    assert r.status_code == 200 and r.json()["tecnica"] == tecnica
    assert marca in llm_falso.llamadas[0][1]


def test_comparar_hace_tres_llamadas(client, farma_headers, inventario, llm_falso):
    r = client.post("/api/v1/ai/comparar", headers=farma_headers, json={"pregunta": PREGUNTA})
    assert r.status_code == 200
    assert [x["tecnica"] for x in r.json()["resultados"]] == ["zero_shot", "few_shot", "cot"]
    assert len(llm_falso.llamadas) == 3


def test_contexto_rag_sin_llamar_al_llm(client, farma_headers, inventario, llm_falso):
    r = client.get("/api/v1/ai/contexto", headers=farma_headers, params={"pregunta": PREGUNTA, "top_k": 2})
    assert r.status_code == 200
    assert [f["numero_lote"] for f in r.json()["fuentes"]] == ["LT-CRIT", "LT-PREV"]
    assert llm_falso.llamadas == []


def test_tecnica_invalida_422(client, farma_headers, llm_falso):
    r = client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA, "tecnica": "magia"})
    assert r.status_code == 422


def test_sin_token_401(client):
    assert client.post("/api/v1/ai/consultas", json={"pregunta": PREGUNTA}).status_code == 401


@pytest.mark.parametrize("error, codigo", [
    (LLMError(429, "quota", retry_after=30), 429),
    (LLMError(504, "timeout"), 504),
    (LLMError(503, "down"), 503),
])
def test_errores_del_proveedor(client, farma_headers, inventario, error, codigo):
    app.dependency_overrides[get_llm] = lambda: LLMFalso(error)
    r = client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA})
    assert r.status_code == codigo
    if codigo == 429:
        assert r.headers["Retry-After"] == "30"


def test_sin_api_key_503(client, farma_headers):
    # get_llm real con GEMINI_API_KEY vacía (conftest) → servicio no configurado
    r = client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA})
    assert r.status_code == 503
    assert "GEMINI_API_KEY" in r.json()["message"]


def test_limite_propio_por_usuario_429(client, farma_headers, inventario, llm_falso):
    ai_soporte.limitador = ai_soporte.LimitadorPorMinuto(2)
    for _ in range(2):
        assert client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA}).status_code == 200
    r = client.post("/api/v1/ai/consultas", headers=farma_headers, json={"pregunta": PREGUNTA})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
