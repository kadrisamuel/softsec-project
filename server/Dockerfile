# Server image: minimal Flask + Gunicorn
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
 && rm -rf /var/lib/apt/lists/*

# Copy project description
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app

# Install runtime dependencies
RUN pip install --no-cache-dir -e .

# Copy sources after dependencies installation
COPY wsgi.py /app/wsgi.py
COPY flag /app/flag
COPY entrypoint.sh /app/entrypoint.sh

EXPOSE 5000

# Default command runs the web server
CMD ["./entrypoint.sh"]
