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

# Uploaded images/docs live here; mounted as a volume in docker-compose.yml
# so they survive container rebuilds.
RUN mkdir -p /app/app/static/uploads

EXPOSE 8000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "wsgi:app"]
