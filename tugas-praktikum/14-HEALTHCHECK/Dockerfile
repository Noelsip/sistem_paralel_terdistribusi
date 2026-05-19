FROM python:3.10-alpine

RUN apk --no-cache add curl

RUN mkdir /app
WORKDIR /app
COPY server.py .

EXPOSE 8000

HEALTHCHECK --interval=5s --start-period=5s CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "server.py"]
