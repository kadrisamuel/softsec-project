# Server image: minimal Flask + Gunicorn
FROM python:3.12-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy public keys
COPY keys/Public-keys-20260914/*.asc /app/pub-keys/

# Copy the package and install runtime dependencies
COPY requirements.txt /app/requirements.txt
COPY app /app/app
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.py /app/entrypoint.py

# Initialize second flag
COPY --chmod=600 flag /app/flag
RUN --mount=type=secret,id=flag_2 sed -i "s/REPLACE_THIS_STRING_WITH_SERVER_FLAG/$(cat /run/secrets/flag_2)/g" /app/flag

# Create and switch to non-root user pyu
# Let pyu write to /app/storage only
RUN groupadd -g 1000 pyugroup && \
    useradd --system --no-create-home -u 1000 -g pyugroup pyu
RUN mkdir -p /app/storage \
    && chown -R pyu:pyugroup /app/storage \
    && chmod 750 /app/storage
USER pyu

EXPOSE 5000

# Default command runs the web server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "entrypoint:app"]
