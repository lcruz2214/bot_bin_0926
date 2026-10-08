import logging
from typing import Dict, Optional, Tuple, Any
from database.db_handler import db

logger = logging.getLogger(__name__)

class StrategyEngine:
    """
    Motor da estratégia quantitativa que implementa:
    1. Trailing Buy com detecção de sobrevenda (RSI e/ou Banda Inferior), histerese e multiplicador de queda.
    2. Trailing Stop com rastreamento contínuo de máximas, histerese de avanço e trava de descida (catchet).
    """

    def __init__(self, order_manager):
        self.order_manager = order_manager
        # Estado em memória de ordens ativas de trailing buy:
        # { "BTCUSDT": { "p_min": float, "initial_trigger_price": float, "p_buy": float, "order_id": int } }
        self.active_trailing_buys: Dict[str, Dict[str, Any]] = {}

    def check_activation_condition(self, price: float, indicators: Dict[str, Optional[float]], config: Dict[str, Any]) -> bool:
        """
        Verifica se a condição de ativação configurada foi atendida:
        - 'or' (padrão): Preço <= BB Inferior OU RSI <= Sobrevenda (Operação OR)
        - 'rsi': Apenas RSI <= Sobrevenda
        - 'bb_lower': Apenas Preço <= BB Inferior
        - 'and': Preço <= BB Inferior E RSI <= Sobrevenda simultaneamente (Operação AND)
        """
        rsi = indicators.get("rsi")
        bb_lower = indicators.get("bb_lower")
        trigger_mode = config.get("activation_trigger", "or")
        rsi_oversold = config.get("rsi_oversold", 30.0)

        if price is None:
            return False

        rsi_condition = (rsi is not None and rsi <= rsi_oversold)
        bb_condition = (bb_lower is not None and price <= bb_lower)

        if trigger_mode in ("or", "either", "both"):
            # Operação OR: ativa se Banda Inferior OU RSI atingirem a condição
            return rsi_condition or bb_condition
        elif trigger_mode == "rsi":
            return rsi_condition
        elif trigger_mode == "bb_lower":
            return bb_condition
        elif trigger_mode in ("and",):
            # Operação AND: exige ambos simultaneamente
            return rsi_condition and bb_condition
        return False

    def evaluate_tick(self, symbol: str, current_price: float, indicators: Dict[str, Optional[float]]):
        """
        Avalia o preço e indicadores em tempo real para um ativo.
        Executado a cada tick/kline recebido.
        """
        config = db.get_config(symbol)
        if not config or not config.get("is_bot_running", True):
            return

        # 1. Verifica se já existe uma posição aberta para este ativo
        open_position = db.get_open_position(symbol)

        if open_position:
            # Ativo já comprado -> Gerenciar Trailing Stop e Saída (sempre ativo para proteção de capital)
            self._handle_trailing_stop(symbol, current_price, open_position, config)
        else:
            # Ativo sem posição aberta -> Gerenciar Condição de Entrada / Trailing Buy se compras permitidas
            can_buy = config.get("can_buy", True)
            if can_buy:
                self._handle_trailing_buy(symbol, current_price, indicators, config)
            else:
                # Se compras foram bloqueadas para este par, cancela qualquer trailing buy armado
                if symbol in self.active_trailing_buys:
                    self.cancel_trailing_buy(symbol)

    def _handle_trailing_buy(self, symbol: str, current_price: float, indicators: Dict[str, Optional[float]], config: Dict[str, Any]):
        """
        Mecânica de Trailing Buy:
        - Ativação por sobrevenda.
        - Registro de P_min e cálculo de P_buy = P_min * (1 + delta).
        - Histerese: Se preço continua caindo e (P_buy - P_atual) / P_atual >= histerese, ajusta P_min e P_buy para baixo.
        - Ajuste de volume / Multiplicador de queda se preço cair significativamente.
        - Execução: Quando P_atual >= P_buy, dispara compra simulada a mercado.
        """
        trailing_buy_delta = config.get("trailing_buy_delta", 0.005)
        buy_hysteresis = config.get("buy_hysteresis", 0.002)
        base_order_usdt = config.get("base_order_usdt", 50.0)
        drop_multiplier = config.get("drop_multiplier", 1.25)
        drop_threshold_pct = config.get("drop_threshold_pct", 0.015)

        tb_state = self.active_trailing_buys.get(symbol)

        # Se ainda não existe ordem de Trailing Buy ativa para este símbolo
        if not tb_state:
            # Verifica se atingiu a condição de sobrevenda
            if self.check_activation_condition(current_price, indicators, config):
                p_min = current_price
                p_buy = p_min * (1.0 + trailing_buy_delta)
                qty = base_order_usdt / p_buy

                # Cria ordem virtual no banco
                order = self.order_manager.create_virtual_order(
                    symbol=symbol,
                    order_type="TRAILING_BUY",
                    side="BUY",
                    trigger_price=p_buy,
                    reference_price=p_min,
                    quantity=qty,
                    usdt_amount=base_order_usdt,
                    notes=f"Gatilho ativado: RSI={indicators.get('rsi')}, BB_Low={indicators.get('bb_lower')}"
                )

                self.active_trailing_buys[symbol] = {
                    "p_min": p_min,
                    "initial_trigger_price": current_price,
                    "p_buy": p_buy,
                    "order_id": order["id"] if order else None,
                    "allocated_usdt": base_order_usdt
                }
                logger.info(
                    f"[{symbol}] Trailing Buy ARMADO! P_min={p_min:.4f}, P_buy={p_buy:.4f} (+{trailing_buy_delta*100:.2f}%)"
                )
            return

        # Já existe Trailing Buy ativo:
        p_min = tb_state["p_min"]
        p_buy = tb_state["p_buy"]
        initial_price = tb_state["initial_trigger_price"]
        order_id = tb_state["order_id"]

        # CENÁRIO 1: O preço continua caindo abaixo de P_min
        if current_price < p_min:
            # Distância atual em relação ao P_buy configurado
            rel_distance = (p_buy - current_price) / current_price if current_price > 0 else 0

            # Lógica de Histerese: só ajusta se a distância for maior ou igual à histerese
            if rel_distance >= buy_hysteresis:
                new_p_min = current_price
                new_p_buy = new_p_min * (1.0 + trailing_buy_delta)

                # Ajuste de volume / Multiplicador de queda:
                # Se o preço caiu mais de 'drop_threshold_pct' em relação ao preço inicial do gatilho
                allocated_usdt = base_order_usdt
                if initial_price > 0:
                    total_drop = (initial_price - current_price) / initial_price
                    if total_drop >= drop_threshold_pct:
                        allocated_usdt = base_order_usdt * drop_multiplier
                        logger.info(
                            f"[{symbol}] Queda de {total_drop*100:.2f}% detectada! Multiplicador de queda aplicado: "
                            f"USDT={allocated_usdt:.2f} (Base={base_order_usdt:.2f})"
                        )

                new_qty = allocated_usdt / new_p_buy

                tb_state["p_min"] = new_p_min
                tb_state["p_buy"] = new_p_buy
                tb_state["allocated_usdt"] = allocated_usdt

                # Atualiza ordem no banco
                if order_id:
                    self.order_manager.update_virtual_order(
                        order_id=order_id,
                        trigger_price=new_p_buy,
                        reference_price=new_p_min,
                        quantity=new_qty,
                        usdt_amount=allocated_usdt,
                        notes=f"Histerese aplicada. Novo P_min={new_p_min:.4f}"
                    )
                logger.info(
                    f"[{symbol}] Trailing Buy REAJUSTADO para baixo: Novo P_min={new_p_min:.4f}, Novo P_buy={new_p_buy:.4f}"
                )

        # CENÁRIO 2: O preço repicou e bateu ou superou o gatilho P_buy -> EXECUTAR COMPRA
        elif current_price >= p_buy:
            logger.info(
                f"[{symbol}] DISPARO DE COMPRA! Preço={current_price:.4f} >= P_buy={p_buy:.4f}. Executando Market Buy..."
            )
            allocated_usdt = tb_state.get("allocated_usdt", base_order_usdt)
            qty = allocated_usdt / current_price

            success = self.order_manager.execute_simulated_buy(
                symbol=symbol,
                buy_price=current_price,
                quantity=qty,
                usdt_amount=allocated_usdt,
                order_id=order_id,
                config=config
            )

            # Limpa estado de Trailing Buy ativo
            self.active_trailing_buys.pop(symbol, None)

    def _handle_trailing_stop(self, symbol: str, current_price: float, position: Dict[str, Any], config: Dict[str, Any]):
        """
        Mecânica de Trailing Stop:
        - Rastreia máximas P_max.
        - Quando preço sobe e a distância com o stop respeita a histerese, eleva P_stop = P_max * (1 - delta).
        - P_stop NUNCA desce.
        - Disparo de Saída: Se P_atual <= P_stop (ou gap down), executa venda a mercado imediatamente.
        """
        trailing_stop_delta = config.get("trailing_stop_delta", 0.010)
        sell_hysteresis = config.get("sell_hysteresis", 0.002)

        entry_price = position["entry_price"]
        current_stop = position["trailing_stop_price"]
        highest_price = max(position.get("highest_price", entry_price), current_price)

        # 1. Checa condição de saída por Stop
        if current_price <= current_stop:
            reason = "TRAILING_STOP_TRIGGERED" if current_stop > entry_price else "STOP_LOSS_EXIT"
            logger.info(
                f"[{symbol}] DISPARO DE SAÍDA ({reason})! Preço={current_price:.4f} <= Stop={current_stop:.4f}. "
                f"Fechando posição..."
            )
            self.order_manager.execute_simulated_sell(
                symbol=symbol,
                exit_price=current_price,
                exit_reason=reason
            )
            return

        # 2. Rastreamento e elevação do stop se o preço renovar máxima
        new_stop = highest_price * (1.0 - trailing_stop_delta)

        # O stop NUNCA pode diminuir
        if new_stop > current_stop:
            # Histerese de subida: verifica avanço mínimo
            advance_pct = (new_stop - current_stop) / current_stop if current_stop > 0 else 0
            if advance_pct >= sell_hysteresis:
                db.update_position_price(symbol, current_price, new_trailing_stop=new_stop)
                self.order_manager.notify_stop_updated(symbol, current_price, new_stop, highest_price)
                logger.info(
                    f"[{symbol}] Trailing Stop ELEVADO para {new_stop:.4f} (Máxima={highest_price:.4f}, +{advance_pct*100:.2f}%)"
                )
            else:
                db.update_position_price(symbol, current_price)
        else:
            db.update_position_price(symbol, current_price)

    def cancel_trailing_buy(self, symbol: str):
        """Cancela ordem de trailing buy ativa."""
        if symbol in self.active_trailing_buys:
            order_id = self.active_trailing_buys[symbol].get("order_id")
            if order_id:
                self.order_manager.update_virtual_order(order_id, status="CANCELLED")
            self.active_trailing_buys.pop(symbol, None)
            logger.info(f"[{symbol}] Ordem de Trailing Buy cancelada.")
