FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.11 python3.11-dev python3-pip \
    build-essential gcc g++ \
    libpq-dev libffi-dev libssl-dev \
    libhdf5-dev \
    curl wget git \
    && rm -rf /var/lib/apt/lists/*

# Set python3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create artifact directory
RUN mkdir -p /app/artifacts/models /app/artifacts/reports /app/artifacts/exports

# Expose port
EXPOSE 8000

# Start command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop", "--http", "httptools"]
