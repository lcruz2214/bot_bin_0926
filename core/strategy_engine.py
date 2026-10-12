import logging
from typing import Dict, Optional, Tuple, Any
from database.db_handler import db

logger = logging.getLogger(__name__)

class StrategyEngine:
    """
    Motor da Estratégia Quantitativa (RF-RISCO, RF-ESTADO, RF-TRAIL, RF-EXPLAIN)
    Implementa:
    1. Trailing Buy com sobrevenda (RSI e/ou BB Inferior), histerese e persistência de estado (RF-TRAIL-001);
    2. Aumento Progressivo de Exposição / Escalonamento de Entrada com limites estritos (RF-RISCO-001 a 008);
    3. Trailing Stop com rastreamento contínuo, avanço de máximas e trava estrita de descida (RF-TRAIL-002/003);
    4. Modo Explicar (RF-EXPLAIN-001 a 004) para diagnóstico em linguagem humana.
    """

    def __init__(self, order_manager):
        self.order_manager = order_manager
        # Estado em memória de ordens ativas de trailing buy:
        # { "BTCUSDT": { "p_min": float, "initial_trigger_price": float, "p_buy": float, "order_id": int, "entry_number": int } }
        self.active_trailing_buys: Dict[str, Dict[str, Any]] = {}

    def check_activation_condition(self, price: float, indicators: Dict[str, Optional[float]], config: Dict[str, Any]) -> bool:
        """
        Verifica se a condição de ativação configurada foi atendida:
        - 'or' (padrão): Preço <= BB Inferior OU RSI <= Sobrevenda
        - 'rsi': Apenas RSI <= Sobrevenda
        - 'bb_lower': Apenas Preço <= BB Inferior
        - 'and': Preço <= BB Inferior E RSI <= Sobrevenda simultaneamente
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
            return rsi_condition or bb_condition
        elif trigger_mode == "rsi":
            return rsi_condition
        elif trigger_mode == "bb_lower":
            return bb_condition
        elif trigger_mode in ("and",):
            return rsi_condition and bb_condition
        return False

    def evaluate_tick(self, symbol: str, current_price: float, indicators: Dict[str, Optional[float]]):
        """
        Avalia o preço e indicadores em tempo real para um ativo.
        Controla transições de estado da posição e saídas mesmo se compras estiverem pausadas.
        """
        config = db.get_config(symbol)
        if not config or not config.get("is_bot_running", True):
            return

        # 1. Verifica se já existe uma posição aberta para este ativo
        open_position = db.get_open_position(symbol)

        if open_position:
            # Ativo comprado -> Gerenciar Trailing Stop e Saída (sempre ativo para proteção de capital)
            self._handle_trailing_stop(symbol, current_price, open_position, config)

            # Escalonamento de Entrada / Aumento Progressivo de Exposição (RF-RISCO-001 a 008)
            can_buy = config.get("can_buy", True)
            if can_buy:
                self._handle_scaling_entry(symbol, current_price, indicators, open_position, config)
            else:
                if symbol in self.active_trailing_buys:
                    self.cancel_trailing_buy(symbol)
        else:
            # Ativo sem posição aberta -> Gerenciar Condição de Entrada Inicial se compras permitidas
            can_buy = config.get("can_buy", True)
            if can_buy:
                self._handle_trailing_buy(symbol, current_price, indicators, config, entry_number=1)
            else:
                if symbol in self.active_trailing_buys:
                    self.cancel_trailing_buy(symbol)

    def _handle_scaling_entry(self, symbol: str, current_price: float, indicators: Dict[str, Optional[float]],
                              open_position: Dict[str, Any], config: Dict[str, Any]):
        """
        Gerencia entradas adicionais (Aumento Progressivo de Exposição / Escalonamento - RF-RISCO):
        - Exige queda mínima (RF-RISCO-007) em relação ao preço médio de entrada.
        - Respeita limite máximo de entradas (RF-RISCO-006).
        - Aplica multiplicador e limita pelo teto individual e teto por ativo (RF-RISCO-004/005).
        """
        current_entries = open_position.get("entry_count", 1)
        max_entries = config.get("max_entries_count", 5)

        # Se já atingiu a quantidade máxima de entradas permitidas, bloqueia (RF-RISCO-006)
        if current_entries >= max_entries:
            return

        drop_threshold_pct = config.get("drop_threshold_pct", 0.015)
        entry_price = open_position["entry_price"]

        # Calcula percentual de queda em relação ao preço médio
        drop_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0

        # Só avalia gatilho se o preço apresentar a queda mínima configurada (RF-RISCO-007)
        if drop_pct >= drop_threshold_pct:
            next_entry_number = current_entries + 1
            self._handle_trailing_buy(
                symbol, current_price, indicators, config,
                entry_number=next_entry_number,
                ref_price_for_scaling=entry_price
            )

    def _handle_trailing_buy(self, symbol: str, current_price: float, indicators: Dict[str, Optional[float]],
                             config: Dict[str, Any], entry_number: int = 1, ref_price_for_scaling: float = None):
        """
        Mecânica de Trailing Buy com persistência de estado (RF-TRAIL-001):
        - Ativação por sobrevenda.
        - Cálculo de volume escalonado (Aumento Progressivo de Exposição).
        - Trava de limite máximo por entrada (RF-RISCO-004).
        - Reajuste por histerese se o preço continuar caindo.
        - Disparo de compra no repique (P_atual >= P_buy).
        """
        trailing_buy_delta = config.get("trailing_buy_delta", 0.005)
        buy_hysteresis = config.get("buy_hysteresis", 0.002)
        base_order_usdt = config.get("base_order_usdt", 50.0)
        drop_multiplier = config.get("drop_multiplier", 1.25)
        max_order_amount = config.get("max_order_amount_usdt", 150.0)

        # Cálculo do valor da entrada com multiplicador de escala (RF-RISCO-003)
        multiplier_factor = drop_multiplier ** (entry_number - 1)
        calculated_amount = base_order_usdt * multiplier_factor
        # Aplica teto máximo por entrada (RF-RISCO-004)
        target_amount_usdt = min(calculated_amount, max_order_amount)

        tb_state = self.active_trailing_buys.get(symbol)

        # Se ainda não existe ordem de Trailing Buy ativa para este símbolo
        if not tb_state:
            # Verifica condição de ativação (RSI / BB Inferior)
            if self.check_activation_condition(current_price, indicators, config):
                p_min = current_price
                p_buy = p_min * (1.0 + trailing_buy_delta)
                qty = target_amount_usdt / p_buy

                # Cria ordem virtual no banco
                order = self.order_manager.create_virtual_order(
                    symbol=symbol,
                    order_type="TRAILING_BUY",
                    side="BUY",
                    trigger_price=p_buy,
                    reference_price=p_min,
                    quantity=qty,
                    usdt_amount=target_amount_usdt,
                    notes=f"Trailing Buy #{entry_number} armado: RSI={indicators.get('rsi')}, BB_Low={indicators.get('bb_lower')}"
                )

                # Persiste estado do Trailing Buy no banco (RF-TRAIL-001)
                db.save_trailing_state(
                    symbol=symbol,
                    trailing_type="BUY",
                    reference_price=p_min,
                    trigger_price=p_buy,
                    delta=trailing_buy_delta,
                    hysteresis=buy_hysteresis,
                    allocated_usdt=target_amount_usdt,
                    entry_count=entry_number,
                    initial_trigger_price=current_price,
                    order_id=order["id"] if order else None
                )

                self.active_trailing_buys[symbol] = {
                    "p_min": p_min,
                    "initial_trigger_price": current_price,
                    "p_buy": p_buy,
                    "order_id": order["id"] if order else None,
                    "allocated_usdt": target_amount_usdt,
                    "entry_number": entry_number
                }

                logger.info(
                    f"[{symbol}] Trailing Buy #{entry_number} ARMADO! P_min={p_min:.4f}, "
                    f"P_buy={p_buy:.4f} (+{trailing_buy_delta*100:.2f}%), Alocação=${target_amount_usdt:.2f}"
                )
            return

        # Já existe Trailing Buy ativo:
        p_min = tb_state["p_min"]
        p_buy = tb_state["p_buy"]
        order_id = tb_state["order_id"]
        current_entry_num = tb_state.get("entry_number", entry_number)

        # CENÁRIO 1: O preço continua caindo abaixo de P_min
        if current_price < p_min:
            rel_distance = (p_buy - current_price) / current_price if current_price > 0 else 0

            # Lógica de Histerese: só ajusta se a distância for maior ou igual à histerese
            if rel_distance >= buy_hysteresis:
                new_p_min = current_price
                new_p_buy = new_p_min * (1.0 + trailing_buy_delta)
                new_qty = target_amount_usdt / new_p_buy

                tb_state["p_min"] = new_p_min
                tb_state["p_buy"] = new_p_buy
                tb_state["allocated_usdt"] = target_amount_usdt

                # Atualiza ordem no banco
                if order_id:
                    self.order_manager.update_virtual_order(
                        order_id=order_id,
                        trigger_price=new_p_buy,
                        reference_price=new_p_min,
                        quantity=new_qty,
                        usdt_amount=target_amount_usdt,
                        notes=f"Histerese aplicada. Novo P_min={new_p_min:.4f}"
                    )

                # Atualiza persistência do Trailing State (RF-TRAIL-004)
                db.save_trailing_state(
                    symbol=symbol,
                    trailing_type="BUY",
                    reference_price=new_p_min,
                    trigger_price=new_p_buy,
                    delta=trailing_buy_delta,
                    hysteresis=buy_hysteresis,
                    allocated_usdt=target_amount_usdt,
                    entry_count=current_entry_num,
                    order_id=order_id
                )

                logger.info(
                    f"[{symbol}] Trailing Buy #{current_entry_num} REAJUSTADO para baixo: "
                    f"Novo P_min={new_p_min:.4f}, Novo P_buy={new_p_buy:.4f}"
                )

        # CENÁRIO 2: O preço repicou e bateu ou superou o gatilho P_buy -> EXECUTAR COMPRA
        elif current_price >= p_buy:
            logger.info(
                f"[{symbol}] DISPARO DE COMPRA #{current_entry_num}! Preço={current_price:.4f} >= P_buy={p_buy:.4f}. Executando..."
            )
            allocated_usdt = tb_state.get("allocated_usdt", target_amount_usdt)
            qty = allocated_usdt / current_price

            success = self.order_manager.execute_simulated_buy(
                symbol=symbol,
                buy_price=current_price,
                quantity=qty,
                usdt_amount=allocated_usdt,
                order_id=order_id,
                config=config,
                entry_number=current_entry_num
            )

            # Limpa estado de Trailing Buy ativo em memória e no banco
            self.active_trailing_buys.pop(symbol, None)
            db.clear_trailing_state(symbol)

    def _handle_trailing_stop(self, symbol: str, current_price: float, position: Dict[str, Any], config: Dict[str, Any]):
        """
        Mecânica de Trailing Stop (RF-TRAIL-002 / 003):
        - Rastreia máximas P_max.
        - Eleva Stop P_stop = P_max * (1 - delta) respeitando histerese.
        - Stop NUNCA retrocede: novo_stop >= stop_anterior.
        - Disparo imediato se P_atual <= P_stop.
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
                f"[{symbol}] DISPARO DE SAÍDA ({reason})! Preço={current_price:.4f} <= Stop={current_stop:.4f}. Fechando posição..."
            )
            self.order_manager.execute_simulated_sell(
                symbol=symbol,
                exit_price=current_price,
                exit_reason=reason
            )
            return

        # 2. Rastreamento e elevação do stop se o preço renovar máxima
        new_stop = highest_price * (1.0 - trailing_stop_delta)

        # Trava estrita: o stop NUNCA pode diminuir (RF-TRAIL-003)
        if new_stop > current_stop:
            advance_pct = (new_stop - current_stop) / current_stop if current_stop > 0 else 0
            if advance_pct >= sell_hysteresis:
                db.update_position_price(symbol, current_price, new_trailing_stop=new_stop)
                self.order_manager.notify_stop_updated(symbol, current_price, new_stop, highest_price)

                # Persiste estado do Trailing Stop (RF-TRAIL-002)
                db.save_trailing_state(
                    symbol=symbol,
                    trailing_type="STOP",
                    reference_price=highest_price,
                    trigger_price=new_stop,
                    delta=trailing_stop_delta,
                    hysteresis=sell_hysteresis
                )

                logger.info(
                    f"[{symbol}] Trailing Stop ELEVADO para {new_stop:.4f} (Máxima={highest_price:.4f}, +{advance_pct*100:.2f}%)"
                )
            else:
                db.update_position_price(symbol, current_price)
        else:
            db.update_position_price(symbol, current_price)

    def cancel_trailing_buy(self, symbol: str):
        """Cancela ordem de trailing buy ativa e limpa persistência."""
        if symbol in self.active_trailing_buys:
            order_id = self.active_trailing_buys[symbol].get("order_id")
            if order_id:
                self.order_manager.update_virtual_order(order_id, status="CANCELLED")
            self.active_trailing_buys.pop(symbol, None)
            db.clear_trailing_state(symbol)
            logger.info(f"[{symbol}] Ordem de Trailing Buy cancelada.")

    # ==========================================
    # MODO EXPLICAR (RF-EXPLAIN-001 a 004)
    # ==========================================
    def explain_decision(self, symbol: str, current_price: float = None, indicators: Dict[str, Optional[float]] = None) -> Dict[str, Any]:
        """
        Retorna explicação clara em linguagem humana do motivo da decisão atual sem alterar lógica (RF-EXPLAIN-001 a 004).
        """
        sym = symbol.upper().strip()
        config = db.get_config(sym)
        pos = db.get_open_position(sym)
        tb_state = self.active_trailing_buys.get(sym)
        op_status = db.get_operational_status()

        rsi = indicators.get("rsi") if indicators else None
        bb_lower = indicators.get("bb_lower") if indicators else None
        bb_upper = indicators.get("bb_upper") if indicators else None
        rsi_limit = config.get("rsi_oversold", 30.0)
        trigger_mode = config.get("activation_trigger", "or")

        explanation = {
            "symbol": sym,
            "operational_status": op_status["status"],
            "has_open_position": pos is not None,
            "has_active_trailing_buy": tb_state is not None,
            "current_price": current_price,
            "rsi": rsi,
            "bb_lower": bb_lower,
            "summary": "",
            "details": []
        }

        # 1. Se em estado de emergência ou modo seguro
        if not op_status["can_operate"] or not op_status["can_buy"]:
            explanation["summary"] = f"Operação bloqueada pela hierarquia de segurança: {op_status['label']}."
            explanation["details"].append(f"Motivo operacional: {op_status['status']} ativo.")
            return explanation

        # 2. Se existe posição aberta
        if pos:
            entry = pos["entry_price"]
            stop = pos["trailing_stop_price"]
            highest = pos.get("highest_price", entry)
            pnl_pct = pos.get("unrealized_pnl_pct", 0.0)
            entry_count = pos.get("entry_count", 1)
            max_entries = config.get("max_entries_count", 5)

            explanation["summary"] = (
                f"Posição em monitoramento de saída (Trailing Stop). Posição aberta #{entry_count} "
                f"com PnL de {pnl_pct:+.2f}%. Stop posicionado em ${stop:.4f} (Máxima: ${highest:.4f})."
            )
            explanation["details"].append(f"Preço de entrada médio: ${entry:.4f}.")
            explanation["details"].append(f"Distância para o Stop: {((current_price - stop) / current_price * 100):.2f}%" if current_price else "-")

            if entry_count < max_entries:
                drop_needed = config.get("drop_threshold_pct", 0.015)
                current_drop = (entry - current_price) / entry if (current_price and entry > 0) else 0
                if current_drop >= drop_needed:
                    explanation["details"].append(
                        f"Condição de escalonamento (#{entry_count+1}): Queda de {current_drop*100:.2f}% atingiu o limiar mínimo de {drop_needed*100:.2f}%."
                    )
                else:
                    explanation["details"].append(
                        f"Escalonamento #{entry_count+1} aguardando queda mínima de {drop_needed*100:.2f}% (queda atual: {current_drop*100:.2f}%)."
                    )
            else:
                explanation["details"].append(f"Limite máximo de entradas ({max_entries}) já atingido. Nenhuma nova compra autorizada.")
            return explanation

        # 3. Se existe Trailing Buy armado
        if tb_state:
            p_min = tb_state["p_min"]
            p_buy = tb_state["p_buy"]
            entry_num = tb_state.get("entry_number", 1)
            explanation["summary"] = (
                f"Trailing Buy #{entry_num} armado e monitorando repique. "
                f"Mínima rastreada (P_min): ${p_min:.4f}. Gatilho de disparo (P_buy): ${p_buy:.4f}."
            )
            if current_price:
                dist = (p_buy - current_price) / current_price * 100
                explanation["details"].append(f"Preço atual ${current_price:.4f} está a {dist:.2f}% do gatilho de compra.")
            return explanation

        # 4. Sem posição e sem trailing buy armado
        if not config.get("can_buy", True):
            explanation["summary"] = f"Compras para o par {sym} estão desativadas pelo usuário no Gerenciador de Pares."
            return explanation

        rsi_met = (rsi is not None and rsi <= rsi_limit)
        bb_met = (bb_lower is not None and current_price is not None and current_price <= bb_lower)

        if trigger_mode == "or":
            condition_text = f"RSI <= {rsi_limit} OU Preço <= Banda Inferior"
        elif trigger_mode == "and":
            condition_text = f"RSI <= {rsi_limit} E Preço <= Banda Inferior simultaneamente"
        elif trigger_mode == "rsi":
            condition_text = f"RSI <= {rsi_limit}"
        else:
            condition_text = "Preço <= Banda Inferior"

        explanation["summary"] = f"Aguardando gatilho de sobrevenda ({condition_text})."
        rsi_str = f"{rsi:.2f}" if rsi is not None else "-"
        cp_str = f"{current_price:.4f}" if current_price is not None else "-"
        bb_str = f"{bb_lower:.4f}" if bb_lower is not None else "-"
        explanation["details"].append(f"RSI atual: {rsi_str} (Limiar de sobrevenda: {rsi_limit}) -> {'ATENDIDO' if rsi_met else 'NÃO atingido'}")
        explanation["details"].append(
            f"Preço atual: ${cp_str} vs Banda Inferior: ${bb_str} -> {'ATENDIDO' if bb_met else 'NÃO atingido'}"
        )

        return explanation
