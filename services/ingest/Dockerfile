ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}
WORKDIR /app
COPY src /app/src
ENV PYTHONPATH=/app/src
RUN pip install --no-cache-dir fastapi uvicorn redis
EXPOSE 8080
CMD ["uvicorn","src.main:app","--host","0.0.0.0","--port","8080"]
