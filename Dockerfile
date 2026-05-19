FROM python:3.11-slim

WORKDIR /app

COPY docker_requirements.txt .
RUN pip install --no-cache-dir -r docker_requirements.txt

COPY libs/    ./libs/
COPY runtime/ ./runtime/

# Auth/secrets.json must be mounted at runtime — never bake credentials into the image
VOLUME ["/app/libs/Auth"]

ENV POLL_INTERVAL=300
ENV PORT=5500
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""

EXPOSE 5500

HEALTHCHECK --interval=60s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5500/healthz')"

CMD ["python", "runtime/middleware.py"]
