FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AIVF_STATE_DIR=/app/state

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY ai_video_factory ./ai_video_factory
COPY tools ./tools
COPY templates ./templates
COPY static ./static
COPY dashboard_auth.py cli.py cli_v2.py web_app_v2.py wsgi.py ./

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir '.[web]'

RUN groupadd --system aivf \
    && useradd --system --gid aivf --create-home aivf \
    && mkdir -p /app/output /app/uploads /app/knowledge_base_v2 /app/state \
    && chown -R aivf:aivf /app

USER aivf
EXPOSE 5000

CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:5000", "--timeout", "0", "wsgi:app"]
