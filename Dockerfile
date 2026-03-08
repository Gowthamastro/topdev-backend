FROM python:3.11-slim

WORKDIR /app

# Install system deps for weasyprint, psycopg2 etc
RUN set -eux; \
    apt-get update; \
    GDK_PIXBUF_PKG="libgdk-pixbuf2.0-0"; \
    if apt-cache show libgdk-pixbuf-xlib-2.0-0 >/dev/null 2>&1; then \
      GDK_PIXBUF_PKG="libgdk-pixbuf-xlib-2.0-0"; \
    fi; \
    apt-get install -y --no-install-recommends \
      curl \
      gcc libpq-dev libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
      "$GDK_PIXBUF_PKG" \
      libffi-dev shared-mime-info; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
