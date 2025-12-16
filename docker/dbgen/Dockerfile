# -----------------------------------------------------------------------------
# Stage 1: Runtime (Python)
# -----------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /data

# Install the tpchgen-cli tool
# This usually installs an executable named 'tpchgen' or 'tpchgen-cli' to /usr/local/bin
RUN pip install --no-cache-dir tpchgen-cli

# Set entrypoint to shell so we can run the chown commands in docker-compose
ENTRYPOINT ["/bin/sh"]