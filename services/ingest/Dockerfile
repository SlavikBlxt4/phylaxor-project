FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn redis
EXPOSE 8080
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
