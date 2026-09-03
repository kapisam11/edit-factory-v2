FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[web]"

RUN mkdir -p /app/output /app/uploads /app/knowledge_base_v2

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "wsgi:app"]
