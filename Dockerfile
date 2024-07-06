# Dockerfile
FROM python:3.9

# Set environment variables
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN apt-get update \
    && apt-get install -y postgresql-client \
    && pip install -r requirements.txt

# Copy project
COPY . /app/
