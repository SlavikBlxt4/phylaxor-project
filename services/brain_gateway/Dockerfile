FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src /app/src

# Set python path
ENV PYTHONPATH=/app/src

# Default environment variables
ENV CONTRACTS_DIR=/app/contracts
ENV PORT=8000

# Create a volume point for contracts (or copy them if available in build context)
# In production, we might COPY them. For dev, we might mount.
# Here we just ensure the dir exists.
RUN mkdir -p /app/contracts

# Run command
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
