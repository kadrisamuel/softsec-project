# Server image: minimal Flask + Gunicorn
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the package and install runtime dependencies
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
RUN pip install --no-cache-dir -e .

COPY entrypoint.py /app/entrypoint.py

# Initialize second flag
COPY flag /app/flag
RUN --mount=type=secret,id=flag_2 sed -i "s/REPLACE_THIS_STRING_WITH_SERVER_FLAG/$(cat /run/secrets/flag_2)/g" /app/flag
RUN chmod 400 /app/flag

# Create and switch to non-root user
RUN adduser --system --no-create-home pyu
USER pyu

EXPOSE 5000

# Default command runs the web server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "entrypoint:app"]
