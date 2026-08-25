FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy the repository dependency files and install base deps. The runtime uses the
# checked-in vendor/ 3O closure via PYTHONPATH; do not install a second platform
# source tree from a host-relative build context.
COPY pyproject.toml .
COPY uv.lock .
RUN uv export --frozen --no-dev --format requirements.txt \
        --no-emit-project --output-file /tmp/mneme-requirements.lock \
    && uv pip install --system -r /tmp/mneme-requirements.lock

# Copy mneme project files
COPY . .

# Keep the checked-in runtime closure first even when the image is run without
# docker-compose's environment override.
ENV PYTHONPATH=/app/vendor:/app:/app/packages/mneme-core:/app/packages/mneme-agent:/app/packages/event-schema

# Expose API port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "services.main:app", "--host", "0.0.0.0", "--port", "8000"]
