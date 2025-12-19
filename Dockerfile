FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt /app/requirements.txt
COPY api/requirements.txt /app/api_requirements.txt

# Install Python deps (merge both)
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r api_requirements.txt

# Copy source code
COPY . /app

# Environment
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 8000

# Run FastAPI
# We run uvicorn on api.main:app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
