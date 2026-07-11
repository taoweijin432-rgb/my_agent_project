FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1

WORKDIR /app

ARG INSTALLER=pip

COPY constraints.txt requirements.txt .
RUN python -m pip install --upgrade pip \
    && if [ "$INSTALLER" = "uv" ]; then \
        python -m pip install uv \
        && uv pip install --system --no-cache -r requirements.txt; \
    else \
        python -m pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app
COPY knowledge ./knowledge
COPY migrations ./migrations
COPY scripts ./scripts

RUN mkdir -p data/chroma logs .model_cache/huggingface \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

CMD ["sh", "-c", "python scripts/check_runtime_paths.py && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
