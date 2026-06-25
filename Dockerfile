# Production-ready slim Dockerfile for the COVID-19 Data Tracker
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer outputs immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5001
ENV FLASK_ENV=production

WORKDIR /app

# Install system dependencies (needed for compiling certain python packages if necessary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies first to take advantage of Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create raw/processed data storage directory inside container
RUN mkdir -p data/raw data/processed data/backups

# Expose app port
EXPOSE 5001

# Command to run the application using Gunicorn and the production config
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
