#!/bin/bash
set -euo pipefail

# Frecuencia de ejecución. Los datos del INE son anuales, así que por defecto
# se ejecuta una vez al día (madrugada). Cambia ETL_CRON en el entorno si
# necesitas otra cadencia.
ETL_CRON="${ETL_CRON:-0 4 * * *}"

# Pasar el entorno al cron (cron arranca sin nuestras env vars)
printenv \
  | grep -E '^(INFLUXDB_|ETL_)' \
  > /etc/environment

# Registrar el cron
echo "${ETL_CRON} root cd /etl && /usr/local/bin/python3 /etl/ine_pipeline.py >> /proc/1/fd/1 2>> /proc/1/fd/2" \
  > /etc/cron.d/ine_pipeline
chmod 0644 /etc/cron.d/ine_pipeline
crontab /etc/cron.d/ine_pipeline

# Ejecutar una vez al arrancar (si RUN_ON_START != "0")
if [ "${RUN_ON_START:-1}" = "1" ]; then
  echo "[run.sh] Ejecutando ETL inicial..."
  cd /etl && python3 /etl/ine_pipeline.py || echo "[run.sh] ETL inicial fallido (continuamos con cron)"
fi

# Cron en foreground (PID 1)
echo "[run.sh] Lanzando cron en foreground (cadencia: ${ETL_CRON})"
exec cron -f