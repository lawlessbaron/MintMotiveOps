FROM python:3.11-slim

# psycopg2-binary needs libpq at runtime; build-essential/libpq-dev cover
# both the binary wheel case and a source-build fallback on odd platforms.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Uploaded images/docs live here. Mount a volume at this path (a Docker
# volume in docker-compose.yml, a Railway volume on Railway) so they survive
# rebuilds and redeploys.
RUN mkdir -p /app/app/static/uploads

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Shell form so $PORT (set by Railway and most hosts) is honoured; 8000 when
# it isn't set. --preload builds the app once before the workers fork, so the
# first-boot schema setup and the stock import run once, not once per worker.
CMD gunicorn --preload -w ${WEB_CONCURRENCY:-4} -b 0.0.0.0:${PORT:-8000} --timeout 300 --access-logfile - wsgi:app
