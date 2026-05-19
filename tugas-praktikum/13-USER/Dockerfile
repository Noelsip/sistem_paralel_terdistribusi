FROM python:3.10-alpine

RUN mkdir /app

RUN addgroup -S noelgroup
RUN adduser -S -D -h /app noeluser noelgroup
RUN chown -R noeluser:noelgroup /app

USER noeluser

WORKDIR /app
COPY app.py .

EXPOSE 8080

CMD ["python", "app.py"]
