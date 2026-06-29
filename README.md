# Visor demográfico de la España Vaciada

Plataforma de **visualización de datos demográficos del INE** y un
**asistente conversacional** para estudiar la despoblación rural en España.
 Combina un mapa coroplético de los ~8.100 municipios con
capas temáticas (renta, trabajo, estudios y poblacion) y un chat que
responde con cifras reales del INE.

> Trabajo de Fin de Máster (TFM).

---

## 1. Arquitectura

Todo se levanta con **Docker Compose**. Servicios:

| Servicio   | Tecnología                     | Rol                                                        |
|------------|--------------------------------|------------------------------------------------------------|
| `proxy`    | Caddy 2                        | Única puerta de entrada. Termina HTTPS (`https://localhost`). |
| `app`      | Vite + Leaflet + ECharts       | Frontend (mapa, rankings, gráficas, chat).                 |
| `backend`  | FastAPI + LangGraph            | API REST `/api/*` y agente conversacional.                 |
| `ollama`   | Ollama (`qwen3:8b`)            | LLM local: clasifica intención y redacta texto.            |
| `influxdb` | InfluxDB 2.7                   | Almacena las series temporales del INE.                    |
| `etl`      | Python + cron                  | Descarga, transforma y carga los datos del INE.            |

**Principio de diseño:** el LLM solo entiende y redacta lenguaje natural. Toda
consulta a la base de datos es **Python determinista** (Flux); el modelo nunca
genera queries ni inventa cifras. Si InfluxDB no devuelve datos, el chat
responde con un texto fijo.

El flujo de datos del navegador es **dinámico**: el frontend pide cada valor a
`/api/*`, que consulta InfluxDB (y, para el chat, Ollama)..

---

## 2. Requisitos previos

- **Docker** y **Docker Compose v2** (`docker compose`, no `docker-compose`).
- ~8–10 GB de disco libres (imágenes + datos INE + modelo de Ollama).
- CPU con al menos 8 GB de RAM recomendado (el modelo `qwen3:8b` corre en CPU).
- Salida a Internet la primera vez (descarga de imágenes, datos del INE y modelo).

---

## 3. Configuración (`.env`)

En la raíz del proyecto debe existir un fichero **`.env`**. Plantilla mínima:

```dotenv
# InfluxDB (credenciales y bootstrap del bucket)
INFLUXDB_USERNAME=PoBadmin
INFLUXDB_PASSWORD=_password
INFLUXDB_ORG=tfm_rural
INFLUXDB_BUCKET=poblacion_municipios
INFLUXDB_TOKEN=_token_

# Ollama
OLLAMA_MODEL=qwen3:8b

# (opcional) Orígenes CORS permitidos por el backend
CORS_ORIGINS=https://localhost
```

> El `INFLUXDB_TOKEN` lo usan a la vez InfluxDB (para crear el admin token) y el
> backend (para autenticarse). Debe ser el **mismo** valor.

---

## 4. Arranque paso a paso

```bash
# 1) Construir y levantar todo el stack
docker compose up -d --build

# 2) Descargar los modelos de Ollama (NO se descargan solos). Tardan unos minutos.
#    - qwen3:8b   -> redacción del modo conversacional
#    - qwen3:1.7b -> clasificación rápida de intención (router del chat)
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull qwen3:1.7b

# 3) (Opcional) Forzar la carga inicial de datos del INE.
#    El servicio `etl` ya la ejecuta al arrancar (RUN_ON_START=1), pero puedes
#    relanzarla manualmente:
docker compose run --rm etl python3 /etl/ine_pipeline.py
```

La primera carga del ETL descarga decenas de tablas del INE y puede tardar
varios minutos. Sigue el progreso con:

```bash
docker compose logs -f etl
docker compose logs -f backend
```

Cuando el ETL haya terminado y el modelo esté descargado, abre:

> **https://localhost**

Caddy usa `tls internal`, así que la primera vez el navegador avisará de que la
CA no es de confianza. Acepta la excepción (o instala la CA raíz de Caddy) para
quitar el aviso.

---

## 5. Acceso desde un servidor remoto (VS Code Remote-SSH)

Si el stack corre en un servidor remoto (p. ej. `tauro`) y trabajas con
**VS Code Remote-SSH**, `localhost` en tu navegador apunta a *tu* máquina, no al
servidor. Reenvía los puertos del proxy en la pestaña **PORTS** de VS Code:

- **443** → para acceder a `https://localhost`
- **80**  → opcional (Caddy redirige 80→443)

Con esos puertos reenviados, `https://localhost` en tu navegador local llega al
proxy del servidor. No es necesario exponer 8000/3000/8086/11434: el proxy es la
única entrada.

---

## 6. Endpoints principales del backend

| Método | Ruta                         | Descripción                                 |
|--------|------------------------------|---------------------------------------------|
| GET    | `/api/comunidades`           | Lista de comunidades autónomas.             |
| GET    | `/api/provincias`            | Provincias (opcional `?comunidad=`).        |
| GET    | `/api/municipios`            | Municipios (filtros `provincia`, `q`, …).   |
| GET    | `/api/mapa?anio=&sexo=`      | Valores por municipio para el coroplético.  |
| GET    | `/api/stats?anio=`           | Indicadores agregados (total, deltas, …).   |
| GET    | `/api/ranking?anio=&sexo=`   | Ranking de municipios.                      |
| GET    | `/api/serie`                 | Serie temporal de población.                |
| GET    | `/api/capa/{modo}`           | Capas temáticas (`renta`, `trabajo`, `estudios`). |
| POST   | `/api/chat`                  | Chat. Cuerpo: `{ "message": str, "thread_id": str }`. |

Ejemplo de chat:

```bash
curl -sk https://localhost/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"¿Cuántos habitantes tiene Soria?","thread_id":"demo"}'
```

---

## 8. Operación y mantenimiento

**Parar sin perder datos:**

```bash
docker compose stop          # detiene los contenedores
docker compose down          # los elimina pero CONSERVA los volúmenes
```

> ⚠️ **Nunca** uses `docker compose down -v` salvo que quieras borrarlo todo:
> elimina los volúmenes, incluidos los **datos de InfluxDB** y el **modelo de
> Ollama** ya descargado (tendrías que recargar el ETL y volver a hacer `pull`).

**Reconstruir tras cambios de código:**

```bash
docker compose up -d --build backend     # solo el backend
docker compose up -d --build app         # solo el frontend
```

---
