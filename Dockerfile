FROM python:3.12-slim AS builder

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

FROM python:3.12-slim AS runtime

WORKDIR /app

ARG GIT_SHA=unknown
ARG RELEASE_VERSION=dev
LABEL org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.version=$RELEASE_VERSION \
      org.opencontainers.image.source="https://github.com/mneme/mneme"

RUN groupadd --system mneme && useradd --system --gid mneme --home-dir /app mneme

# The builder needs a compiler for a few optional native wheels.  Copy only
# the resolved Python runtime into the final image; never ship the compiler,
# Perl, headers, or package-manager caches to production containers.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy mneme project files
COPY . .
RUN chown -R mneme:mneme /app
USER mneme

# Keep the checked-in runtime closure first even when the image is run without
# docker-compose's environment override.
ENV PYTHONPATH=/app/vendor:/app:/app/packages/mneme-core:/app/packages/mneme-agent:/app/packages/event-schema

# Expose API port
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Command to run the application
CMD ["uvicorn", "services.main:app", "--host", "0.0.0.0", "--port", "8000"]
