FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 wheels are bundled; keep the image lean.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PORT=8000
EXPOSE 8000

# Shell form so ${PORT} is expanded at runtime (managed hosts inject it).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
