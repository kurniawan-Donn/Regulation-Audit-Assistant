# Audit Assistant — image untuk server tim.
# Jalankan lewat docker-compose.yml (data, hasil, dan cache disimpan di luar container).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY scripts/ ./scripts/

# Jalan sebagai pengguna biasa, bukan root.
RUN useradd --create-home --uid 1000 auditor \
    && mkdir -p data outputs cache uploads \
    && chown -R auditor:auditor /app
USER auditor

# HOST=0.0.0.0 di container WAJIB disertai APP_PASSWORD (server menolak start tanpa itu).
ENV AUDIT_ASSISTANT_INSTALL=docker \
    HOST=0.0.0.0 \
    PORT=8000 \
    DEBUG=false
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "app"]
