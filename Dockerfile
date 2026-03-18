# Bright Staffing Job Refresh Bot
# Multi-stage build for smaller final image

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Production stage
FROM python:3.11-slim AS production

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Create directories
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R appuser:appuser /app

# Copy application code
COPY --chown=appuser:appuser src/ /app/src/
COPY --chown=appuser:appuser config/ /app/config/

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CONFIG_PATH=/app/config/config.yaml

# No HEALTHCHECK: this is a cron job that runs once and exits.
# A HEALTHCHECK can cause Railway to restart the container after exit.

# Default command: Railway cron triggers this once per week
# Use --limit 1 for testing, remove when ready for production
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["run"]