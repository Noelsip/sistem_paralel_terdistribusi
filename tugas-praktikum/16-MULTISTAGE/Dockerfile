# BUILDER
FROM python:3.10-alpine AS builder

WORKDIR /app

RUN python -m venv /app/venv
RUN /app/venv/bin/pip install --no-cache-dir requests

# FINAL IMAGE
FROM python:3.10-alpine

WORKDIR /app

COPY --from=builder /app/venv /app/venv
COPY app.py .

ENV PATH="/app/venv/bin:$PATH"

CMD ["python", "app.py"]
