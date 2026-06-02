FROM python:3.11-slim

WORKDIR /app

COPY docker_requirements.txt .
RUN pip install --no-cache-dir -r docker_requirements.txt

COPY pyproject.toml ./
COPY libs/    ./libs/
COPY runtime/ ./runtime/

# Install libs/* as top-level Python packages so `from Auth.fcm_receiver import ...`
# works without sys.path hacks. --no-deps because docker_requirements.txt already
# covers runtime dependencies.
RUN pip install --no-cache-dir --no-deps .

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser

# Auth/secrets.json must be mounted at runtime — never bake credentials into the image
VOLUME ["/app/libs/Auth"]

# Unbuffered stdout/stderr so the polling loop's print()s ([poll], [mqtt] published
# N, [fetch] timeout ...) reach Fly logs in real time instead of being stuck in
# Python's block buffer — without this the pipeline is effectively unobservable.
ENV PYTHONUNBUFFERED=1
ENV POLL_INTERVAL=300
ENV LOCATION_BATCH_SIZE=8
ENV LOCATION_BATCH_DELAY=2.0
ENV PORT=5500
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""

EXPOSE 5500

HEALTHCHECK --interval=60s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5500/healthz')"

CMD ["gunicorn", "--chdir", "runtime", "--bind", "[::]:5500", "--workers", "1", "--threads", "4", "middleware:app"]
