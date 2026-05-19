FROM python:3.10-alpine

ENV NAMA="Noel"
ENV PORT_APLIKASI=8080

RUN mkdir /app
WORKDIR /app
COPY main.py .

EXPOSE ${PORT_APLIKASI}

CMD ["python", "main.py"]
