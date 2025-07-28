# Dockerfile to build the TPC-H dbgen utility from the ymatrix-data Git repository
FROM gcc:latest AS builder

# Set working directory
WORKDIR /usr/src/tpch

# Install git and patch
RUN apt-get update && apt-get install -y git patch

# Clone the TPC-H tools repository
RUN git clone https://github.com/ymatrix-data/TPC-H.git

# Navigate to the cloned repository
WORKDIR /usr/src/tpch/TPC-H

# Copy and apply the patch
# This assumes tpch_changes.patch is in the same directory as the Dockerfile
COPY tpch_changes.patch .
RUN git apply tpch_changes.patch

# Navigate to the dbgen compilation directory and build it
WORKDIR /usr/src/tpch/TPC-H/00_compile_tpch/dbgen
RUN make

# Final stage - a smaller image to reduce size
FROM debian:stable-slim
WORKDIR /usr/local/bin

# Copy the compiled dbgen binary and the required dists.dss file from the builder stage
COPY --from=builder /usr/src/tpch/TPC-H/00_compile_tpch/dbgen/dbgen .
COPY --from=builder /usr/src/tpch/TPC-H/00_compile_tpch/dbgen/dists.dss .

# The entrypoint is overridden by the docker-compose command
ENTRYPOINT ["./dbgen"]