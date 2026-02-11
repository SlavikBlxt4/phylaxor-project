FROM python:3.11-slim
WORKDIR /app

RUN pip install fastapi uvicorn psycopg2-binary jinja2 python-multipart

COPY src /app/src
COPY templates /app/src/templates
COPY static /app/src/static
ENV PYTHONPATH=/app/src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8083"]
