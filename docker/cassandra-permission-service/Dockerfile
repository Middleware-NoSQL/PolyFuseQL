# STAGE 1: Build Environment
FROM node:20-alpine AS builder

# Install git, which is required to clone the repository
RUN apk add --no-cache git

# Set the working directory
WORKDIR /app

# Clone the repository that contains all microservices
# Note: Using --depth 1 for a faster, shallow clone
RUN git clone --depth 1 https://github.com/andr3slelouch/SQL-to-CQL.git .

# --- Build Cassandra Permission Service ---
WORKDIR /app/permission-service
RUN npm install
RUN npm run build

# --- STAGE 2: Production Environment ---
# This stage creates the final, lightweight image for the cassandra-translator-api
FROM node:20-alpine

WORKDIR /app

# Copy only the necessary files for the cassandra-translator from the 'builder' stage
COPY --from=builder /app/permission-service/package*.json ./
COPY --from=builder /app/permission-service/node_modules ./node_modules
COPY --from=builder /app/permission-service/dist ./dist

# The permission service runs on port 3002.
EXPOSE 3002

# The command to start the service in production mode.
CMD [ "npm", "run", "start:prod" ]
