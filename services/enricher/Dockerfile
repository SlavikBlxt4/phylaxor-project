FROM python:3.11-slim
WORKDIR /app
COPY worker.py /app/worker.py
RUN pip install --no-cache-dir redis
CMD ["python","/app/worker.py"]
