FROM python:3.11-slim

WORKDIR /app

# System deps for undetected-chromedriver / Selenium
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir flask supabase

COPY . .

# Auth/secrets.json must be mounted at runtime — never bake credentials into the image
VOLUME ["/app/Auth"]

ENV PUSH_URL=""
ENV POLL_INTERVAL=300
ENV PORT=5500
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""

EXPOSE 5500

HEALTHCHECK --interval=60s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5500/healthz')"

CMD ["python", "middleware.py"]
