
# Use a lightweight, amd64-compatible Python image
FROM --platform=linux/amd64 python:3.10-slim

# Set the working directory
WORKDIR /app

COPY requirements.txt .
# Install minimal runtime deps
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Ensure output directory exists
RUN mkdir -p /app/output

# Entrypoint: process all PDFs in /app/input and save results to /app/output
CMD ["python", "1A.py", "/app/input", "-o", "/app/output"]