FROM python:3.12-slim AS builder

WORKDIR /build
COPY inference/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY inference/ ./inference/
# The one image that carries the model. The backend deliberately does not.
COPY ml/model.joblib ./inference/model.joblib

USER appuser

CMD ["uvicorn", "inference.main:app", "--host", "0.0.0.0", "--port", "8001"]
