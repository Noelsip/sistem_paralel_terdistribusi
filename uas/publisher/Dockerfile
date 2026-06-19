FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY publisher.py .

RUN useradd --create-home --uid 10002 appuser \
    && chown -R appuser:appuser /srv
USER appuser

CMD ["python", "publisher.py"]
