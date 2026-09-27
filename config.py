import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env se existir
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "bot_binance_super_secret_secure_key_2026")
    
    # Configuração PostgreSQL com fallback seguro
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "binance_bot")

    POSTGRES_URI = os.getenv(
        "DATABASE_URL",
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data") if (BASE_DIR / "data").exists() else str(BASE_DIR)))
    SQLITE_URI = f"sqlite:///{DATA_DIR / 'crypto_bot.db'}"
    
    # Parâmetros Binance
    BINANCE_REST_URL = "https://api.binance.com/api/v3"
    BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
    BINANCE_STREAM_URL = "wss://stream.binance.com:9443/stream?streams="
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    
    # Modo de Execução Seguro
    PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() in ("true", "1", "yes")
    INITIAL_BALANCE_USDT = float(os.getenv("INITIAL_BALANCE_USDT", "10000.0"))
    
    # Ativos e Timeframes monitorados
    AVAILABLE_SYMBOLS = [
        s.strip().upper() for s in os.getenv("DEFAULT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT").split(",") if s.strip()
    ]
    DEFAULT_TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "1m")
    AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]

    # Parâmetros Técnicos Padrão
    DEFAULT_RSI_PERIOD = 14
    DEFAULT_RSI_OVERSOLD = 30.0
    DEFAULT_RSI_OVERBOUGHT = 70.0
    DEFAULT_BB_PERIOD = 20
    DEFAULT_BB_STD = 2.0
    
    # Gatilho de Ativação: 'rsi', 'bb_lower', 'both'
    DEFAULT_ACTIVATION_TRIGGER = "both"

    # Mecânica Trailing Buy & Trailing Stop Padrão
    DEFAULT_TRAILING_BUY_DELTA = 0.005       # 0.5% acima da mínima
    DEFAULT_BUY_HYSTERESIS = 0.002           # 0.2% de tolerância
    DEFAULT_TRAILING_STOP_DELTA = 0.010      # 1.0% de recuo antes da venda
    DEFAULT_SELL_HYSTERESIS = 0.002          # 0.2% de tolerância para subir o stop
    
    # Gestão de Risco & Alocação Financeira
    DEFAULT_BASE_ORDER_USDT = 50.0           # Alocação base por ordem em USDT
    DEFAULT_MAX_ASSET_ALLOCATION_USDT = 250.0 # Máximo por ativo
    DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT = 1000.0 # Capital máximo total em aberto
    
    # Multiplicador de Queda (Martingale / Preço Médio Ponderado)
    DEFAULT_DROP_MULTIPLIER = 1.25           # Aumento de volume se cair mais que o limiar
    DEFAULT_DROP_THRESHOLD_PCT = 0.015       # 1.5% de queda adicional para ativar multiplicador
    
    # Servidor Web
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
