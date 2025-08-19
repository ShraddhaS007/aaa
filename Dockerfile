FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app

# Copy components, orchestrator, and local wheels (for offline install)
COPY wheels /wheels
COPY component-1a ./component-1a
COPY component-1b ./component-1b
COPY orchestrator.py ./orchestrator.py

# Install minimal runtime dependencies from local wheels (no network)
RUN pip install --no-cache-dir --no-index --find-links=/wheels PyMuPDF==1.24.10

# Prepare output directory
RUN mkdir -p /app/output

# Default entrypoint runs the orchestrator to perform both steps
CMD ["python", "orchestrator.py"]

