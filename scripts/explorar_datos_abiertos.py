"""Explora los datasets de datos.gov.co configurados y verifica la normalización.

Muestra, para INVIMA CUM y DANE DIVIPOLA:
  * los nombres de columna REALES que entrega la API (Socrata cambia nombres entre versiones);
  * el % de registros normalizados que quedan con valor en cada campo canónico;
  * un registro de ejemplo.

Si algún campo importante queda en 0 %, agregue el nombre real al diccionario
CAMPOS_CUM / CAMPOS_DIVIPOLA de app/infrastructure/datos_abiertos/normalizacion.py
o cambie DATASET_CUM_ID / DATASET_DIVIPOLA_ID en el .env.

Uso:
    python -m scripts.explorar_datos_abiertos
    python -m scripts.explorar_datos_abiertos --termino losartan
"""
import argparse
import json

from app.infrastructure.config import settings
from app.infrastructure.datos_abiertos.normalizacion import cobertura_campos, normalizar_cum, normalizar_municipio
from app.infrastructure.datos_abiertos.socrata import ClienteSocrata, ErrorFuenteExterna


def explorar(cliente: ClienteSocrata, titulo: str, dataset: str, params: dict, normalizador) -> None:
    print(f"\n=== {titulo} · dataset {dataset} ===")
    try:
        crudos = cliente.consultar(dataset, params)
    except ErrorFuenteExterna as exc:
        print(f"  ERROR: {exc} (status={exc.status})")
        return
    print(f"  Registros recibidos: {len(crudos)}")
    if not crudos:
        return
    columnas = sorted({k for r in crudos for k in r})
    print(f"  Columnas reales ({len(columnas)}): {', '.join(columnas)}")
    normalizados = [normalizador(r) for r in crudos]
    print("  Cobertura de campos normalizados:")
    for campo, pct in cobertura_campos(normalizados).items():
        marca = "  <-- revisar" if pct == 0 else ""
        print(f"    {campo:<28} {pct:6.1f} %{marca}")
    print("  Ejemplo normalizado:")
    print("   ", json.dumps(normalizados[0], ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Explorar datasets de datos.gov.co usados por SITRAL")
    parser.add_argument("--termino", default="acetaminofen", help="Término de búsqueda para el CUM")
    args = parser.parse_args()
    cliente = ClienteSocrata(settings.DATOS_ABIERTOS_BASE_URL, settings.SOCRATA_APP_TOKEN,
                             settings.OPENDATA_TIMEOUT_SECONDS)
    explorar(cliente, "INVIMA - Código Único de Medicamentos", settings.DATASET_CUM_ID,
             {"$q": args.termino, "$limit": 20}, normalizar_cum)
    explorar(cliente, "DANE - DIVIPOLA", settings.DATASET_DIVIPOLA_ID, {"$limit": 50}, normalizar_municipio)


if __name__ == "__main__":
    main()
