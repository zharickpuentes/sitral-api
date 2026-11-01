"""Experimento de prompt engineering: ≥ 10 llamadas REALES a /api/v1/ai/consultas.

4 preguntas × 3 técnicas (zero-shot, few-shot, CoT) = 12 llamadas. Para cada
respuesta se calcula automáticamente la COBERTURA: qué porcentaje de los lotes
que deberían mencionarse (verdad de referencia obtenida de la propia API)
aparecen en la respuesta. Genera:
    resultados/experimento_<fecha>.json   (evidencia completa, incluye prompts)
    resultados/experimento_<fecha>.md     (tabla comparativa + estimación de costos en inglés)

Uso (con la API corriendo en otra terminal: uvicorn app.main:app):
    python -m scripts.experimento_prompting --usuario admin
    python -m scripts.experimento_prompting --usuario admin --completar resultados/experimento_X.json --pausa 30
"""
import argparse
import getpass
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

from app.infrastructure.config import settings

TECNICAS = ["zero_shot", "few_shot", "cot"]


def login(cliente: httpx.Client, usuario: str, password: str) -> None:
    r = cliente.post("/api/v1/auth/login", data={"username": usuario, "password": password})
    if r.status_code != 200:
        sys.exit(f"Login falló ({r.status_code}): {r.text}")
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def get(cliente: httpx.Client, ruta: str, **params):
    r = cliente.get(ruta, params=params)
    r.raise_for_status()
    return r.json()


def preguntas_con_referencia(cliente: httpx.Client) -> list[dict]:
    """Define las preguntas y calcula, desde la API, qué lotes deberían aparecer."""
    config = get(cliente, "/api/v1/alertas/configuracion")
    criticos = get(cliente, "/api/v1/lotes", vence_en_dias=10, limit=200)
    criticos = [l for l in criticos if l["dias_para_vencer"] >= 0]
    vencidos = get(cliente, "/api/v1/lotes", estado="VENCIDO", limit=200)
    amox = get(cliente, "/api/v1/medicamentos", q="Amoxicilina 500")
    lotes_amox = get(cliente, "/api/v1/lotes", id_medicamento=amox[0]["id_medicamento"]) if amox else []
    proximos = get(cliente, "/api/v1/lotes", vence_en_dias=config["dias_anticipacion"], limit=200)
    proximos = [l for l in proximos if l["dias_para_vencer"] >= 0]
    conteo = Counter(l["proveedor"]["nombre"] for l in proximos)
    top_prov = conteo.most_common(1)[0][0] if conteo else None

    return [
        {"id": "P1", "pregunta": "¿Qué lotes vencen en los próximos 10 días y qué debo hacer con cada uno?",
         "esperados": [l["numero_lote"] for l in criticos]},
        {"id": "P2", "pregunta": "¿Hay medicamentos vencidos todavía en inventario? Indica lote y cantidad.",
         "esperados": [l["numero_lote"] for l in vencidos]},
        {"id": "P3", "pregunta": "¿Cuántas unidades de Amoxicilina 500 mg hay disponibles y en qué lotes?",
         "esperados": [l["numero_lote"] for l in lotes_amox],
         "dato_clave": str(sum(l["cantidad_disponible"] for l in lotes_amox))},
        {"id": "P4", "pregunta": f"¿Qué proveedor tiene más lotes próximos a vencer en los próximos "
                                 f"{config['dias_anticipacion']} días?",
         "esperados": [], "dato_clave": top_prov},
    ]


def cobertura(respuesta: str, caso: dict) -> float | None:
    objetivos = list(caso["esperados"])
    if caso.get("dato_clave"):
        objetivos.append(caso["dato_clave"])
    if not objetivos:
        return None
    texto = respuesta.lower()
    return round(100 * sum(1 for o in objetivos if o.lower() in texto) / len(objetivos), 1)


ESPERA_429 = 60


def llamar(cliente: httpx.Client, pregunta: str, tecnica: str) -> dict:
    for intento in range(3):
        r = cliente.post("/api/v1/ai/consultas", json={"pregunta": pregunta, "tecnica": tecnica,
                                                       "top_k": 20, "incluir_prompt": True})
        if r.status_code in (429, 503) and intento < 2:
            espera = max(int(r.headers.get("Retry-After", "0")), ESPERA_429)
            print(f"   {r.status_code} → esperando {espera}s y reintentando…")
            time.sleep(espera)
            continue
        return {"status": r.status_code, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text})}
    return {"status": 429}


