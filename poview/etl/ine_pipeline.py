import logging
import sys
import time

from csv_loader import descargar_csv, parse_csv
from datasets import DATASETS
from emitter import emitir_metricas
from transformer import transformar_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("ine_pipeline")


def run_etl() -> None:
    inicio = time.time()
    total_puntos = 0
    total_tablas = 0
    errores = 0

    for categoria, grupos in DATASETS.items():
        for subgrupo, tablas in grupos.items():
            for tabla in tablas:
                total_tablas += 1
                try:
                    csv_text = descargar_csv(tabla)
                    rows = parse_csv(csv_text)
                    registros = transformar_rows(subgrupo, rows)
                    escritos = emitir_metricas(
                        categoria,
                        subgrupo,
                        f"{subgrupo}_{tabla}",
                        registros,
                    )
                    total_puntos += escritos
                except Exception as exc:
                    errores += 1
                    logger.error("tabla=%s msg=%s", tabla, exc)

    dur = time.time() - inicio
    logger.info(
        "ETL terminado tablas=%d puntos=%d errores=%d duracion=%.1fs",
        total_tablas, total_puntos, errores, dur,
    )


if __name__ == "__main__":
    run_etl()