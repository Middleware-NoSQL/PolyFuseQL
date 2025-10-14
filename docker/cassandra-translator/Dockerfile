# --- STAGE 1: Build Environment ---
# This stage will clone the repository, install dependencies, and build all microservices.
FROM node:20-alpine AS builder

# Install git, which is required to clone the repository
RUN apk add --no-cache git

# Set the working directory
WORKDIR /app

# Clone the repository that contains all microservices
# Note: Using --depth 1 for a faster, shallow clone
RUN git clone --depth 1 https://github.com/andr3slelouch/SQL-to-CQL.git .

# --- Build Cassandra Translator ---
WORKDIR /app/translate-service
RUN npm install
RUN npm run build


# --- STAGE 2: Production Environment ---
# This stage creates the final, lightweight image for the cassandra-translator-api
FROM node:20-alpine

WORKDIR /app

# Copy only the necessary files for the cassandra-translator from the 'builder' stage
COPY --from=builder /app/translate-service/package*.json ./
COPY --from=builder /app/translate-service/node_modules ./node_modules
COPY --from=builder /app/translate-service/dist ./dist

# Expose the port the application will run on
EXPOSE 3000

# The command to run when the container starts
CMD [ "npm", "run", "start:prod" ]

