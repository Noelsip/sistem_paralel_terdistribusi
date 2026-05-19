FROM python:3.10-alpine

ARG nama_file=utama

RUN mkdir /app
WORKDIR /app
COPY main.py .

RUN mv main.py ${nama_file}.py

EXPOSE 8080

ENV nama_file=${nama_file}

CMD python ${nama_file}.py
