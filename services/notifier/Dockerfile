FROM python:3.11-slim
WORKDIR /app
COPY main.py /app/main.py
RUN pip install --no-cache-dir fastapi uvicorn requests python-telegram-bot==20.6
EXPOSE 8082
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8082"]