def proyeccion(promedios: dict, usuarios: int, consultas_dia: int, dias_mes: int) -> list[dict]:
    filas = []
    consultas_mes = usuarios * consultas_dia * dias_mes
    for etiqueta, p_in, p_out in (("2026 (introductory)", 0.75, 3.75), ("from 2027-01-01", 1.50, 7.50)):
        for tecnica, m in promedios.items():
            costo = consultas_mes * (m["input"] * p_in + (m["output"] + m["thinking"]) * p_out) / 1e6
            filas.append({"periodo": etiqueta, "tecnica": tecnica, "consultas_mes": consultas_mes,
                          "costo_mes_usd": round(costo, 4), "costo_mes_cop": round(costo * 4000)})
    return filas


def escribir_markdown(ruta: Path, meta: dict, filas: list[dict], promedios: dict, proy: list[dict]) -> None:
    L = [f"# SITRAL – Prompting experiment ({meta['fecha']})", "",
         f"Model: `{meta['modelo']}` · Calls: {len(filas)} · RAG top_k = 20 · Temperature = {settings.LLM_TEMPERATURE}", "",
         "## Table 1. Results per call", "",
         "| # | Q | Technique | HTTP | Input tok | Output tok | Thinking tok | Latency (ms) | Coverage (%) | Cost (USD) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(filas, 1):
        u = f.get("uso") or {}
        L.append(f"| {i} | {f['pregunta_id']} | {f['tecnica']} | {f['status']} | {u.get('input_tokens', '-')} | "
                 f"{u.get('output_tokens', '-')} | {u.get('thinking_tokens', '-')} | {f.get('latencia_ms', '-')} | "
                 f"{f['cobertura'] if f['cobertura'] is not None else 'n/a'} | {f.get('costo_estimado_usd', '-')} |")
    L += ["", "## Table 2. Average per technique", "",
          "| Technique | Avg input | Avg output | Avg thinking | Avg latency (ms) | Avg coverage (%) | Avg cost/call (USD) |",
          "|---|---|---|---|---|---|---|"]
    for t, m in promedios.items():
        L.append(f"| {t} | {m['input']:.0f} | {m['output']:.0f} | {m['thinking']:.0f} | {m['latencia']:.0f} | "
                 f"{m['cobertura'] if m['cobertura'] is not None else 'n/a'} | {m['costo']:.6f} |")
    L += ["", "## Table 3. Monthly cost projection", "",
          f"Assumptions: {meta['usuarios']} users × {meta['consultas_dia']} queries/day × {meta['dias_mes']} days. "
          "Prices: Gemini 3.8 Flash paid tier, USD 0.75 / 1M input tokens and USD 3.75 / 1M output tokens "
          "(thinking tokens billed as output) until 2026-12-31; USD 1.50 / 7.50 from 2027-01-01. "
          "Exchange rate assumed: 1 USD = 4,000 COP. The free tier of Google AI Studio costs USD 0 within its quota.", "",
          "| Period | Technique | Queries/month | Cost/month (USD) | Cost/month (COP) |", "|---|---|---|---|---|"]
    for p in proy:
        L.append(f"| {p['periodo']} | {p['tecnica']} | {p['consultas_mes']} | {p['costo_mes_usd']} | {p['costo_mes_cop']:,} |")
    errores = [(f["pregunta_id"], f["tecnica"], e) for f in filas for e in f.get("intentos_fallidos", [])]
    errores += [(f["pregunta_id"], f["tecnica"], {"status": f["status"], "message": f.get("message")})
                for f in filas if f["status"] != 200]
    if errores:
        L += ["", "## Table 4. Provider errors handled by the API (evidence of rate-limit / availability handling)", "",
              "| Q | Technique | HTTP | Message |", "|---|---|---|---|"]
        for q, t, e in errores:
            L.append(f"| {q} | {t} | {e.get('status')} | {(e.get('message') or '').replace('|', '/')} |")
    L += ["", "## Answers", ""]
    for i, f in enumerate(filas, 1):
        L += [f"### {i}. {f['pregunta_id']} – {f['tecnica']}", f"**Question:** {f['pregunta']}", "",
              f"**Expected batches:** {', '.join(f['esperados']) or '—'}", "",
              "```text", (f.get("respuesta") or f.get("message") or f.get("raw") or "").strip(), "```", ""]
    ruta.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Experimento zero-shot vs few-shot vs CoT sobre SITRAL")
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--pausa", type=float, default=7.0, help="Segundos entre llamadas (cuota gratuita).")
    ap.add_argument("--usuarios", type=int, default=4)
    ap.add_argument("--consultas-dia", type=int, default=20)
    ap.add_argument("--dias-mes", type=int, default=30)
    ap.add_argument("--completar", help="JSON de un experimento anterior: repite solo las llamadas fallidas.")
    ap.add_argument("--espera-429", type=int, default=60, help="Segundos de espera ante 429/503 antes de reintentar.")
    args = ap.parse_args()

    global ESPERA_429
    ESPERA_429 = args.espera_429
    password = getpass.getpass(f"Contraseña de {args.usuario}: ")
    with httpx.Client(base_url=args.base_url, timeout=180) as cliente:
        login(cliente, args.usuario, password)
        if args.completar:
            # Repite solo las llamadas que fallaron en un experimento anterior.
            previo = json.loads(Path(args.completar).read_text(encoding="utf-8"))
            filas = previo["llamadas"]
            pendientes = [i for i, f in enumerate(filas) if f["status"] != 200]
            print(f"Completando {len(pendientes)} llamada(s) fallida(s) de {args.completar}")
            for n, i in enumerate(pendientes, 1):
                f = filas[i]
                print(f"[{n}/{len(pendientes)}] {f['pregunta_id']} · {f['tecnica']} …", flush=True)
                res = llamar(cliente, f["pregunta"], f["tecnica"])
                historial = f.get("intentos_fallidos", []) + [
                    {k: f.get(k) for k in ("status", "message", "timestamp") if f.get(k) is not None}]
                caso = {"esperados": f["esperados"], "dato_clave": f.get("dato_clave")}
                base = {k: f[k] for k in ("pregunta_id", "pregunta", "tecnica", "esperados", "dato_clave")}
                filas[i] = {**base, **res, "intentos_fallidos": historial}
                filas[i]["cobertura"] = cobertura(res.get("respuesta", ""), caso) if res["status"] == 200 else None
                print(f"    HTTP {res['status']} · tokens {res.get('uso', {}).get('total_tokens', '-')} · "
                      f"{res.get('latencia_ms', '-')} ms · cobertura {filas[i]['cobertura']}")
                if n < len(pendientes):
                    time.sleep(args.pausa)
        else:
            casos = preguntas_con_referencia(cliente)
            filas = []
            for caso in casos:
                for tecnica in TECNICAS:
                    print(f"[{len(filas) + 1}/{len(casos) * len(TECNICAS)}] {caso['id']} · {tecnica} …", flush=True)
                    res = llamar(cliente, caso["pregunta"], tecnica)
                    fila = {"pregunta_id": caso["id"], "pregunta": caso["pregunta"], "tecnica": tecnica,
                            "esperados": caso["esperados"], "dato_clave": caso.get("dato_clave"), **res}
                    fila["cobertura"] = cobertura(res.get("respuesta", ""), caso) if res["status"] == 200 else None
                    print(f"    HTTP {res['status']} · tokens {res.get('uso', {}).get('total_tokens', '-')} · "
                          f"{res.get('latencia_ms', '-')} ms · cobertura {fila['cobertura']}")
                    filas.append(fila)
                    time.sleep(args.pausa)

    ok = [f for f in filas if f["status"] == 200]
    promedios = {}
    for t in TECNICAS:
        g = [f for f in ok if f["tecnica"] == t]
        if not g:
            continue
        cobs = [f["cobertura"] for f in g if f["cobertura"] is not None]
        promedios[t] = {
            "input": statistics.mean(f["uso"]["input_tokens"] for f in g),
            "output": statistics.mean(f["uso"]["output_tokens"] for f in g),
            "thinking": statistics.mean(f["uso"]["thinking_tokens"] for f in g),
            "latencia": statistics.mean(f["latencia_ms"] for f in g),
            "costo": statistics.mean(f["costo_estimado_usd"] for f in g),
            "cobertura": round(statistics.mean(cobs), 1) if cobs else None,
        }
    proy = proyeccion(promedios, args.usuarios, args.consultas_dia, args.dias_mes)

    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = Path("resultados")
    salida.mkdir(exist_ok=True)
    meta = {"fecha": fecha, "modelo": ok[0]["modelo"] if ok else settings.GEMINI_MODEL, "usuarios": args.usuarios,
            "consultas_dia": args.consultas_dia, "dias_mes": args.dias_mes}
    (salida / f"experimento_{fecha}.json").write_text(
        json.dumps({"meta": meta, "llamadas": filas, "promedios": promedios, "proyeccion": proy},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    escribir_markdown(salida / f"experimento_{fecha}.md", meta, filas, promedios, proy)
    print(f"\nLlamadas exitosas: {len(ok)}/{len(filas)}")
    print(f"Archivos: resultados/experimento_{fecha}.json y .md")


if __name__ == "__main__":
    main()
