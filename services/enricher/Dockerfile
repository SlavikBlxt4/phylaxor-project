# Imagen base mínima
FROM python:3.11-slim

# Ajustes de runtime (logs sin buffer, no .pyc)
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Dependencias de la app
WORKDIR /app
COPY src /app/src
ENV PYTHONPATH=/app/src
RUN pip install --no-cache-dir redis kubernetes

# Crear usuario/grupo sin privilegios y dar permisos a /app
RUN groupadd -g 10001 app && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin app \
    && chown -R 10001:10001 /app

USER 10001:10001
CMD ["python","/app/src/worker.py"]
