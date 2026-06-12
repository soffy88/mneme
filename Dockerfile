FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml .
COPY requirements.txt .

# Install dependencies into the system environment
RUN uv pip install --system -r requirements.txt .

# Copy project files
COPY . .

# Expose API port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "services.main:app", "--host", "0.0.0.0", "--port", "8000"]
