FROM python:3.10-alpine

RUN mkdir /app
WORKDIR /app
COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
