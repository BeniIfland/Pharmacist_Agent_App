# Use a small, official Python image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Gradio defaults (good for Docker)
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860

WORKDIR /app

# (Optional but recommended) system deps for common wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY . .

# (Optional) non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 7860
CMD ["python", "-m", "app.ui"]
