FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
# Pre-computed model predictions consumed by app.seed at startup.
# model.joblib is only needed offline (train/generate scripts), not at runtime.
COPY ml/predictions.json ./ml/predictions.json

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
