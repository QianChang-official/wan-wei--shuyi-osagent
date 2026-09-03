# syntax=docker/dockerfile:1.7
FROM node:22.23.2-bookworm-slim AS frontend-builder

WORKDIR /build/frontend/console-vue
COPY frontend/console-vue/package.json frontend/console-vue/package-lock.json ./
RUN npm ci
COPY frontend/console-vue/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ARG APP_VERSION=v0.11.0-wanshu
LABEL org.opencontainers.image.title="Wanwei Shuyi MemoryOps Autopilot"       org.opencontainers.image.description="Single-node OSAgent memory governance and evaluation platform"       org.opencontainers.image.source="https://github.com/QianChang-official/wan-wei--shuyi-osagent"       org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PYTHONPATH=/app/backend     WANWEI_PRODUCTION=1     WANWEI_MEMORY_DB=/data/memory.db     WANWEI_PLATFORM_DIR=/data/platform

RUN addgroup --system --gid 10001 wanwei     && adduser --system --uid 10001 --ingroup wanwei --home /nonexistent --no-create-home wanwei

WORKDIR /app
ARG PIP_VERSION=26.2.0
COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --upgrade "pip==${PIP_VERSION}"     && python -m pip install --no-cache-dir --disable-pip-version-check -r /app/backend/requirements.txt

COPY backend /app/backend
# 只 COPY CI 契约要求的单次评测产物,不带整个 reports/ 历史目录(2.0MB 过程产物不该进生产镜像)
COPY reports/production_memory_eval_metrics.json /app/reports/production_memory_eval_metrics.json
COPY --from=frontend-builder /build/frontend/console-vue/dist /app/frontend/console-vue/dist

RUN mkdir -p /data /data/platform && chown -R wanwei:wanwei /data

USER 10001:10001
EXPOSE 8010
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=4   CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health/ready', timeout=2).read()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8010", "--no-proxy-headers"]
