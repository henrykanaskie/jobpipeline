FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY jobpipeline ./jobpipeline
RUN pip install --no-cache-dir .
COPY db ./db
COPY config ./config
ENV PYTHONUNBUFFERED=1
