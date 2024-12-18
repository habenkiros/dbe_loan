# # Dockerfile

# # Use the official Python image from the Docker Hub.
# FROM python:3.10-slim

# # Set environment variables to prevent Python from writing .pyc files to disk
# ENV PYTHONDONTWRITEBYTECODE 1

# # Prevent Python from buffering stdout and stderr
# ENV PYTHONUNBUFFERED 1

# # Set the working directory in the container
# WORKDIR /app

# # Copy the requirements file to the working directory
# COPY requirements.txt /app/

# # Install the dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy the entire project to the working directory
# COPY . /app/

# # Run migrations and start the Django server
# CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]

# Use an official Python runtime as a parent image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Install any needed packages specified in requirements.txt
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app/

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run the development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
