import unittest
import pandas as pd
import numpy as np

from core.indicators import TechnicalIndicators
from config import Config
from database.db_handler import db
from core.order_manager import OrderManager
from core.strategy_engine import StrategyEngine

class TestCryptoBot(unittest.TestCase):
    def setUp(self):
        self.order_manager = OrderManager(socketio_emitter=lambda e, d: None)
        self.strategy = StrategyEngine(order_manager=self.order_manager)

    def test_wilder_rsi_and_bb(self):
        # Gera série sintética de 100 preços
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
        sym = "BTCUSDT"

        # Persiste parâmetros no banco para o teste
        test_params = {
            "trailing_buy_delta": 0.01,  # 1%
            "buy_hysteresis": 0.002,      # 0.2%
            "trailing_stop_delta": 0.02, # 2%
            "sell_hysteresis": 0.002,     # 0.2%
            "base_order_usdt": 100.0,
            "activation_trigger": "or",
            "rsi_oversold": 30.0,
            "can_buy": True,
            "is_bot_running": True
        }
        db.update_config(sym, test_params)

        # Limpa ordens e posições anteriores do ativo
        db.cancel_active_orders(sym)
        while True:
            existing_pos = db.get_open_position(sym)
            if not existing_pos:
                break
            db.close_position(sym, existing_pos["current_price"], "CLEANUP")

        # 1. Condição de sobrevenda: Preço=90, BB_Lower=95, RSI=25 -> Ativa Trailing Buy
        ind_oversold = {"rsi": 25.0, "bb_lower": 95.0, "bb_middle": 100.0, "bb_upper": 105.0}
        self.strategy.evaluate_tick(sym, 90.0, ind_oversold)

        self.assertIn(sym, self.strategy.active_trailing_buys)
        tb_state = self.strategy.active_trailing_buys[sym]
        self.assertEqual(tb_state["p_min"], 90.0)
        # P_buy = 90 * (1 + 0.01) = 90.9
        self.assertAlmostEqual(tb_state["p_buy"], 90.9, places=2)
        print(f"[TEST PASS] Trailing Buy armado em P_buy={tb_state['p_buy']}")

        # 2. Preço cai para 88.0 (queda > histerese) -> Reajusta P_min e P_buy
        self.strategy.evaluate_tick(sym, 88.0, ind_oversold)
        tb_state = self.strategy.active_trailing_buys[sym]
        self.assertEqual(tb_state["p_min"], 88.0)
        # Novo P_buy = 88 * 1.01 = 88.88
        self.assertAlmostEqual(tb_state["p_buy"], 88.88, places=2)
        print(f"[TEST PASS] Trailing Buy ajustado com histerese para P_buy={tb_state['p_buy']}")

        # 3. Preço repica para 89.0 (atinge ou supera 88.88) -> Dispara Compra!
        self.strategy.evaluate_tick(sym, 89.0, ind_oversold)
        self.assertNotIn(sym, self.strategy.active_trailing_buys)

        pos = db.get_open_position(sym)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["status"], "OPEN")
        self.assertEqual(pos["entry_price"], 89.0)
        # Stop inicial = 89.0 * (1 - 0.02) = 87.22
        self.assertAlmostEqual(pos["trailing_stop_price"], 87.22, places=2)
        print(f"[TEST PASS] Compra simulada executada @ ${pos['entry_price']}. Stop inicial: ${pos['trailing_stop_price']}")

        # 4. Preço sobe para 100.0 -> Trailing Stop deve subir
        ind_normal = {"rsi": 60.0, "bb_lower": 85.0, "bb_middle": 95.0, "bb_upper": 105.0}
        self.strategy.evaluate_tick(sym, 100.0, ind_normal)
        pos = db.get_open_position(sym)
        # Novo stop = 100.0 * (1 - 0.02) = 98.0
        self.assertAlmostEqual(pos["trailing_stop_price"], 98.0, places=2)
        print(f"[TEST PASS] Trailing Stop elevado para ${pos['trailing_stop_price']}")

        # 5. Preço recua para 98.5 (stop continua 98.0, NUNCA DESCE)
        self.strategy.evaluate_tick(sym, 98.5, ind_normal)
        pos = db.get_open_position(sym)
        self.assertAlmostEqual(pos["trailing_stop_price"], 98.0, places=2)
        print(f"[TEST PASS] Stop mantido fixo (não desce): ${pos['trailing_stop_price']}")

        # 6. Preço cai para 97.5 (abaixo de 98.0) -> Dispara Stop de Saída!
        self.strategy.evaluate_tick(sym, 97.5, ind_normal)
        pos = db.get_open_position(sym)
        self.assertIsNone(pos)  # Posição fechada
        trades = db.get_trade_logs(sym, limit=1)
        self.assertEqual(len(trades), 1)
        last_trade = trades[0]
        self.assertEqual(last_trade["buy_price"], 89.0)
        self.assertEqual(last_trade["sell_price"], 97.5)
        self.assertTrue(last_trade["pnl_usdt"] > 0)
        print(f"[TEST PASS] Saída executada com sucesso! PnL={last_trade['pnl_usdt']} USDT ({last_trade['pnl_pct']}%)")

if __name__ == "__main__":
    unittest.main()
