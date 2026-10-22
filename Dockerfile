FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/BitNike/immobilienverwalter"

# Systembibliotheken für WeasyPrint (PDF) und klassische Schriften für die Abrechnung
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NK_DATA=/data \
    NK_DOKUMENTE=/dokumente

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
RUN useradd --system --uid 1000 nk && mkdir -p /data /dokumente && chown nk /data /dokumente
USER nk

VOLUME ["/data", "/dokumente"]
EXPOSE 8080
# Gesundheitscheck: Docker (und Dockge, Portainer …) zeigen „healthy“, solange App und Datenbank antworten
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "120", "main:app"]
