# Base oficial Python
FROM python:3.12-slim

# Configurações básicas
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema
RUN apt update && apt install -y build-essential libpq-dev \
    && apt clean

# Instalar dependências Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copiar projeto
COPY . /app/

# Criar diretórios persistentes
RUN mkdir -p /app/staticfiles

# Entrypoint: migrate + collectstatic antes de iniciar
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

# Comando final: gunicorn em modo produção
CMD ["gunicorn", "nossotrello.wsgi:application", \
     "-b", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "8", \
     "--worker-tmp-dir", "/dev/shm", \
     "--timeout", "120", \
     "--graceful-timeout", "30"]
