import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

class TechnicalIndicators:
    @staticmethod
    def calculate_wilder_rsi(close_prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calcula o RSI utilizando exatamente a suavização exponencial de J. Welles Wilder,
        idêntico ao cálculo oficial da Binance e TradingView.
        """
        if len(close_prices) < period + 1:
            return pd.Series(index=close_prices.index, dtype=float)

        delta = close_prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Primeiro valor: média simples dos primeiros 'period' períodos
        avg_gain = pd.Series(index=close_prices.index, dtype=float)
        avg_loss = pd.Series(index=close_prices.index, dtype=float)

        # Média inicial
        first_gain_avg = gain.iloc[1:period + 1].mean()
        first_loss_avg = loss.iloc[1:period + 1].mean()
        
        avg_gain.iloc[period] = first_gain_avg
        avg_loss.iloc[period] = first_loss_avg

        # Suavização de Wilder: (Prev_Avg * (period - 1) + Current) / period
        gain_vals = gain.values
        loss_vals = loss.values
        avg_g_vals = np.full(len(close_prices), np.nan)
        avg_l_vals = np.full(len(close_prices), np.nan)

        avg_g_vals[period] = first_gain_avg
        avg_l_vals[period] = first_loss_avg

        for i in range(period + 1, len(close_prices)):
            avg_g_vals[i] = (avg_g_vals[i - 1] * (period - 1) + gain_vals[i]) / period
            avg_l_vals[i] = (avg_l_vals[i - 1] * (period - 1) + loss_vals[i]) / period

        rs = np.divide(
            avg_g_vals,
            avg_l_vals,
            out=np.zeros_like(avg_g_vals),
            where=avg_l_vals != 0
        )
        
        rsi = np.where(
            avg_l_vals == 0,
            100.0,
            np.where(avg_g_vals == 0, 0.0, 100.0 - (100.0 / (1.0 + rs)))
        )

        return pd.Series(rsi, index=close_prices.index)

    @staticmethod
    def calculate_bollinger_bands(close_prices: pd.Series, period: int = 20, num_std: float = 2.0) -> Dict[str, pd.Series]:
        """
        Calcula as Bandas de Bollinger padrão da Binance (SMA 20 e 2 desvios padrão).
        """
        if len(close_prices) < period:
            nan_s = pd.Series(index=close_prices.index, dtype=float)
            return {"upper": nan_s, "middle": nan_s, "lower": nan_s}

        # SMA da Binance/TradingView
        middle = close_prices.rolling(window=period).mean()
        # Desvio padrão populacional (ddof=0) correspondente a Pine Script ta.stdev / Binance
        std = close_prices.rolling(window=period).std(ddof=0)
        upper = middle + (std * num_std)
        lower = middle - (std * num_std)

        return {
            "upper": upper,
            "middle": middle,
            "lower": lower
        }

    @classmethod
    def compute_all(cls, df: pd.DataFrame, rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0) -> pd.DataFrame:
        """
        Processa um DataFrame contendo coluna 'close' e adiciona as colunas dos indicadores.
        """
        if "close" not in df.columns or len(df) == 0:
            return df

        df = df.copy()
        df["close"] = df["close"].astype(float)
        
        df["rsi"] = cls.calculate_wilder_rsi(df["close"], period=rsi_period)
        
        bb = cls.calculate_bollinger_bands(df["close"], period=bb_period, num_std=bb_std)
        df["bb_upper"] = bb["upper"]
        df["bb_middle"] = bb["middle"]
        df["bb_lower"] = bb["lower"]

        return df

    @classmethod
    def get_latest_indicators(cls, df: pd.DataFrame, rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0) -> Dict[str, Optional[float]]:
        """
        Retorna os valores mais recentes dos indicadores calculados.
        """
        if len(df) < max(rsi_period + 1, bb_period):
            return {
                "rsi": None,
                "bb_upper": None,
                "bb_middle": None,
                "bb_lower": None,
                "close": float(df["close"].iloc[-1]) if len(df) > 0 and "close" in df else None
            }

        df_calc = cls.compute_all(df, rsi_period=rsi_period, bb_period=bb_period, bb_std=bb_std)
        last_row = df_calc.iloc[-1]

        def sanitize(val):
            return None if pd.isna(val) or np.isnan(val) else round(float(val), 4)

        return {
            "close": sanitize(last_row.get("close")),
            "rsi": sanitize(last_row.get("rsi")),
            "bb_upper": sanitize(last_row.get("bb_upper")),
            "bb_middle": sanitize(last_row.get("bb_middle")),
            "bb_lower": sanitize(last_row.get("bb_lower"))
        }
