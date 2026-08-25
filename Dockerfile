# Use an official Python runtime as a parent image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Tesseract OCR for scanned document text extraction (optional checks)
# WeasyPrint needs Pango/Cairo for HTML→PDF appraisal packs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-amh \
    poppler-utils \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install any needed packages specified in requirements.txt
COPY requirements.txt /app/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --default-timeout=120 --retries=10 -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app/

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Dev default: runserver. Production / on-prem: USE_GUNICORN=1 (migrate + collectstatic + gunicorn).
COPY scripts/docker_entrypoint.sh /app/scripts/docker_entrypoint.sh
RUN chmod +x /app/scripts/docker_entrypoint.sh
CMD ["sh", "-c", "if [ \"${USE_GUNICORN:-0}\" = \"1\" ]; then exec /app/scripts/docker_entrypoint.sh; else exec python manage.py runserver 0.0.0.0:8000; fi"]

# Budget based loans based on loan category

# Date round from to