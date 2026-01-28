# CSR Breaktime - Combined Bot + Dashboard
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Manila \
    BASE_DIR=/app \
    DATA_DIR=/app/data \
    RUN_MODE=both

# Set timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY breaktime_tracker_bot.py .
COPY bot_db_integration.py .
COPY start_all.py .
COPY run_dashboard.py .
COPY database/ ./database/
COPY dashboard/ ./dashboard/

# Create data directories
RUN mkdir -p /app/data /app/database

# Copy seed data (Excel files) for initial sync
COPY database/2026-01/ ./data/2026-01/

# Expose dashboard port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run combined services
CMD ["python", "-u", "start_all.py"]
