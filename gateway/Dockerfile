FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8080

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 gateway \
    && mkdir -p /var/lib/hydraflow-gateway/metadata \
        /var/lib/hydraflow-gateway/bodies \
    && chmod 700 /var/lib/hydraflow-gateway/metadata \
        /var/lib/hydraflow-gateway/bodies \
    && chown -R gateway:gateway /var/lib/hydraflow-gateway

USER gateway
WORKDIR /var/lib/hydraflow-gateway

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]

CMD ["python", "-m", "hydraflow_gateway"]
