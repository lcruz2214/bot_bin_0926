import logging
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from config import Config
from database.db_handler import db
from core.market_stream import BinanceMarketStream
from core.indicators import TechnicalIndicators
from core.order_manager import OrderManager
from core.strategy_engine import StrategyEngine

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("App")

# Inicialização Flask & SocketIO
app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False
)

# Inicializa Banco de Dados
db.init_db()

# Inicializa Orquestradores
order_manager = OrderManager(socketio_emitter=lambda evt, data: socketio.emit(evt, data))
strategy_engine = StrategyEngine(order_manager=order_manager)
market_stream = BinanceMarketStream(symbols=Config.AVAILABLE_SYMBOLS, timeframe=Config.DEFAULT_TIMEFRAME)

# Callbacks de Mercado
def handle_candle_update(symbol: str, timeframe: str, candle: dict, df_buffer):
    """Executado a cada tick/kline recebido do WebSocket Binance."""
    try:
        cfg = db.get_config(symbol)
        rsi_p = cfg.get("rsi_period", Config.DEFAULT_RSI_PERIOD)
        bb_p = cfg.get("bb_period", Config.DEFAULT_BB_PERIOD)
        bb_std = cfg.get("bb_std", Config.DEFAULT_BB_STD)
        strategy_tf = (cfg.get("timeframe") or Config.DEFAULT_TIMEFRAME).lower()

        # Calcula indicadores mais recentes para o timeframe
        indicators = TechnicalIndicators.get_latest_indicators(
            df_buffer, rsi_period=rsi_p, bb_period=bb_p, bb_std=bb_std
        )

        # Avalia a estratégia e ordens no timeframe configurado (ex: 1m)
        if timeframe.lower() == strategy_tf:
            strategy_engine.evaluate_tick(symbol, candle["close"], indicators)

        # Transmite atualização em tempo real com identificação do timeframe
        socketio.emit("kline_update", {
            "symbol": symbol,
            "timeframe": timeframe.lower(),
            "candle": candle,
            "indicators": indicators
        })
    except Exception as e:
        logger.error(f"Erro no processamento do tick de {symbol} ({timeframe}): {e}")

def handle_ticker_update(symbol: str, ticker: dict):
    """Executado a cada atualização 24h ticker da Binance."""
    socketio.emit("ticker_update", ticker)

market_stream.on_candle_update = handle_candle_update
market_stream.on_ticker_update = handle_ticker_update

# Inicia stream em background e garante subscrição nos timeframes configurados por par
active_symbols = db.get_active_symbols()
if active_symbols:
    market_stream.symbols = active_symbols
    for s in active_symbols:
        cfg = db.get_config(s)
        if cfg and cfg.get("timeframe"):
            market_stream.ensure_kline_subscription(s, cfg["timeframe"])

market_stream.start()

# ==========================================
# ROTAS HTTP (FRONTEND & REST API)
# ==========================================

@app.route("/")
def index():
    symbols = db.get_active_symbols()
    if not symbols:
        symbols = Config.AVAILABLE_SYMBOLS
    default_symbol = symbols[0] if symbols else "BTCUSDT"
    execution_mode = db.get_execution_mode()
    has_binance_keys = bool(Config.BINANCE_API_KEY and Config.BINANCE_API_SECRET)

    return render_template(
        "index.html",
        symbols=symbols,
        default_symbol=default_symbol,
        timeframes=Config.AVAILABLE_TIMEFRAMES,
        default_timeframe=Config.DEFAULT_TIMEFRAME,
        db_type=db.db_type,
        execution_mode=execution_mode,
        has_binance_keys=has_binance_keys
    )

@app.route("/api/assets", methods=["GET"])
def api_get_assets():
    symbols = db.get_active_symbols()
    return jsonify({"success": True, "symbols": symbols})

@app.route("/api/assets/config", methods=["GET"])
def api_get_all_assets_config():
    """Retorna configuração de todos os pares (can_buy, timeframe, posições)."""
    configs = db.get_all_assets_config()
    return jsonify({"success": True, "assets": configs})

