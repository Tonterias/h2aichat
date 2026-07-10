# H2AI Chat — imagen de la app (FASE 40.2). Se usa con docker-compose.yml (app + Ollama).
FROM python:3.13-slim

WORKDIR /app

# Dependencias primero (mejor cacheo de capas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El código de la app
COPY . .

EXPOSE 8000
ENV HUMANIA_ENV=dev

# Arranca el servidor (el frontend se sirve en http://localhost:8000)
CMD ["python", "-m", "uvicorn", "execution.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
