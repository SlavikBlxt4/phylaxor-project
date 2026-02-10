FROM python:3.11-slim
WORKDIR /app

RUN pip install requests python-telegram-bot==13.14 psycopg2-binary==2.9.9

COPY src /app/src
ENV PYTHONPATH=/app/src

CMD ["python", "src/main.py"]
