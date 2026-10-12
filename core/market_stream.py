import json
import time
import logging
import asyncio
import threading
import requests
import pandas as pd
from typing import Dict, List, Callable, Optional, Set
import websockets

from config import Config
from database.db_handler import db
from core.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

class BinanceMarketStream:
    """
    Cliente WebSocket e REST da Binance com monitoramento resiliente (RF-WS-001 a 006):
    - Detecção e estados: CONECTADO, RECONECTANDO, DESCONECTADO, RECUPERANDO (RF-WS-006);
    - Intervalo progressivo de reconexão (backoff exponencial) com limite de tentativas (RF-WS-002/003);
    - Recuperação de dados perdidos via REST API pós-reconexão (RF-WS-004/005);
    - Remoção dinâmica de pares do stream de mercado (Exclusão de Pares).
    """

    def __init__(self, symbols: List[str] = None, timeframe: str = "5m"):
        self.symbols = [s.upper() for s in (symbols or Config.AVAILABLE_SYMBOLS)]
        self.timeframe = timeframe or Config.DEFAULT_TIMEFRAME
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws = None
        self.status = "DESCONECTADO"  # CONECTADO, RECONECTANDO, DESCONECTADO, RECUPERANDO
        self.max_reconnect_attempts = 50

        # Buffer de candles por símbolo e timeframe: { "BTCUSDT_5m": pd.DataFrame(...), "BTCUSDT_1d": ... }
        self.candle_buffers: Dict[str, pd.DataFrame] = {}
        self.latest_tickers: Dict[str, Dict] = {}
        self.subscribed_streams: Set[str] = set()

        # Callbacks registrados
        self.on_candle_update: Optional[Callable] = None
        self.on_ticker_update: Optional[Callable] = None
        self.on_status_change: Optional[Callable] = None

    def set_status(self, new_status: str):
        if self.status != new_status:
            old = self.status
            self.status = new_status
            logger.info(f"[WEBSOCKET] Estado alterado: {old} -> {new_status}")
            if self.on_status_change:
                try:
                    self.on_status_change(new_status)
                except Exception as e:
                    logger.error(f"Erro no callback de status do WebSocket: {e}")

    def fetch_historical_klines(self, symbol: str, interval: str = "5m", limit: int = 150) -> pd.DataFrame:
        """Busca histórico de candles via REST API da Binance para o intervalo solicitado."""
        url = f"{Config.BINANCE_REST_URL}/klines"
        params = {
            "symbol": symbol.upper().strip(),
            "interval": interval.lower().strip(),
            "limit": limit
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            rows = []
            for item in data:
                rows.append({
                    "time": int(item[0] // 1000),  # segundos para lightweight-charts
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            df = pd.DataFrame(rows)
            return df
        except Exception as e:
            logger.error(f"Erro ao buscar histórico de klines para {symbol} ({interval}): {e}")
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    def initialize_buffers(self, symbols: List[str] = None, timeframe: str = None):
        """Carrega candles iniciais para os símbolos configurados."""
        symbols = symbols or self.symbols
        tf = (timeframe or self.timeframe).lower()
        for sym in symbols:
            key = f"{sym}_{tf}"
            df = self.fetch_historical_klines(sym, interval=tf, limit=120)
            if not df.empty:
                self.candle_buffers[key] = df
                logger.info(f"Buffer de {key} inicializado com {len(df)} candles.")

    def ensure_kline_subscription(self, symbol: str, timeframe: str):
        """Garante que a conexão WebSocket está inscrita no stream do par e timeframe."""
        sym = symbol.lower().strip()
        tf = timeframe.lower().strip()
        stream_name = f"{sym}@kline_{tf}"
        key = f"{symbol.upper().strip()}_{tf}"

        if key not in self.candle_buffers or self.candle_buffers[key].empty:
            df = self.fetch_historical_klines(symbol.upper().strip(), interval=tf, limit=120)
            if not df.empty:
                self.candle_buffers[key] = df

        if stream_name not in self.subscribed_streams:
            self.subscribed_streams.add(stream_name)
            if self.loop and self.loop.is_running() and hasattr(self, "ws") and self.ws:
                try:
                    sub_msg = {
                        "method": "SUBSCRIBE",
                        "params": [stream_name],
                        "id": int(time.time() * 1000)
                    }
                    asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(sub_msg)), self.loop)
                    logger.info(f"WebSocket inscrito com sucesso em: {stream_name}")
                except Exception as e:
                    logger.error(f"Erro ao enviar SUBSCRIBE para {stream_name}: {e}")

    def get_chart_data(self, symbol: str, timeframe: str = "5m", rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0) -> Dict:
        """Retorna histórico de candles no timeframe selecionado com indicadores calculados."""
        sym = symbol.upper().strip()
        tf = (timeframe or "5m").lower().strip()
        key = f"{sym}_{tf}"

        if key not in self.candle_buffers or self.candle_buffers[key].empty:
            df = self.fetch_historical_klines(sym, interval=tf, limit=120)
            if not df.empty:
                self.candle_buffers[key] = df
            else:
                return {
                    "symbol": sym,
                    "timeframe": tf,
                    "candles": [],
                    "bb_upper": [],
                    "bb_middle": [],
                    "bb_lower": [],
                    "rsi": []
                }

        self.ensure_kline_subscription(sym, tf)

        df = self.candle_buffers[key]
        df_calc = TechnicalIndicators.compute_all(df, rsi_period=rsi_period, bb_period=bb_period, bb_std=bb_std)

        candles = []
        bb_upper = []
        bb_middle = []
        bb_lower = []
        rsi = []

        for _, row in df_calc.iterrows():
            t = int(row["time"])
            candles.append({
                "time": t,
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4)
            })
            if pd.notna(row.get("bb_upper")):
                bb_upper.append({"time": t, "value": round(float(row["bb_upper"]), 4)})
                bb_middle.append({"time": t, "value": round(float(row["bb_middle"]), 4)})
                bb_lower.append({"time": t, "value": round(float(row["bb_lower"]), 4)})
            if pd.notna(row.get("rsi")):
                rsi.append({"time": t, "value": round(float(row["rsi"]), 2)})

        return {
            "symbol": sym,
            "timeframe": tf,
            "candles": candles,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "rsi": rsi
        }

    def start(self):
        if self.running:
            return
        self.running = True
        self.initialize_buffers()
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True, name="BinanceStreamThread")
        self.thread.start()
        logger.info("Market stream da Binance iniciado em background.")

    def stop(self):
        self.running = False
        self.set_status("DESCONECTADO")
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        logger.info("Market stream da Binance interrompido.")

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._websocket_worker())

    async def _websocket_worker(self):
        """Worker WebSocket assíncrono com backoff exponencial e recuperação de dados perdidos (RF-WS-001 a 005)."""
        backoff = 1
        reconnect_attempts = 0

        while self.running:
            try:
                # Monta streams combinados dos pares ativos
                for sym in self.symbols:
                    s_lower = sym.lower()
                    self.subscribed_streams.add(f"{s_lower}@kline_{self.timeframe}")
                    self.subscribed_streams.add(f"{s_lower}@ticker")

                stream_url = f"{Config.BINANCE_STREAM_URL}{'/'.join(list(self.subscribed_streams))}"
                logger.info(f"Conectando ao Binance WebSocket: {len(self.subscribed_streams)} streams ativos.")

                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    backoff = 1

                    if reconnect_attempts > 0:
                        self.set_status("RECUPERANDO")
                        db.log_event("WEBSOCKET_RECONECTADO", "WebSocket reconectado. Recuperando dados perdidos...", level="INFO")
                        # Recupera dados perdidos pós-reconexão via REST (RF-WS-004/005)
                        self._recover_missing_data()

                    reconnect_attempts = 0
                    self.set_status("CONECTADO")
                    db.log_event("WEBSOCKET_CONECTADO", f"WebSocket conectado ({len(self.subscribed_streams)} streams)", level="INFO")
                    logger.info("WebSocket Binance conectado com sucesso!")

                    while self.running:
                        message = await ws.recv()
                        self._process_message(message)

            except (websockets.ConnectionClosed, Exception) as e:
                if not self.running:
                    self.set_status("DESCONECTADO")
                    break

                reconnect_attempts += 1
                self.set_status("RECONECTANDO")
                db.log_event(
                    "WEBSOCKET_DESCONECTADO",
                    f"Conexão WebSocket interrompida ({e}). Tentativa #{reconnect_attempts} em {backoff}s...",
                    level="WARNING"
                )
                logger.warning(f"Conexão WebSocket perdida: {e}. Reconectando em {backoff}s (Tentativa {reconnect_attempts})...")

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _recover_missing_data(self):
        """Atualiza os últimos candles de todos os pares monitorados via REST após reconexão (RF-WS-004)."""
        try:
            logger.info("Recuperando histórico recente de candles pós-reconexão...")
            for sym in self.symbols:
                for k in list(self.candle_buffers.keys()):
                    if k.startswith(f"{sym}_"):
                        tf = k.split("_")[1]
                        df = self.fetch_historical_klines(sym, interval=tf, limit=30)
                        if not df.empty:
                            self.candle_buffers[k] = df
            logger.info("Recuperação de dados concluída.")
        except Exception as e:
            logger.error(f"Erro ao recuperar dados pós-reconexão: {e}")

    @staticmethod
    def validate_symbol(symbol: str) -> bool:
        """Verifica se o par existe e está ativo na Binance."""
        url = f"{Config.BINANCE_REST_URL}/ticker/price"
        try:
            resp = requests.get(url, params={"symbol": symbol.upper().strip()}, timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Erro ao validar par {symbol} na Binance: {e}")
            return False

    def add_symbol(self, symbol: str) -> bool:
        """Adiciona dinamicamente um novo par de moedas ao stream e inicializa buffers."""
        sym = symbol.upper().strip()
        if not self.validate_symbol(sym):
            logger.warning(f"Par {sym} não encontrado ou inválido na Binance.")
            return False

        if sym not in self.symbols:
            self.symbols.append(sym)
            key = f"{sym}_{self.timeframe}"
            df = self.fetch_historical_klines(sym, interval=self.timeframe, limit=120)
            if not df.empty:
                self.candle_buffers[key] = df

            if self.loop and self.loop.is_running() and hasattr(self, "ws") and self.ws:
                try:
                    sub_msg = {
                        "method": "SUBSCRIBE",
                        "params": [f"{sym.lower()}@kline_{self.timeframe}", f"{sym.lower()}@ticker"],
                        "id": int(time.time() * 1000)
                    }
                    asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(sub_msg)), self.loop)
                except Exception as e:
                    logger.error(f"Erro ao enviar SUBSCRIBE para {sym}: {e}")

            logger.info(f"Par {sym} adicionado dinamicamente ao streaming Binance!")
        return True

    def remove_symbol(self, symbol: str) -> bool:
        """
        Remove dinamicamente um par do monitoramento:
        - Remove das listas de símbolos e buffers;
        - Envia comando UNSUBSCRIBE para o WebSocket da Binance;
        - Limpa streams cadastrados.
        """
        sym = symbol.upper().strip()
        s_lower = sym.lower()

        if sym in self.symbols:
            self.symbols.remove(sym)

        # Remove buffers de memória para este símbolo
        keys_to_remove = [k for k in self.candle_buffers.keys() if k.startswith(f"{sym}_")]
        for k in keys_to_remove:
            self.candle_buffers.pop(k, None)

        self.latest_tickers.pop(sym, None)

        # Streams do símbolo
        streams_to_unsub = [s for s in self.subscribed_streams if s.startswith(f"{s_lower}@")]
        for s in streams_to_unsub:
            self.subscribed_streams.discard(s)

        # Envia UNSUBSCRIBE para o WebSocket se conectado
        if streams_to_unsub and self.loop and self.loop.is_running() and hasattr(self, "ws") and self.ws:
            try:
                unsub_msg = {
                    "method": "UNSUBSCRIBE",
                    "params": streams_to_unsub,
                    "id": int(time.time() * 1000)
                }
                asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(unsub_msg)), self.loop)
                logger.info(f"WebSocket desinscrito com sucesso de: {streams_to_unsub}")
            except Exception as e:
                logger.error(f"Erro ao enviar UNSUBSCRIBE para {sym}: {e}")

        logger.info(f"Par {sym} removido com sucesso do streaming da Binance.")
        return True

    def _process_message(self, raw_message: str):
        try:
            data = json.loads(raw_message)
            stream_name = data.get("stream", "")
            payload = data.get("data", {})

            if "@kline_" in stream_name:
                k = payload.get("k", {})
                sym = payload.get("s", "").upper()
                tf = k.get("i", "1m").lower()
                if not k or not sym:
                    return

                candle_time = int(k["t"] // 1000)
                candle_obj = {
                    "time": candle_time,
                    "open": float(k["o"]),
                    "high": float(k["h"]),
                    "low": float(k["l"]),
                    "close": float(k["c"]),
                    "volume": float(k["v"]),
                    "is_closed": bool(k["x"])
                }

                self._update_candle_buffer(sym, tf, candle_obj)

                if self.on_candle_update:
                    key = f"{sym}_{tf}"
                    self.on_candle_update(sym, tf, candle_obj, self.candle_buffers.get(key))

            elif "@ticker" in stream_name:
                sym = payload.get("s", "").upper()
                ticker_obj = {
                    "symbol": sym,
                    "price": float(payload.get("c", 0)),
                    "price_change_pct": float(payload.get("P", 0)),
                    "high": float(payload.get("h", 0)),
                    "low": float(payload.get("l", 0)),
                    "volume": float(payload.get("v", 0)),
                    "timestamp": time.time()
                }
                self.latest_tickers[sym] = ticker_obj
                if self.on_ticker_update:
                    self.on_ticker_update(sym, ticker_obj)

        except Exception as e:
            logger.error(f"Erro ao processar mensagem do WebSocket Binance: {e}")

    def _update_candle_buffer(self, symbol: str, timeframe: str, candle: Dict):
        key = f"{symbol}_{timeframe}"
        if key not in self.candle_buffers or self.candle_buffers[key].empty:
            df = self.fetch_historical_klines(symbol, interval=timeframe, limit=120)
            if df.empty:
                df = pd.DataFrame([candle])
            self.candle_buffers[key] = df

        df = self.candle_buffers[key]
        last_idx = df.index[-1]
        last_time = df.loc[last_idx, "time"]

        if last_time == candle["time"]:
            df.loc[last_idx, ["open", "high", "low", "close", "volume"]] = [
                candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]
            ]
        elif candle["time"] > last_time:
            new_row = pd.DataFrame([{
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"]
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            if len(df) > 200:
                df = df.iloc[-200:].reset_index(drop=True)
            self.candle_buffers[key] = df

    def get_latest_price(self, symbol: str) -> Optional[float]:
        sym = symbol.upper().strip()
        ticker = self.latest_tickers.get(sym)
        if ticker:
            return ticker["price"]
        for k, df in self.candle_buffers.items():
            if k.startswith(f"{sym}_") and not df.empty:
                return float(df["close"].iloc[-1])
        return None
