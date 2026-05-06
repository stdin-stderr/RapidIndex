FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src/ src/
COPY *.py .

RUN uv pip install --system --no-cache .

ENV PYTHONPATH=/app
