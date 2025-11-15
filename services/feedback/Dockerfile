FROM python:3.11-slim
WORKDIR /app

RUN pip install fastapi uvicorn psycopg2-binary jinja2 python-multipart

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8083"]
