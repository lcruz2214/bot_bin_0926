import unittest
import pandas as pd
import numpy as np

from core.indicators import TechnicalIndicators
from config import Config
from database.db_handler import db
from core.order_manager import OrderManager
from core.strategy_engine import StrategyEngine
from core.recovery_manager import RecoveryManager
from core.market_stream import BinanceMarketStream

class TestCryptoBot(unittest.TestCase):
    def setUp(self):
        self.order_manager = OrderManager(socketio_emitter=lambda e, d: None)
        self.strategy = StrategyEngine(order_manager=self.order_manager)
        self.market_stream = BinanceMarketStream(symbols=[])
        self.recovery = RecoveryManager(
            order_manager=self.order_manager,
            strategy_engine=self.strategy,
            market_stream=self.market_stream
        )

    def test_wilder_rsi_and_bb(self):
        prices = [100.0 + np.sin(i / 5.0) * 10.0 + (i * 0.1) for i in range(100)]
        df = pd.DataFrame({
            "time": range(100),
            "open": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [1000] * 100
        })

        df_calc = TechnicalIndicators.compute_all(df, rsi_period=14, bb_period=20, bb_std=2.0)
        self.assertIn("rsi", df_calc.columns)
        self.assertIn("bb_upper", df_calc.columns)
        self.assertIn("bb_middle", df_calc.columns)
        self.assertIn("bb_lower", df_calc.columns)

        latest = TechnicalIndicators.get_latest_indicators(df, rsi_period=14, bb_period=20, bb_std=2.0)
        self.assertIsNotNone(latest["rsi"])
        self.assertIsNotNone(latest["bb_middle"])
        self.assertTrue(0 <= latest["rsi"] <= 100)
        self.assertTrue(latest["bb_upper"] >= latest["bb_middle"] >= latest["bb_lower"])
        print(f"[TEST PASS] Indicadores calculados com sucesso: RSI={latest['rsi']}, BB_Mid={latest['bb_middle']}")

    def test_activation_trigger_modes(self):
        """Valida que o gatilho padrão 'or' opera como OR (Banda Inferior OU RSI)"""
        cfg_or = {"activation_trigger": "or", "rsi_oversold": 30.0}
        cfg_rsi = {"activation_trigger": "rsi", "rsi_oversold": 30.0}
        cfg_bb = {"activation_trigger": "bb_lower", "rsi_oversold": 30.0}
        cfg_and = {"activation_trigger": "and", "rsi_oversold": 30.0}

        # Cenário 1: Apenas RSI sobrevendido (RSI=25, Preço=100 > BB=95)
        ind_only_rsi = {"rsi": 25.0, "bb_lower": 95.0}
        self.assertTrue(self.strategy.check_activation_condition(100.0, ind_only_rsi, cfg_or))
        self.assertTrue(self.strategy.check_activation_condition(100.0, ind_only_rsi, cfg_rsi))
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_only_rsi, cfg_bb))
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_only_rsi, cfg_and))

        # Cenário 2: Apenas BB Inferior atingida (RSI=45, Preço=90 <= BB=95)
        ind_only_bb = {"rsi": 45.0, "bb_lower": 95.0}
        self.assertTrue(self.strategy.check_activation_condition(90.0, ind_only_bb, cfg_or))
        self.assertFalse(self.strategy.check_activation_condition(90.0, ind_only_bb, cfg_rsi))
        self.assertTrue(self.strategy.check_activation_condition(90.0, ind_only_bb, cfg_bb))
        self.assertFalse(self.strategy.check_activation_condition(90.0, ind_only_bb, cfg_and))

        # Cenário 3: Nenhum critério atingido (RSI=50, Preço=100 > BB=95)
        ind_none = {"rsi": 50.0, "bb_lower": 95.0}
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_none, cfg_or))
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_none, cfg_rsi))
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_none, cfg_bb))
        self.assertFalse(self.strategy.check_activation_condition(100.0, ind_none, cfg_and))

        # Cenário 4: Ambos atingidos (RSI=20, Preço=90 <= BB=95)
        ind_both = {"rsi": 20.0, "bb_lower": 95.0}
        self.assertTrue(self.strategy.check_activation_condition(90.0, ind_both, cfg_or))
        self.assertTrue(self.strategy.check_activation_condition(90.0, ind_both, cfg_and))
        print("[TEST PASS] Modos de gatilho de ativação (OR, RSI, BB_LOWER, AND) validados com sucesso!")

    def test_trailing_buy_and_trailing_stop_workflow(self):
        sym = "TEST_FLOW_USDT"
        db.add_asset(sym)

        test_params = {
            "trailing_buy_delta": 0.01,  # 1%
            "buy_hysteresis": 0.002,     # 0.2%
            "trailing_stop_delta": 0.02, # 2%
            "sell_hysteresis": 0.002,    # 0.2%
            "base_order_usdt": 100.0,
            "max_order_amount_usdt": 150.0,
            "max_asset_allocation_usdt": 500.0,
            "max_entries_count": 5,
            "activation_trigger": "or",
            "rsi_oversold": 30.0,
            "can_buy": True,
            "is_bot_running": True
        }
        db.update_config(sym, test_params)
        db.cancel_active_orders(sym)
        db.clear_trailing_state(sym)

        while True:
            existing_pos = db.get_open_position(sym)
            if not existing_pos:
                break
            db.close_position(sym, existing_pos["current_price"], "CLEANUP")

        # 1. Ativa Trailing Buy
        ind_oversold = {"rsi": 25.0, "bb_lower": 95.0, "bb_middle": 100.0, "bb_upper": 105.0}
        self.strategy.evaluate_tick(sym, 90.0, ind_oversold)
        self.assertIn(sym, self.strategy.active_trailing_buys)
        tb_state = self.strategy.active_trailing_buys[sym]
        self.assertEqual(tb_state["p_min"], 90.0)
        self.assertAlmostEqual(tb_state["p_buy"], 90.9, places=2)

        # 2. Histerese para baixo
        self.strategy.evaluate_tick(sym, 88.0, ind_oversold)
        tb_state = self.strategy.active_trailing_buys[sym]
        self.assertEqual(tb_state["p_min"], 88.0)
        self.assertAlmostEqual(tb_state["p_buy"], 88.88, places=2)

        # 3. Disparo de compra
        self.strategy.evaluate_tick(sym, 89.0, ind_oversold)
        self.assertNotIn(sym, self.strategy.active_trailing_buys)
        pos = db.get_open_position(sym)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["status"], "OPEN")
        self.assertEqual(pos["entry_price"], 89.0)
        self.assertAlmostEqual(pos["trailing_stop_price"], 87.22, places=2)

        # 4. Elevação do Stop
        ind_normal = {"rsi": 60.0, "bb_lower": 85.0, "bb_middle": 95.0, "bb_upper": 105.0}
        self.strategy.evaluate_tick(sym, 100.0, ind_normal)
        pos = db.get_open_position(sym)
        self.assertAlmostEqual(pos["trailing_stop_price"], 98.0, places=2)

        # 5. Stop fixo (não desce)
        self.strategy.evaluate_tick(sym, 98.5, ind_normal)
        pos = db.get_open_position(sym)
        self.assertAlmostEqual(pos["trailing_stop_price"], 98.0, places=2)

        # 6. Stop disparado
        self.strategy.evaluate_tick(sym, 97.5, ind_normal)
        pos = db.get_open_position(sym)
        self.assertIsNone(pos)
        db.delete_asset(sym)
        print("[TEST PASS] Workflow completo de Trailing Buy e Trailing Stop validado com sucesso!")

    def test_pair_deletion_and_open_position_protection(self):
        """Valida adição e exclusão de pares, impedindo exclusão de ativo com posição aberta (USER REQUEST)."""
        test_sym = "TEST_DEL_USDT"
        db.add_asset(test_sym)
        self.assertIn(test_sym, db.get_active_symbols())

        # 1. Simula abertura de posição para o par
        db.save_position(test_sym, quantity=10.0, entry_price=100.0, trailing_stop_price=98.0)
        self.assertIsNotNone(db.get_open_position(test_sym))

        # 2. Tenta excluir o par com posição aberta -> DEVE SER RECUSADO
        ok, msg = db.delete_asset(test_sym)
        self.assertFalse(ok)
        self.assertIn("posição aberta", msg.lower())
        self.assertIn(test_sym, db.get_active_symbols())

        # 3. Fecha a posição aberta
        db.close_position(test_sym, exit_price=102.0, exit_reason="TEST_CLOSE")
        self.assertIsNone(db.get_open_position(test_sym))

        # 4. Tenta excluir agora que a posição foi encerrada -> DEVE TER SUCESSO
        ok, msg = db.delete_asset(test_sym)
        self.assertTrue(ok)
        self.assertNotIn(test_sym, db.get_active_symbols())
        print(f"[TEST PASS] Exclusão de par validada com proteção contra posição aberta!")

    def test_kill_switch_and_operational_hierarchy(self):
        """Valida a Parada de Emergência (Kill Switch) e Hierarquia Operacional (RF-KILL / RF-14)."""
        db.set_kill_switch(active=True, mode="PARADA_OPERACIONAL", reason="Teste Unitário")
        status = db.get_operational_status()
        self.assertEqual(status["level"], "EMERGENCIA")
        self.assertEqual(status["status"], "KILL_SWITCH")
        self.assertFalse(status["can_buy"])

        cfg = {"max_order_amount_usdt": 150.0, "max_asset_allocation_usdt": 500.0, "max_entries_count": 5}
        allowed, reason = self.order_manager.check_risk_limits("TEST_KS_USDT", requested_amount_usdt=50.0, config=cfg)
        self.assertFalse(allowed)
        self.assertIn("Hierarquia", reason)

        db.set_kill_switch(active=False)
        status_after = db.get_operational_status()
        self.assertNotEqual(status_after["status"], "KILL_SWITCH")
        print("[TEST PASS] Parada de Emergência (Kill Switch) e Hierarquia Operacional validadas com sucesso!")

    def test_progressive_exposure_and_risk_limits(self):
        """Valida limites do Aumento Progressivo de Exposição (RF-RISCO-004, 005, 006)."""
        cfg = {
            "max_order_amount_usdt": 100.0,
            "max_entries_count": 3,
            "max_asset_allocation_usdt": 250.0,
            "max_total_open_capital_usdt": 1000.0
        }

        # 1. Entrada individual excedendo teto de ordem -> Bloqueada (RF-RISCO-004)
        allowed, reason = self.order_manager.check_risk_limits("TEST_RISK_USDT", requested_amount_usdt=150.0, config=cfg, entry_number=1)
        self.assertFalse(allowed)
        self.assertIn("RF-RISCO-004", reason)

        # 2. Entrada dentro dos limites -> Permitida
        allowed, reason = self.order_manager.check_risk_limits("TEST_RISK_USDT", requested_amount_usdt=80.0, config=cfg, entry_number=1)
        self.assertTrue(allowed)

        # 3. Excedendo quantidade máxima de entradas -> Bloqueada (RF-RISCO-006)
        allowed, reason = self.order_manager.check_risk_limits("TEST_RISK_USDT", requested_amount_usdt=80.0, config=cfg, entry_number=4)
        self.assertFalse(allowed)
        self.assertIn("RF-RISCO-006", reason)
        print("[TEST PASS] Limites de Aumento Progressivo de Exposição (RF-RISCO) validados com sucesso!")

    def test_recovery_manager_state_reconstruction(self):
        """Valida que o Gerenciador de Recuperação reconstrói o estado após reinício (RF-REC-002/005)."""
        sym = "TEST_REC_USDT"
        db.add_asset(sym)
        db.cancel_active_orders(sym)

        db.save_position(sym, quantity=2.0, entry_price=3000.0, trailing_stop_price=2940.0)

        db.save_trailing_state(
            sym, trailing_type="BUY", reference_price=2800.0, trigger_price=2820.0,
            delta=0.01, hysteresis=0.002, allocated_usdt=100.0
        )

        self.strategy.active_trailing_buys.clear()

        recovery_results = self.recovery.run_recovery()
        self.assertTrue(recovery_results["recovered_positions"] >= 1)
        self.assertIn(sym, self.strategy.active_trailing_buys)
        recovered_tb = self.strategy.active_trailing_buys[sym]
        self.assertEqual(recovered_tb["p_min"], 2800.0)
        self.assertEqual(recovered_tb["p_buy"], 2820.0)

        db.close_position(sym, exit_price=3050.0, exit_reason="TEST_RECOVERY_CLEANUP")
        db.clear_trailing_state(sym)
        db.delete_asset(sym)
        print("[TEST PASS] Gerenciador de Recuperação (RF-REC) validado com sucesso!")

    def test_explain_decision_mode(self):
        """Valida o Modo Explicar produzindo diagnóstico em linguagem humana sem alterar estado (RF-EXPLAIN)."""
        sym = "TEST_EXP_USDT"
        db.add_asset(sym)
        indicators = {"rsi": 28.5, "bb_lower": 65000.0, "bb_upper": 68000.0}
        exp = self.strategy.explain_decision(sym, current_price=64800.0, indicators=indicators)

        self.assertIn("summary", exp)
        self.assertIn("details", exp)
        self.assertEqual(exp["symbol"], sym)
        self.assertTrue(len(exp["details"]) > 0)
        db.delete_asset(sym)
        print(f"[TEST PASS] Modo Explicar validado com sucesso! Resumo: {exp['summary']}")

    def test_trailing_stop_strictly_never_decreases(self):
        """Valida garantia estrita de que o Stop NUNCA retrocede (RF-TRAIL-003)."""
        sym = "TEST_STOP_USDT"
        db.add_asset(sym)
        db.save_position(sym, quantity=5.0, entry_price=100.0, trailing_stop_price=95.0)

        # Tenta diminuir o stop para 92.0 -> NÃO PODE DIMINUIR
        pos = db.update_position_price(sym, current_price=96.0, new_trailing_stop=92.0)
        self.assertEqual(pos["trailing_stop_price"], 95.0)

        # Tenta elevar o stop para 98.0 -> DEVE SUBIR
        pos = db.update_position_price(sym, current_price=105.0, new_trailing_stop=98.0)
        self.assertEqual(pos["trailing_stop_price"], 98.0)

        db.close_position(sym, exit_price=98.0, exit_reason="TEST_STOP_CLEANUP")
        db.delete_asset(sym)
        print("[TEST PASS] Regra RF-TRAIL-003 garantida: Stop estritamente nunca diminui!")

    def test_excluded_timeframes_and_default_strategy_config(self):
        """Valida que os tempos 1m e 3m foram excluídos e que a configuração padrão de RSI e BB é aplicada com sucesso."""
        # 1. 1m e 3m não podem estar nos timeframes disponíveis
        self.assertNotIn("1m", Config.AVAILABLE_TIMEFRAMES)
        self.assertNotIn("3m", Config.AVAILABLE_TIMEFRAMES)
        self.assertEqual(Config.DEFAULT_TIMEFRAME, "5m")

        # 2. Aplicação de configuração padrão para um par específico
        sym = "TEST_PAD_USDT"
        db.add_asset(sym)
        # Altera para valores não-padrão propositalmente
        db.update_config(sym, {
            "rsi_period": 7,
            "rsi_oversold": 20.0,
            "bb_period": 10,
            "bb_std": 3.0,
            "activation_trigger": "and",
            "timeframe": "15m"
        })

        # Aplica padrão
        res = db.apply_default_strategy_config(sym)
        self.assertEqual(res["rsi_period"], 14)
        self.assertEqual(res["rsi_oversold"], 30.0)
        self.assertEqual(res["bb_period"], 20)
        self.assertEqual(res["bb_std"], 2.0)
        self.assertEqual(res["activation_trigger"], "or")
        self.assertEqual(res["timeframe"], "5m")

        db.delete_asset(sym)
        print("[TEST PASS] Exclusão de 1m/3m e configuração padrão de RSI/BB validados com sucesso!")

if __name__ == "__main__":
    unittest.main()