@app.route("/api/assets/bulk-update", methods=["POST"])
def api_bulk_update_assets_config():
    """Permite atualizar permissões de compra e timeframes de múltiplos pares em lote."""
    data = request.json or {}
    items = data.get("updates", [])
    if not items:
        return jsonify({"success": False, "error": "Nenhuma alteração informada."}), 400

    updated = db.bulk_update_assets_config(items)
    for item in items:
        sym = item.get("symbol")
        if sym:
            if item.get("can_buy") is False:
                strategy_engine.cancel_trailing_buy(sym)
            if item.get("timeframe"):
                market_stream.ensure_kline_subscription(sym, item["timeframe"])
            cfg = db.get_config(sym)
            socketio.emit("config_updated", {"symbol": sym, "config": cfg})

    return jsonify({"success": True, "updated": updated})

@app.route("/api/assets/add", methods=["POST"])
def api_add_asset():
    data = request.json or {}
    raw_sym = data.get("symbol", "").upper().strip()
    if not raw_sym:
        return jsonify({"success": False, "error": "Símbolo obrigatório"}), 400

    # Adiciona sufixo USDT se o usuário digitou apenas o ativo base (ex: ADA -> ADAUSDT)
    symbol = raw_sym if raw_sym.endswith("USDT") else f"{raw_sym}USDT"

    # Validação via Binance REST API
    if not market_stream.validate_symbol(symbol):
        return jsonify({"success": False, "error": f"O par {symbol} não foi encontrado na Binance."}), 400

    # Salva no banco de dados e ativa
    asset = db.add_asset(symbol)

    # Registra no market stream e busca histórico
    market_stream.add_symbol(symbol)

    symbols = db.get_active_symbols()
    socketio.emit("asset_added", {"symbol": symbol, "symbols": symbols})
    return jsonify({"success": True, "symbol": symbol, "symbols": symbols, "asset": asset})

@app.route("/api/mode", methods=["GET", "POST"])
def api_mode():
    has_keys = bool(Config.BINANCE_API_KEY and Config.BINANCE_API_SECRET)
    if request.method == "POST":
        data = request.json or {}
        new_mode = data.get("mode", "PAPER").upper().strip()
        if new_mode == "REAL" and not has_keys:
            return jsonify({
                "success": False,
                "error": "Não é possível ativar o Modo Real sem chaves de API configuradas no arquivo .env (BINANCE_API_KEY e BINANCE_API_SECRET)."
            }), 400

        updated_mode = db.set_execution_mode(new_mode)
        socketio.emit("execution_mode_changed", {"mode": updated_mode})
        return jsonify({"success": True, "mode": updated_mode, "has_binance_keys": has_keys})

    current_mode = db.get_execution_mode()
    return jsonify({"success": True, "mode": current_mode, "has_binance_keys": has_keys})

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    symbol = request.args.get("symbol", "").upper() or None
    if request.method == "POST":
        data = request.json or {}
        updated = db.update_config(symbol, data)
        if updated:
            if symbol and not updated.get("can_buy", True):
                strategy_engine.cancel_trailing_buy(symbol)
            if symbol and updated.get("timeframe"):
                market_stream.ensure_kline_subscription(symbol, updated["timeframe"])
            socketio.emit("config_updated", {"symbol": symbol, "config": updated})
        return jsonify({"success": True, "config": updated})
    
    cfg = db.get_config(symbol)
    return jsonify({"success": True, "config": cfg})

@app.route("/api/chart-data", methods=["GET"])
def api_chart_data():
    symbol = request.args.get("symbol", Config.AVAILABLE_SYMBOLS[0]).upper()
    timeframe = request.args.get("timeframe", Config.DEFAULT_TIMEFRAME).lower().strip()
    cfg = db.get_config(symbol)
    rsi_p = cfg.get("rsi_period", Config.DEFAULT_RSI_PERIOD)
    bb_p = cfg.get("bb_period", Config.DEFAULT_BB_PERIOD)
    bb_std = cfg.get("bb_std", Config.DEFAULT_BB_STD)
    
    chart_data = market_stream.get_chart_data(
        symbol,
        timeframe=timeframe,
        rsi_period=rsi_p,
        bb_period=bb_p,
        bb_std=bb_std
    )
    
    # Adiciona posições e ordens ativas para desenhar as linhas no gráfico
    pos = db.get_open_position(symbol)
    orders = db.get_active_orders(symbol)
    
    return jsonify({
        "success": True,
        "chart_data": chart_data,
        "position": pos,
        "active_orders": orders
    })

