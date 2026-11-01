"""Recuperación para RAG básico (Retrieve → Augment → Generate).

Cada lote con existencias se convierte en un documento de texto. Ante una
pregunta se puntúa cada documento con BM25 (léxico, sin costo de embeddings) y
se suma un refuerzo por urgencia cuando la pregunta trata de vencimientos.
Los k documentos mejor puntuados se insertan como CONTEXTO en el prompt.
Solo depende de la librería estándar.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

_STOPWORDS = {
    "a", "al", "algo", "como", "con", "cual", "cuales", "cuanto", "cuantos", "cuantas", "de", "del", "el", "en",
    "es", "esta", "estan", "hay", "la", "las", "lo", "los", "me", "mi", "mis", "o", "para", "por", "que", "se",
    "si", "son", "su", "sus", "tengo", "tiene", "tienen", "un", "una", "unos", "y", "ya", "debo", "hacer", "cada",
    "uno", "dime", "indica", "muestra", "cuando", "donde", "todos", "todas", "hoy",
}
_INTENCION_VENCIMIENTO = ("venc", "caduc", "expir", "alerta", "critic", "urgent", "pronto", "proxim", "riesgo",
                          "perd", "baja", "fefo", "rotar", "priori")
_PESO_URGENCIA = {"VENCIDO": 3.0, "CRITICA": 2.5, "PREVENTIVA": 1.2}


def normalizar(texto: str) -> list[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", sin_tildes) if t not in _STOPWORDS and len(t) > 1]


@dataclass
class DocumentoRAG:
    id: str
    texto: str
    metadatos: dict = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = normalizar(self.texto)


@dataclass
class Recuperado:
    documento: DocumentoRAG
    puntaje: float


def pregunta_sobre_vencimientos(pregunta: str) -> bool:
    return any(raiz in t for t in normalizar(pregunta) for raiz in _INTENCION_VENCIMIENTO)


def recuperar(documentos: list[DocumentoRAG], pregunta: str, k: int = 8,
              k1: float = 1.5, b: float = 0.75) -> list[Recuperado]:
    if not documentos:
        return []
    consulta = normalizar(pregunta)
    n = len(documentos)
    promedio = sum(len(d.tokens) for d in documentos) / n
    df = Counter(t for d in documentos for t in set(d.tokens))
    urgente = pregunta_sobre_vencimientos(pregunta)

    resultados = []
    for doc in documentos:
        tf = Counter(doc.tokens)
        puntaje = 0.0
        for termino in consulta:
            if termino not in tf:
                continue
            idf = math.log(1 + (n - df[termino] + 0.5) / (df[termino] + 0.5))
            frec = tf[termino]
            puntaje += idf * frec * (k1 + 1) / (frec + k1 * (1 - b + b * len(doc.tokens) / promedio))
        if urgente:
            puntaje += _PESO_URGENCIA.get(doc.metadatos.get("nivel_alerta") or "", 0.0)
        resultados.append(Recuperado(doc, round(puntaje, 4)))

    resultados.sort(key=lambda r: (-r.puntaje, r.documento.metadatos.get("dias_para_vencer", 10**6)))
    if all(r.puntaje == 0 for r in resultados):
        # Sin coincidencias léxicas: se devuelven los lotes más próximos a vencer.
        resultados.sort(key=lambda r: r.documento.metadatos.get("dias_para_vencer", 10**6))
    return [r for r in resultados[:k]]
