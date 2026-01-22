FROM python:3.11-slim
WORKDIR /app
COPY worker.py rules.py history_score.py logger.py /app/
RUN pip install --no-cache-dir redis requests psycopg2-binary
CMD ["python","/app/worker.py"]
