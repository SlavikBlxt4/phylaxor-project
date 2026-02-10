FROM python:3.11-slim
WORKDIR /app
COPY src /app/src
ENV PYTHONPATH=/app/src
RUN pip install --no-cache-dir redis requests psycopg2-binary
CMD ["python","/app/src/worker.py"]
