# BrowseBias Research Server — Dockerfile
# Optimized for Hugging Face Spaces and standalone container deployments

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up user for Hugging Face Spaces security requirements (UID 1000)
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR $HOME/app

# Install Python requirements
COPY --chown=user requirements.txt $HOME/app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_sm

# Prepare optional persistent storage mount point for Hugging Face Spaces (/data)
USER root
RUN mkdir -p /data && chown -R user:user /data
USER user

# Copy application source code
COPY --chown=user . $HOME/app

# Hugging Face Spaces listens on port 7860
EXPOSE 7860

# Start BrowseBias server
CMD ["python", "server/app.py"]
