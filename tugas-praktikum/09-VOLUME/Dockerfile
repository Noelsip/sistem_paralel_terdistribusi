FROM python:3.10-alpine

RUN mkdir -p /app /data/logs

WORKDIR /app
COPY app.py .

# Format Volume
VOLUME /data/logs

CMD ["python", "app.py"]
