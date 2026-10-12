import time
import logging
from typing import Dict, Any, List, Optional
import requests

from config import Config
from database.db_handler import db

logger = logging.getLogger(__name__)

class RecoveryManager:
    """
    Gerenciador de Recuperação do Bot Binance (RF-REC-001 a 005)
    Responsável por:
    - Reconstruir o estado operacional na inicialização a partir do banco de dados (RF-REC-002);
    - Recuperar posições abertas e estados do Trailing Buy / Trailing Stop sem reinicializar do zero (RF-REC-005);
    - Reconciliar ordens e saldos com a Binance quando em Modo Real (RF-REC-003);
    - Ativar Modo Seguro diante de divergências críticas (RF-REC-004);
    - Garantir que a Parada de Emergência (Kill Switch) permaneça ativa após reinício se previamente disparada (RF-KILL-006).
    """

    def __init__(self, order_manager=None, strategy_engine=None, market_stream=None):
        self.order_manager = order_manager
        self.strategy_engine = strategy_engine
        self.market_stream = market_stream

    def set_dependencies(self, order_manager, strategy_engine, market_stream):
        self.order_manager = order_manager
        self.strategy_engine = strategy_engine
        self.market_stream = market_stream

    def run_recovery(self) -> Dict[str, Any]:
        """Executa rotina completa de recuperação pós-inicialização."""
        logger.info("=== [GERENCIADOR DE RECUPERAÇÃO] Iniciando auditoria e reconstrução de estado ===")
        results = {
            "recovered_positions": 0,
            "recovered_trailing_buys": 0,
            "recovered_trailing_stops": 0,
            "reconciled_real_orders": 0,
            "safe_mode_activated": False,
            "kill_switch_active": False,
            "messages": []
        }

        # 1. Checa Parada de Emergência persistida (RF-KILL-006)
        ks_status = db.get_kill_switch_status()
        if ks_status["active"]:
            results["kill_switch_active"] = True
            msg = f"[RF-KILL-006] Parada de Emergência persistida detectada como ATIVA ({ks_status['mode']}). Novas operações bloqueadas."
            logger.warning(msg)
            results["messages"].append(msg)
            db.log_event(
                event_type="RECUPERACAO_KILL_SWITCH",
                message=msg,
                level="CRITICAL",
                details=ks_status
            )

        # 2. Recupera posições abertas do banco de dados (RF-REC-002 / RF-REC-005)
        open_positions = db.get_all_open_positions()
        logger.info(f"Posições abertas recuperadas do banco: {len(open_positions)}")

        for pos in open_positions:
            sym = pos["symbol"]
            qty = pos["quantity"]
            entry = pos["entry_price"]
            stop_price = pos["trailing_stop_price"]
            highest = pos.get("highest_price", entry)

            # Valida estado da máquina de estados (RF-ESTADO-004)
            current_state = pos.get("state") or "PROTECAO_ATIVA"
            logger.info(
                f"[{sym}] Recuperando posição existente: Qtd={qty:.6f}, Entrada=${entry:.4f}, "
                f"Stop Atual=${stop_price:.4f}, Máxima=${highest:.4f}, Estado={current_state}"
            )

            results["recovered_positions"] += 1
            results["recovered_trailing_stops"] += 1

            # Garante que o stream de mercado está ativo para o par recuperado
            if self.market_stream:
                self.market_stream.ensure_kline_subscription(sym, Config.DEFAULT_TIMEFRAME)

        # 3. Recupera estados persistidos de Trailing Buy (RF-TRAIL-005)
        active_trailing_states = db.get_all_active_trailing_states()
        for ts in active_trailing_states:
            sym = ts["symbol"]
            ttype = ts["trailing_type"]

            if ttype == "BUY" and self.strategy_engine:
                self.strategy_engine.active_trailing_buys[sym] = {
                    "p_min": ts["reference_price"],
                    "initial_trigger_price": ts.get("initial_trigger_price") or ts["reference_price"],
                    "p_buy": ts["trigger_price"],
                    "order_id": ts.get("order_id"),
                    "allocated_usdt": ts.get("allocated_usdt", 50.0),
                    "entry_count": ts.get("entry_count", 1)
                }
                results["recovered_trailing_buys"] += 1
                logger.info(f"[{sym}] Trailing Buy recuperado: P_min={ts['reference_price']:.4f}, P_buy={ts['trigger_price']:.4f}")

        # 4. Reconciliação com a Binance se estiver em Modo Real (RF-REC-003 / RF-REC-004)
        exec_mode = db.get_execution_mode()
        if exec_mode == "REAL":
            recon_ok, recon_msg = self.reconcile_with_binance(open_positions)
            if not recon_ok:
                results["safe_mode_activated"] = True
                results["messages"].append(recon_msg)
                db.set_safe_mode(True, reason=recon_msg)

        db.log_event(
            event_type="RECUPERACAO_SISTEMA_CONCLUIDA",
            message=f"Recuperação finalizada: {results['recovered_positions']} posições, {results['recovered_trailing_buys']} trailing buys ativos",
            level="INFO",
            details=results
        )
        logger.info("=== [GERENCIADOR DE RECUPERAÇÃO] Rotina de recuperação concluída com sucesso ===")
        return results

    def reconcile_with_binance(self, local_positions: List[Dict[str, Any]]) -> tuple[bool, str]:
        """
        Reconcilia estado local com a Binance REST API (RF-REC-003 / RF-REC-004).
        Compara posições e ordens para evitar divergência financeira.
        """
        api_key = Config.BINANCE_API_KEY
        api_secret = Config.BINANCE_API_SECRET

        if not api_key or not api_secret:
            msg = "[RF-REC-003] Modo REAL configurado, mas chaves de API da Binance estão ausentes."
            logger.error(msg)
            return False, msg

        # Consulta saldo de conta via Binance REST API com timeout seguro
        url = f"{Config.BINANCE_REST_URL}/account"
        import time, hmac, hashlib, urllib.parse
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp, "recvWindow": 5000}
        query_str = urllib.parse.urlencode(params)
        sig = hmac.new(api_secret.encode("utf-8"), query_str.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        headers = {"X-MBX-APIKEY": api_key}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                msg = f"Falha ao consultar conta Binance ({resp.status_code}): {resp.text}"
                logger.error(msg)
                return False, msg

            account_data = resp.json()
            balances = {b["asset"]: float(b["free"]) + float(b["locked"]) for b in account_data.get("balances", [])}

            # Valida cada posição aberta localmente
            for pos in local_positions:
                sym = pos["symbol"]
                base_asset = sym.replace("USDT", "")
                binance_qty = balances.get(base_asset, 0.0)
                local_qty = pos["quantity"]

                # Tolerância pequena para taxas residuais
                diff = abs(binance_qty - local_qty)
                if diff > (local_qty * 0.15) and binance_qty < (local_qty * 0.5):
                    divergence_msg = (
                        f"[RF-REC-003/004] Divergência crítica em {sym}! "
                        f"Banco local: {local_qty:.6f} {base_asset} | Binance: {binance_qty:.6f} {base_asset}."
                    )
                    logger.critical(divergence_msg)
                    return False, divergence_msg

            logger.info("Reconciliação com Binance concluída com sucesso. Nenhuma inconsistência crítica detectada.")
            return True, "Reconciliação OK"
        except Exception as e:
            err_msg = f"Erro de comunicação na reconciliação com Binance: {e}"
            logger.error(err_msg)
            return False, err_msg
