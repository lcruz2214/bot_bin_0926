import time
import hmac
import hashlib
import urllib.parse
import requests
import logging
from typing import Dict, Any, Optional, Callable
from config import Config
from database.db_handler import db

logger = logging.getLogger(__name__)

class OrderManager:
    """
    Gerenciador de ordens e posições em modo Paper Trading (Simulação)
    e Modo Real (Live Binance API) com validação rigorosa de risco.
    """

    def __init__(self, socketio_emitter: Optional[Callable] = None):
        self.socketio_emitter = socketio_emitter
        self.paper_balance_usdt = Config.INITIAL_BALANCE_USDT

    def set_socketio_emitter(self, emitter: Callable):
        self.socketio_emitter = emitter

    def emit_event(self, event_name: str, payload: Any):
        if self.socketio_emitter:
            try:
                self.socketio_emitter(event_name, payload)
            except Exception as e:
                logger.error(f"Erro ao emitir evento SocketIO {event_name}: {e}")

    # --- Execução Binance Live (Modo Real) ---
    def send_binance_live_order(self, symbol: str, side: str, quantity: float = None, quote_order_qty: float = None) -> tuple[bool, Any]:
        """Envia ordem MARKET real diretamente para a Binance via REST API com assinatura HMAC-SHA256."""
        api_key = Config.BINANCE_API_KEY
        api_secret = Config.BINANCE_API_SECRET

        if not api_key or not api_secret:
            msg = "Chaves de API da Binance (API Key e Secret) não configuradas no arquivo .env!"
            logger.error(msg)
            return False, msg

        endpoint = f"{Config.BINANCE_REST_URL}/order"
        timestamp = int(time.time() * 1000)

        params = {
            "symbol": symbol.upper().strip(),
            "side": side.upper().strip(),
            "type": "MARKET",
            "timestamp": timestamp,
            "recvWindow": 5000
        }

        if side.upper() == "BUY" and quote_order_qty:
            params["quoteOrderQty"] = f"{quote_order_qty:.2f}"
        elif quantity:
            params["quantity"] = f"{quantity:.6f}"

        # Assinatura HMAC-SHA256
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(api_secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature

        headers = {
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            resp = requests.post(endpoint, params=params, headers=headers, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                logger.info(f"[{symbol}] Ordem REAL executada na Binance com sucesso! ID={data.get('orderId')}")
                return True, data
            else:
                msg = f"Erro Binance ({data.get('code')}): {data.get('msg')}"
                logger.error(f"[{symbol}] Falha ao executar ordem real na Binance: {msg}")
                return False, msg
        except Exception as e:
            msg = f"Erro de conexão com Binance API: {e}"
            logger.error(msg)
            return False, msg

    # --- Verificações de Risco & Alocação ---
    def check_risk_limits(self, symbol: str, requested_amount_usdt: float, config: Dict[str, Any]) -> tuple[bool, str]:
        """
        Verifica se a ordem atende aos limites:
        1. Capital Máximo Total em Aberto (global).
        2. Alocação Máxima por Ativo.
        3. Saldo disponível em caixa.
        """
        max_total_open = config.get("max_total_open_capital_usdt", Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT)
        max_asset_alloc = config.get("max_asset_allocation_usdt", Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT)

        summary = db.get_portfolio_summary()
        current_total_open = summary["total_open_capital"]

        # Checa limite global de capital aberto
        if (current_total_open + requested_amount_usdt) > max_total_open:
            logger.warning(
                f"[{symbol}] Ordem rejeitada por RISCO: Capital aberto atual ({current_total_open:.2f}) + "
                f"ordem ({requested_amount_usdt:.2f}) excede o limite global de {max_total_open:.2f} USDT!"
            )
            return False, f"Excede capital máximo aberto ({max_total_open} USDT)"

        # Checa limite individual do ativo
        current_pos = db.get_open_position(symbol)
        asset_current_invested = current_pos["total_invested_usdt"] if current_pos else 0.0
        if (asset_current_invested + requested_amount_usdt) > max_asset_alloc:
            logger.warning(
                f"[{symbol}] Ordem rejeitada por RISCO: Investimento atual no ativo ({asset_current_invested:.2f}) + "
                f"ordem ({requested_amount_usdt:.2f}) excede alocação máxima de {max_asset_alloc:.2f} USDT!"
            )
            return False, f"Excede alocação máxima do ativo ({max_asset_alloc} USDT)"

        # Se for modo PAPER, checa saldo virtual
        execution_mode = config.get("execution_mode", "PAPER")
        if execution_mode == "PAPER" and requested_amount_usdt > self.paper_balance_usdt:
            logger.warning(
                f"[{symbol}] Ordem rejeitada: Saldo simulado insuficiente ({self.paper_balance_usdt:.2f} USDT)!"
            )
            return False, "Saldo simulado insuficiente em caixa"

        return True, "OK"

    # --- Criação e Atualização de Ordens Virtuais ---
    def create_virtual_order(self, symbol: str, order_type: str, side: str, trigger_price: float,
                             reference_price: float, quantity: float, usdt_amount: float, notes: str = "") -> Dict:
        order = db.save_order(
            symbol=symbol,
            order_type=order_type,
            side=side,
            trigger_price=trigger_price,
            reference_price=reference_price,
            quantity=quantity,
            usdt_amount=usdt_amount,
            status="ARMED",
            notes=notes
        )
        self.emit_event("order_update", {"type": "CREATED", "order": order})
        return order

    def update_virtual_order(self, order_id: int, **kwargs) -> Optional[Dict]:
        order = db.update_order(order_id, **kwargs)
        if order:
            self.emit_event("order_update", {"type": "UPDATED", "order": order})
        return order

    # --- Execução de Compra (Paper Trading ou Live Real) ---
    def execute_simulated_buy(self, symbol: str, buy_price: float, quantity: float,
                              usdt_amount: float, order_id: Optional[int], config: Dict[str, Any]) -> bool:
        # Checa limites de risco antes de fechar a compra
        allowed, reason = self.check_risk_limits(symbol, usdt_amount, config)
        if not allowed:
            if order_id:
                self.update_virtual_order(order_id, status="CANCELLED", notes=f"Rejeitado: {reason}")
            self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": reason})
            return False

        execution_mode = config.get("execution_mode", "PAPER")
        is_real = (execution_mode == "REAL")

        # Se modo REAL ativo, envia para a API da Binance
        if is_real:
            ok, res = self.send_binance_live_order(symbol, "BUY", quote_order_qty=usdt_amount)
            if not ok:
                if order_id:
                    self.update_virtual_order(order_id, status="CANCELLED", notes=f"Erro Binance Real: {res}")
                self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": f"[REAL] {res}"})
                return False

            if isinstance(res, dict) and float(res.get("executedQty", 0)) > 0:
                quantity = float(res.get("executedQty"))
                cummulative_quote = float(res.get("cummulativeQuoteQty", usdt_amount))
                buy_price = cummulative_quote / quantity

        trailing_stop_delta = config.get("trailing_stop_delta", Config.DEFAULT_TRAILING_STOP_DELTA)
        initial_stop_price = buy_price * (1.0 - trailing_stop_delta)

        # Salva posição no banco
        pos = db.save_position(
            symbol=symbol,
            quantity=quantity,
            entry_price=buy_price,
            trailing_stop_price=initial_stop_price
        )

        # Atualiza ordem de compra para FILLED
        if order_id:
            self.update_virtual_order(
                order_id=order_id,
                status="FILLED",
                executed_price=buy_price,
                notes=f"Ordem preenchida ({'REAL BINANCE' if is_real else 'SIMULADA'})"
            )

        # Cria ordem de Trailing Stop ativa
        stop_order = self.create_virtual_order(
            symbol=symbol,
            order_type="TRAILING_STOP",
            side="SELL",
            trigger_price=initial_stop_price,
            reference_price=buy_price,
            quantity=quantity,
            usdt_amount=usdt_amount,
            notes=f"Stop móvel inicial (-{trailing_stop_delta*100:.2f}%)"
        )

        # Atualiza caixa do paper trading se simulação
        if not is_real:
            self.paper_balance_usdt -= usdt_amount

        logger.info(
            f"[{symbol}] Compra ({'REAL' if is_real else 'SIMULADA'}) realizada com SUCESSO! Preço={buy_price:.4f}, "
            f"Qtd={quantity:.6f}, Total={usdt_amount:.2f} USDT, Stop={initial_stop_price:.4f}"
        )

        # Notificações via WebSocket
        self.emit_event("position_opened", {"symbol": symbol, "position": pos, "stop_order": stop_order})
        self.emit_event("portfolio_summary", self.get_portfolio_data())
        self.emit_event("trade_alert", {
            "type": "SUCCESS",
            "symbol": symbol,
            "message": f"[{'REAL' if is_real else 'SIMULADA'}] Compra executada: {quantity:.4f} {symbol} @ ${buy_price:.4f} (Stop: ${initial_stop_price:.4f})"
        })
        return True

    # --- Execução de Venda (Paper Trading ou Live Real) ---
    def execute_simulated_sell(self, symbol: str, exit_price: float, exit_reason: str) -> Optional[Dict]:
        pos = db.get_open_position(symbol)
        if not pos:
            return None

        config = db.get_config(symbol)
        execution_mode = config.get("execution_mode", "PAPER")
        is_real = (execution_mode == "REAL")

        if is_real:
            ok, res = self.send_binance_live_order(symbol, "SELL", quantity=pos["quantity"])
            if not ok:
                self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": f"[REAL] Falha na venda Binance: {res}"})
                return None
            if isinstance(res, dict) and float(res.get("executedQty", 0)) > 0:
                cummulative_quote = float(res.get("cummulativeQuoteQty", 0))
                executed_qty = float(res.get("executedQty"))
                if executed_qty > 0 and cummulative_quote > 0:
                    exit_price = cummulative_quote / executed_qty

        # Fecha posição e gera log de trade
        trade = db.close_position(symbol, exit_price, exit_reason)

        # Cancela ou marca ordem de Trailing Stop como executada
        active_stops = [o for o in db.get_active_orders(symbol) if o["order_type"] == "TRAILING_STOP"]
        for o in active_stops:
            self.update_virtual_order(o["id"], status="TRIGGERED", executed_price=exit_price, notes=exit_reason)

        # Devolve valor ao caixa se simulação
        if not is_real:
            self.paper_balance_usdt += trade["return_usdt"]

        logger.info(
            f"[{symbol}] Venda ({'REAL' if is_real else 'SIMULADA'}) realizada! Preço={exit_price:.4f}, "
            f"PnL={trade['pnl_usdt']:.2f} USDT ({trade['pnl_pct']:.2f}%), Motivo: {exit_reason}"
        )

        # Notificações via WebSocket
        self.emit_event("position_closed", {"symbol": symbol, "trade": trade})
        self.emit_event("portfolio_summary", self.get_portfolio_data())
        self.emit_event("trade_alert", {
            "type": "INFO" if trade["pnl_usdt"] >= 0 else "WARNING",
            "symbol": symbol,
            "message": f"[{'REAL' if is_real else 'SIMULADA'}] Venda executada: {trade['quantity']:.4f} {symbol} @ ${exit_price:.4f} | PnL: ${trade['pnl_usdt']:.2f} ({trade['pnl_pct']:.2f}%)"
        })
        return trade

    def notify_stop_updated(self, symbol: str, current_price: float, new_stop: float, highest_price: float):
        """Notifica o frontend sobre a subida do Trailing Stop."""
        # Atualiza a ordem ativa no banco
        active_stops = [o for o in db.get_active_orders(symbol) if o["order_type"] == "TRAILING_STOP"]
        for o in active_stops:
            self.update_virtual_order(o["id"], trigger_price=new_stop, reference_price=highest_price)

        self.emit_event("stop_updated", {
            "symbol": symbol,
            "current_price": round(current_price, 4),
            "new_stop_price": round(new_stop, 4),
            "highest_price": round(highest_price, 4)
        })

    def get_portfolio_data(self) -> Dict[str, Any]:
        data = db.get_portfolio_summary()
        data["paper_balance_usdt"] = round(self.paper_balance_usdt, 2)
        data["total_equity_usdt"] = round(self.paper_balance_usdt + data["total_open_capital"] + data["total_unrealized_pnl"], 2)
        return data

    def reset_paper_trading(self):
        """Reinicia o ambiente simulado para testes limpos."""
        self.paper_balance_usdt = Config.INITIAL_BALANCE_USDT
        db.cancel_active_orders()
        for pos in db.get_all_open_positions():
            db.close_position(pos["symbol"], pos["current_price"], "PAPER_RESET")
        self.emit_event("portfolio_summary", self.get_portfolio_data())
        logger.info("Paper trading reiniciado com sucesso.")
