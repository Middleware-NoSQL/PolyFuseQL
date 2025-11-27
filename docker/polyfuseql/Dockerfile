# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Set environment variables for build
# POETRY_VIRTUALENVS_IN_PROJECT=true ensures the venv is created in the local directory,
# making it easy to copy to the next stage.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_HOME="/opt/poetry"

# Add Poetry to PATH
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Install system dependencies required for building Python packages
# curl is needed to download poetry; build-essential handles C-extensions if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Copy only dependency definition files first to leverage Docker cache
COPY pyproject.toml poetry.lock ./

# Install dependencies (production only, no dev deps)
# --no-root skips installing the project itself, speeding up the build when code changes
RUN poetry install --only main --no-root

# -----------------------------------------------------------------------------
# Stage 2: Runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Activate the virtual environment by adding it to the front of PATH
    PATH="/app/.venv/bin:$PATH" \
    # Add src to PYTHONPATH so python can find the 'polyfuseql' package without installing it
    PYTHONPATH="/app/src"

WORKDIR /app

# Create a non-root user for security
RUN groupadd -r polyuser && useradd -r -g polyuser polyuser

# Install minimal runtime system dependencies (e.g. for healthchecks) if necessary
# RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=polyuser:polyuser /app/.venv /app/.venv

# Copy the actual application source code
COPY --chown=polyuser:polyuser src /app/src

# Switch to non-root user
USER polyuser

# Expose the application port
EXPOSE 8000

# Run the application using Uvicorn
# The path matches src/polyfuseql/app/main.py
CMD ["uvicorn", "polyfuseql.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# You must run these commands from the **project root directory** (`PolyFuseQL/`) so Docker can access `pyproject.toml`
# and the `src/` folder.

# docker build -t polyfuseql:latest -f docker/polyfuseql/Dockerfile .

# Basic run
# docker run -d -p 8000:8000 --name polyfuseql_app polyfuseql:latest

# Run with environment variables from your .env file
# docker run -d -p 8000:8000 --env-file .env --name polyfuseql_app polyfuseql:latest