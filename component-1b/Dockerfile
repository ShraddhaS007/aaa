# Use a lightweight, amd64-compatible Python image 
FROM --platform=linux/amd64 python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy local wheels for offline installation and requirements
COPY wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# Copy the rest of the application code
COPY . .

# Ensure output directory exists
RUN mkdir -p /app/output

# Entrypoint: process input to output
CMD ["python", "1B.py", "/app/input", "/app/output"]