# -------------------------------------------------------------
# Stage 1: Build & Dependency Installation
# -------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install poetry for dependency resolution
RUN pip install --no-cache-dir poetry

# Create isolated virtualenv for production dependencies
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY pyproject.toml poetry.lock* README.md /build/
COPY src /build/src

# Install only production dependencies into the isolated virtualenv
RUN poetry install --only main --no-interaction --no-ansi

# -------------------------------------------------------------
# Stage 2: Minimal Runtime Image
# -------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Install only git and ca-certificates needed for git operations
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy isolated virtual environment and application code from builder
COPY --from=builder /opt/venv /opt/venv
COPY src /app/src

# Configure environment to use the isolated virtualenv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Configure git safe directory for GitHub Actions workspace mounting
RUN git config --global --add safe.directory "*"

ENTRYPOINT ["python", "-m", "src.main"]
