# ==========================================
# Dockerfile - Binance Trading Bot Terminal
# Produção: Gunicorn + Flask-SocketIO (gthread)
# Otimizado para Linux (x86_64 e ARM64 / ZimaOS)
# ==========================================

FROM python:3.11-slim

# Evita geração de bytecode .pyc e força flush imediato nos logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Instalar dependências mínimas do sistema operacional para PostgreSQL e compilações se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python primeiro (aproveitamento de cache de camadas)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar todo o código-fonte da aplicação
COPY . .

# Criar pasta para dados/backup caso necessário e ajustar permissões
RUN mkdir -p /app/data

# Porta padrão de execução
EXPOSE 5000

# Healthcheck do container
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:5000/api/bot/status || exit 1

# Comando de produção: Gunicorn com worker gthread (multithreaded para WebSocket e streams assíncronos)
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
