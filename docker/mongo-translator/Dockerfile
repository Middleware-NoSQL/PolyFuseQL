# Use a specific, stable version of Python
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install git and curl for healthchecks
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Clone the translator repository into the container
RUN git clone https://github.com/Middleware-NoSQL/Traductor-SQL-NOSQL.git .

# Set the working directory to the Backend folder
WORKDIR /app/Backend

# Create the .env file for fallback configuration
RUN echo '# This .env file is created for transparency and as a fallback.' > .env && \
    echo '# In the docker-compose setup, these values are overridden by the environment section.' >> .env && \
    echo 'MONGO_URI=mongodb://root:example@mongodb:27017/' >> .env && \
    echo 'DATABASE_NAME=mydatabase' >> .env

# Verify the .env file was created correctly
RUN echo "--- Verifying .env file content ---" && cat .env && echo "--- End of .env file ---"

# Install Python dependencies, including gunicorn and python-dotenv
RUN pip install --no-cache-dir -r requirements.txt gunicorn python-dotenv

# Expose the port the application will run on
EXPOSE 5000

# Set the default command to run the application using Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "main:app"]

