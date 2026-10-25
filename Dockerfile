FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --create-home --uid 10001 demoapp

COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY app ./app
USER demoapp
EXPOSE 8010
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
