FROM python:3.11-slim

# Install system dependencies (needed for PDF rendering/parsing libraries if any compiled C dependencies exist)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy python dependencies list and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/app/ /app/app/
COPY backend/alembic/ /app/alembic/
COPY backend/alembic.ini /app/

# Copy frontend static files into the container workspace
COPY frontend/ /app/frontend/

# Expose port
EXPOSE 8000

# Set running command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
