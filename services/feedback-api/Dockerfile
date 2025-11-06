FROM python:3.11-slim
WORKDIR .

RUN pip install fastapi uvicorn psycopg2-binary

COPY app .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8083"]