@app.route("/api/orders", methods=["GET"])
def api_orders():
    symbol = request.args.get("symbol", "").upper() or None
    orders = db.get_active_orders(symbol)
    return jsonify({"success": True, "orders": orders})

@app.route("/api/orders/cancel", methods=["POST"])
def api_cancel_orders():
    data = request.json or {}
    symbol = data.get("symbol", "").upper() or None
    if symbol:
        strategy_engine.cancel_trailing_buy(symbol)
    cancelled = db.cancel_active_orders(symbol)
    socketio.emit("orders_cancelled", {"symbol": symbol, "count": cancelled})
    return jsonify({"success": True, "cancelled": cancelled})

@app.route("/api/positions", methods=["GET"])
def api_positions():
    positions = db.get_all_open_positions()
    return jsonify({"success": True, "positions": positions})

@app.route("/api/positions/close", methods=["POST"])
def api_close_position():
    data = request.json or {}
    symbol = data.get("symbol", "").upper()
    if not symbol:
        return jsonify({"success": False, "error": "Símbolo obrigatório"}), 400

    latest_price = market_stream.get_latest_price(symbol)
    if not latest_price:
        return jsonify({"success": False, "error": "Preço de mercado indisponível"}), 400

    trade = order_manager.execute_simulated_sell(symbol, latest_price, exit_reason="MANUAL_CLOSE")
    return jsonify({"success": True, "trade": trade})

@app.route("/api/trades", methods=["GET"])
def api_trades():
    symbol = request.args.get("symbol", "").upper() or None
    limit = int(request.args.get("limit", 50))
    trades = db.get_trade_logs(symbol, limit=limit)
    return jsonify({"success": True, "trades": trades})

@app.route("/api/portfolio", methods=["GET"])
def api_portfolio():
    summary = order_manager.get_portfolio_data()
    return jsonify({"success": True, "portfolio": summary})

@app.route("/api/paper/reset", methods=["POST"])
def api_reset_paper():
    order_manager.reset_paper_trading()
    return jsonify({"success": True, "message": "Paper trading reiniciado com sucesso."})

@app.route("/api/bot/toggle", methods=["POST"])
def api_toggle_bot():
    data = request.json or {}
    symbol = data.get("symbol", "").upper() or None
    cfg = db.get_config(symbol)
    current_status = cfg.get("is_bot_running", True)
    new_status = not current_status
    updated = db.update_config(symbol, {"is_bot_running": new_status})
    socketio.emit("bot_status_changed", {"symbol": symbol, "is_bot_running": new_status})
    return jsonify({"success": True, "is_bot_running": new_status})

# ==========================================
# EVENTOS SOCKET.IO
# ==========================================

@socketio.on("connect")
def on_client_connect():
    logger.info("Cliente conectado ao WebSocket.")
    emit("portfolio_summary", order_manager.get_portfolio_data())
    emit("positions_update", db.get_all_open_positions())
    emit("orders_update", db.get_active_orders())

@socketio.on("request_state")
def on_request_state(data):
    symbol = (data or {}).get("symbol", Config.AVAILABLE_SYMBOLS[0]).upper()
    emit("portfolio_summary", order_manager.get_portfolio_data())
    emit("positions_update", db.get_all_open_positions())
    emit("orders_update", db.get_active_orders(symbol))

if __name__ == "__main__":
    logger.info(f"Iniciando Bot Binance na porta {Config.PORT}...")
    socketio.run(app, host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, allow_unsafe_werkzeug=True)
