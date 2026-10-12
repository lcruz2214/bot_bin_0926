import time
import uuid
import hmac
import hashlib
import urllib.parse
import requests
import logging
from typing import Dict, Any, Optional, Callable, Tuple

from config import Config
from database.db_handler import db

logger = logging.getLogger(__name__)

class OrderManager:
    """
    Gerenciador de Ordens, Risco e Idempotência (RF-RISCO, RF-IDEMP, RF-TRADE)
    Implementa:
    - Identificador único de negócio e id externo (RF-IDEMP-001);
    - Verificação antes do envio e proteção contra compras duplicadas (RF-IDEMP-002 / 005);
    - Tratamento de timeout com consulta prévia à Binance (RF-IDEMP-004);
    - Limites estritos de exposição por entrada, por ativo e total (RF-RISCO-002 a 006);
    - Registro de justificativas e integração ao EventLog (RF-RISCO-008, RF-EVENT-001).
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

    @staticmethod
    def generate_client_order_id(symbol: str, side: str) -> str:
        """Gera identificador único para idempotência (RF-IDEMP-001)."""
        clean_sym = symbol.replace("USDT", "")[:6]
        ts = int(time.time() * 1000)
        token = uuid.uuid4().hex[:6]
        return f"BOT_{clean_sym}_{side}_{ts}_{token}"

    # --- Execução Binance Live com Idempotência e Tratamento de Timeout ---
    def check_binance_order_status(self, symbol: str, client_order_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Consulta estado de uma ordem na Binance usando client_order_id (RF-IDEMP-004).
        Utilizado após timeout antes de qualquer tentativa de reenvio.
        """
        api_key = Config.BINANCE_API_KEY
        api_secret = Config.BINANCE_API_SECRET
        if not api_key or not api_secret:
            return False, None

        endpoint = f"{Config.BINANCE_REST_URL}/order"
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol.upper().strip(),
            "origClientOrderId": client_order_id,
            "timestamp": timestamp,
            "recvWindow": 5000
        }
        query_string = urllib.parse.urlencode(params)
        sig = hmac.new(api_secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        headers = {"X-MBX-APIKEY": api_key}

        try:
            resp = requests.get(endpoint, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[{symbol}] [RF-IDEMP-004] Consulta de ordem recuperada: Status={data.get('status')}")
                return True, data
            return False, None
        except Exception as e:
            logger.error(f"[{symbol}] Erro ao consultar estado da ordem {client_order_id}: {e}")
            return False, None

    def send_binance_live_order(self, symbol: str, side: str, client_order_id: str,
                                quantity: float = None, quote_order_qty: float = None) -> Tuple[bool, Any]:
        """
        Envia ordem MARKET para a Binance com clientOrderId para garantir idempotência externa.
        Se ocorrer timeout, consulta o status da ordem antes de concluir (RF-IDEMP-004).
        """
        api_key = Config.BINANCE_API_KEY
        api_secret = Config.BINANCE_API_SECRET

        if not api_key or not api_secret:
            msg = "Chaves de API da Binance não configuradas no arquivo .env!"
            logger.error(msg)
            return False, msg

        endpoint = f"{Config.BINANCE_REST_URL}/order"
        timestamp = int(time.time() * 1000)

        params = {
            "symbol": symbol.upper().strip(),
            "side": side.upper().strip(),
            "type": "MARKET",
            "newClientOrderId": client_order_id,
            "timestamp": timestamp,
            "recvWindow": 5000
        }

        if side.upper() == "BUY" and quote_order_qty:
            params["quoteOrderQty"] = f"{quote_order_qty:.2f}"
        elif quantity:
            params["quantity"] = f"{quantity:.6f}"

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
                logger.info(f"[{symbol}] Ordem REAL executada na Binance! ID={data.get('orderId')}, ClientID={client_order_id}")
                return True, data
            else:
                msg = f"Erro Binance ({data.get('code')}): {data.get('msg')}"
                logger.error(f"[{symbol}] Falha ao executar ordem real na Binance: {msg}")
                return False, msg
        except requests.exceptions.Timeout:
            # RF-IDEMP-004 — Timeout não significa falha automática!
            logger.warning(f"[{symbol}] [RF-IDEMP-004] Timeout no envio! Verificando se a ordem foi executada na Binance...")
            time.sleep(1.5)
            found, order_status = self.check_binance_order_status(symbol, client_order_id)
            if found and order_status and order_status.get("status") in ("FILLED", "PARTIALLY_FILLED"):
                logger.info(f"[{symbol}] [RF-IDEMP-004] Ordem confirmada como executada após timeout!")
                return True, order_status
            return False, "Timeout de comunicação com Binance; ordem não confirmada."
        except Exception as e:
            msg = f"Erro de conexão com Binance API: {e}"
            logger.error(msg)
            return False, msg

    # --- Verificações de Risco e Hierarquia Operacional (RF-RISCO, RF-14) ---
    def check_risk_limits(self, symbol: str, requested_amount_usdt: float, config: Dict[str, Any],
                          entry_number: int = 1) -> Tuple[bool, str]:
        """
        Verifica os limites do Aumento Progressivo de Exposição e Hierarquia Operacional:
        1. Hierarquia Operacional: Kill Switch, Modo Seguro, Pausado (RF-14).
        2. Limite Máximo por Entrada (RF-RISCO-004).
        3. Limite Máximo de Entradas (RF-RISCO-006).
        4. Exposição Máxima por Ativo (RF-RISCO-005).
        5. Capital Máximo Aberto Global.
        6. Saldo em caixa (Modo Paper).
        """
        # 1. Checa status da Hierarquia Operacional
        op_status = db.get_operational_status()
        if not op_status["can_buy"]:
            reason = f"Operação bloqueada pela Hierarquia: {op_status['label']}"
            logger.warning(f"[{symbol}] {reason}")
            db.log_event("ORDEM_BLOQUEADA", reason, level="WARNING", symbol=symbol)
            return False, reason

        # 2. Limite Máximo por Entrada (RF-RISCO-004)
        max_per_order = config.get("max_order_amount_usdt", 150.0)
        if requested_amount_usdt > max_per_order:
            reason = f"[RF-RISCO-004] Valor da entrada (${requested_amount_usdt:.2f}) excede limite máximo por ordem (${max_per_order:.2f} USDT)"
            logger.warning(f"[{symbol}] {reason}")
            db.log_event("ORDEM_BLOQUEADA", reason, level="WARNING", symbol=symbol)
            return False, reason

        # 3. Limite Máximo de Entradas (RF-RISCO-006)
        max_entries = config.get("max_entries_count", 5)
        if entry_number > max_entries:
            reason = f"[RF-RISCO-006] Limite de entradas atingido ({entry_number-1}/{max_entries}). Nova entrada bloqueada."
            logger.warning(f"[{symbol}] {reason}")
            db.log_event("ORDEM_BLOQUEADA", reason, level="WARNING", symbol=symbol)
            return False, reason

        # 4. Limite Máximo por Ativo (RF-RISCO-005)
        max_asset_alloc = config.get("max_asset_allocation_usdt", Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT)
        current_pos = db.get_open_position(symbol)
        asset_invested = current_pos["total_invested_usdt"] if current_pos else 0.0

        if (asset_invested + requested_amount_usdt) > max_asset_alloc:
            reason = (
                f"[RF-RISCO-005] Exposição máxima por ativo excedida! Atual: ${asset_invested:.2f} + "
                f"Nova: ${requested_amount_usdt:.2f} > Limite: ${max_asset_alloc:.2f} USDT"
            )
            logger.warning(f"[{symbol}] {reason}")
            db.log_event("ORDEM_BLOQUEADA", reason, level="WARNING", symbol=symbol,
                         details={"invested": asset_invested, "requested": requested_amount_usdt, "limit": max_asset_alloc})
            return False, reason

        # 5. Limite Global de Capital Aberto
        max_total_open = config.get("max_total_open_capital_usdt", Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT)
        summary = db.get_portfolio_summary()
        current_total_open = summary["total_open_capital"]
        if (current_total_open + requested_amount_usdt) > max_total_open:
            reason = f"Capital aberto total (${current_total_open + requested_amount_usdt:.2f}) excede teto global de ${max_total_open:.2f} USDT"
            logger.warning(f"[{symbol}] {reason}")
            db.log_event("ORDEM_BLOQUEADA", reason, level="WARNING", symbol=symbol)
            return False, reason

        # 6. Saldo Simulado no Paper Trading
        execution_mode = config.get("execution_mode", "PAPER")
        if execution_mode == "PAPER" and requested_amount_usdt > self.paper_balance_usdt:
            reason = f"Saldo simulado insuficiente em caixa (${self.paper_balance_usdt:.2f} USDT)"
            logger.warning(f"[{symbol}] {reason}")
            return False, reason

        return True, "OK"

    # --- Criação e Atualização de Ordens Virtuais com Idempotência ---
    def create_virtual_order(self, symbol: str, order_type: str, side: str, trigger_price: float,
                             reference_price: float, quantity: float, usdt_amount: float, notes: str = "",
                             trade_id: int = None) -> Dict:
        client_order_id = self.generate_client_order_id(symbol, side)
        idempotency_key = f"{symbol}_{order_type}_{side}_{round(trigger_price, 4)}"

        order = db.save_order(
            symbol=symbol,
            order_type=order_type,
            side=side,
            trigger_price=trigger_price,
            reference_price=reference_price,
            quantity=quantity,
            usdt_amount=usdt_amount,
            status="ARMED",
            notes=notes,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
            trade_id=trade_id
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
                              usdt_amount: float, order_id: Optional[int], config: Dict[str, Any],
                              entry_number: int = 1) -> bool:
        """
        Executa compra (inicial ou escalonamento) com auditoria e verificação completa de risco.
        """
        # Checa limites de risco antes de emitir a compra
        allowed, reason = self.check_risk_limits(symbol, usdt_amount, config, entry_number=entry_number)
        if not allowed:
            if order_id:
                self.update_virtual_order(order_id, status="REJECTED", notes=f"Rejeitado: {reason}")
            self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": reason})
            return False

        execution_mode = config.get("execution_mode", "PAPER")
        is_real = (execution_mode == "REAL")
        client_order_id = self.generate_client_order_id(symbol, "BUY")

        # Se modo REAL ativo, envia para a API da Binance com proteção de idempotência
        if is_real:
            ok, res = self.send_binance_live_order(symbol, "BUY", client_order_id=client_order_id, quote_order_qty=usdt_amount)
            if not ok:
                if order_id:
                    self.update_virtual_order(order_id, status="CANCELLED", notes=f"Erro Binance: {res}")
                self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": f"[REAL] {res}"})
                return False

            if isinstance(res, dict) and float(res.get("executedQty", 0)) > 0:
                quantity = float(res.get("executedQty"))
                cummulative_quote = float(res.get("cummulativeQuoteQty", usdt_amount))
                buy_price = cummulative_quote / quantity

        trailing_stop_delta = config.get("trailing_stop_delta", Config.DEFAULT_TRAILING_STOP_DELTA)
        initial_stop_price = buy_price * (1.0 - trailing_stop_delta)

        # Salva / atualiza posição no banco (com controle de escalonamento)
        pos = db.save_position(
            symbol=symbol,
            quantity=quantity,
            entry_price=buy_price,
            trailing_stop_price=initial_stop_price,
            entry_count=entry_number
        )

        # Atualiza ordem de compra para FILLED
        if order_id:
            self.update_virtual_order(
                order_id=order_id,
                status="FILLED",
                executed_price=buy_price,
                notes=f"Entrada #{entry_number} executada ({'REAL BINANCE' if is_real else 'SIMULADA'})"
            )

        # Cria ou atualiza ordem de Trailing Stop ativa
        stop_order = self.create_virtual_order(
            symbol=symbol,
            order_type="TRAILING_STOP",
            side="SELL",
            trigger_price=initial_stop_price,
            reference_price=buy_price,
            quantity=pos["quantity"],
            usdt_amount=pos["total_invested_usdt"],
            notes=f"Stop móvel inicial (-{trailing_stop_delta*100:.2f}%)"
        )

        # Atualiza caixa simulado
        if not is_real:
            self.paper_balance_usdt -= usdt_amount

        # Log de Auditoria no EventLog (RF-EVENT-001, RF-RISCO-008)
        event_name = "POSICAO_ABERTA" if entry_number == 1 else "POSICAO_AUMENTADA"
        db.log_event(
            event_type=event_name,
            message=(
                f"[{symbol}] Entrada #{entry_number} executada @ ${buy_price:.4f} "
                f"(${usdt_amount:.2f} USDT, Qtd={quantity:.6f}) - Stop inicial: ${initial_stop_price:.4f}"
            ),
            level="INFO",
            symbol=symbol,
            position_id=pos["id"],
            order_id=order_id,
            details={
                "entry_number": entry_number,
                "price": buy_price,
                "quantity": quantity,
                "usdt_amount": usdt_amount,
                "stop_price": initial_stop_price,
                "total_invested": pos["total_invested_usdt"],
                "is_real": is_real
            }
        )

        logger.info(
            f"[{symbol}] Compra ({'REAL' if is_real else 'SIMULADA'}) #{entry_number} com SUCESSO! "
            f"Preço={buy_price:.4f}, Total={usdt_amount:.2f} USDT, Posição={pos['quantity']:.6f}"
        )

        # Notificações via WebSocket
        self.emit_event("position_opened", {"symbol": symbol, "position": pos, "stop_order": stop_order})
        self.emit_event("portfolio_summary", self.get_portfolio_data())
        self.emit_event("trade_alert", {
            "type": "SUCCESS",
            "symbol": symbol,
            "message": f"[{'REAL' if is_real else 'SIMULADA'}] Entrada #{entry_number}: {quantity:.4f} {symbol} @ ${buy_price:.4f}"
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
        client_order_id = self.generate_client_order_id(symbol, "SELL")

        if is_real:
            ok, res = self.send_binance_live_order(symbol, "SELL", client_order_id=client_order_id, quantity=pos["quantity"])
            if not ok:
                self.emit_event("trade_alert", {"type": "ERROR", "symbol": symbol, "message": f"[REAL] Falha na venda Binance: {res}"})
                return None
            if isinstance(res, dict) and float(res.get("executedQty", 0)) > 0:
                cummulative_quote = float(res.get("cummulativeQuoteQty", 0))
                executed_qty = float(res.get("executedQty"))
                if executed_qty > 0 and cummulative_quote > 0:
                    exit_price = cummulative_quote / executed_qty

        # Limpa trailing states persistidos deste par
        db.clear_trailing_state(symbol)

        # Fecha posição e gera registro de trade com transição de máquina de estados
        trade = db.close_position(symbol, exit_price, exit_reason)

        # Marca ordens ativas como finalizadas
        active_stops = [o for o in db.get_active_orders(symbol) if o["order_type"] == "TRAILING_STOP"]
        for o in active_stops:
            self.update_virtual_order(o["id"], status="TRIGGERED", executed_price=exit_price, notes=exit_reason)

        # Devolve valor ao caixa se for simulação
        if not is_real and trade:
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
            "message": f"[{'REAL' if is_real else 'SIMULADA'}] Venda {symbol} @ ${exit_price:.4f} | PnL: ${trade['pnl_usdt']:.2f} ({trade['pnl_pct']:.2f}%)"
        })
        return trade

    def notify_stop_updated(self, symbol: str, current_price: float, new_stop: float, highest_price: float):
        """Notifica sobre a elevação do Trailing Stop e atualiza no banco."""
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
        db.log_event("PAPER_RESET", "Paper trading reiniciado com saldo de 10.000 USDT", level="INFO")
        self.emit_event("portfolio_summary", self.get_portfolio_data())
        logger.info("Paper trading reiniciado com sucesso.")
