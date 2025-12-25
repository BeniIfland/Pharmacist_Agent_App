# Use a small, official Python image
FROM python:3.11-slim

# Prevents Python from writing .pyc files and buffers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Workdir inside the container
WORKDIR /app

# Install dependencies first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY . .

# # Expose FastAPI port
# EXPOSE 8000

# # Start the server
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

#Expose GUI (Gradio) port
EXPOSE 7860
# Start the server
CMD ["python", "-m", "app.ui"]