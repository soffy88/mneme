FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy and install platform packages (obase/oprim/oskill/omodul)
# Build context is the parent directory (projects/)
COPY platform/3O/obase /app/platform/obase
COPY platform/3O/oprim /app/platform/oprim
COPY platform/3O/oskill /app/platform/oskill
COPY platform/3O/omodul /app/platform/omodul

RUN uv pip install --system \
    /app/platform/obase \
    /app/platform/oprim \
    /app/platform/oskill \
    /app/platform/omodul
# obase  @ v0.15.9
# oprim  @ v3.10.10
# oskill @ v3.25.2
# omodul @ v1.29.2

# Copy mneme dependency files and install base deps
COPY mneme/requirements.txt .
COPY mneme/pyproject.toml .
RUN uv pip install --system -r requirements.txt

# Copy mneme project files
COPY mneme/ .

# Expose API port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "services.main:app", "--host", "0.0.0.0", "--port", "8000"]
