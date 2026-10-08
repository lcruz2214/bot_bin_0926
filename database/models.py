from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utc_now():
    return datetime.now(timezone.utc)

class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    base_asset = Column(String(10), nullable=False)
    quote_asset = Column(String(10), default="USDT", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    price_precision = Column(Integer, default=4)
    qty_precision = Column(Integer, default=4)
    min_notional = Column(Float, default=5.0)  # Binance $5 min
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    configs = relationship("BotConfig", back_populates="asset", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="asset", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="asset", cascade="all, delete-orphan")
    trades = relationship("TradeLog", back_populates="asset", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "is_active": self.is_active,
            "price_precision": self.price_precision,
            "qty_precision": self.qty_precision,
            "min_notional": self.min_notional
        }

class BotConfig(Base):
    __tablename__ = "bot_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=True, index=True)
    is_global = Column(Boolean, default=False, nullable=False)
    is_bot_running = Column(Boolean, default=True, nullable=False)

    # Parâmetros Técnicos
    rsi_period = Column(Integer, default=14)
    rsi_oversold = Column(Float, default=30.0)
    rsi_overbought = Column(Float, default=70.0)
    bb_period = Column(Integer, default=20)
    bb_std = Column(Float, default=2.0)
    activation_trigger = Column(String(20), default="or")  # 'or', 'rsi', 'bb_lower', 'and'

    # Mecânica Trailing Buy & Trailing Stop
    trailing_buy_delta = Column(Float, default=0.005)      # 0.5%
    buy_hysteresis = Column(Float, default=0.002)          # 0.2%
    trailing_stop_delta = Column(Float, default=0.010)     # 1.0%
    sell_hysteresis = Column(Float, default=0.002)         # 0.2%

    # Alocação Financeira & Risco
    base_order_usdt = Column(Float, default=50.0)
    max_asset_allocation_usdt = Column(Float, default=250.0)
    max_total_open_capital_usdt = Column(Float, default=1000.0)

    # Multiplicador de Queda
    drop_multiplier = Column(Float, default=1.25)
    drop_threshold_pct = Column(Float, default=0.015)      # 1.5%

    timeframe = Column(String(10), default="1m")
    can_buy = Column(Boolean, default=True, nullable=False)
    execution_mode = Column(String(20), default="PAPER")  # 'PAPER' ou 'REAL'
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    asset = relationship("Asset", back_populates="configs")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "is_global": self.is_global,
            "is_bot_running": self.is_bot_running,
            "can_buy": self.can_buy if (hasattr(self, "can_buy") and self.can_buy is not None) else True,
            "execution_mode": self.execution_mode or "PAPER",
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "activation_trigger": self.activation_trigger,
            "trailing_buy_delta": self.trailing_buy_delta,
            "buy_hysteresis": self.buy_hysteresis,
            "trailing_stop_delta": self.trailing_stop_delta,
            "sell_hysteresis": self.sell_hysteresis,
            "base_order_usdt": self.base_order_usdt,
            "max_asset_allocation_usdt": self.max_asset_allocation_usdt,
            "max_total_open_capital_usdt": self.max_total_open_capital_usdt,
            "drop_multiplier": self.drop_multiplier,
            "drop_threshold_pct": self.drop_threshold_pct,
            "timeframe": self.timeframe or "1m",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    status = Column(String(20), default="OPEN", index=True)  # OPEN, CLOSED
    side = Column(String(10), default="BUY")
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    total_invested_usdt = Column(Float, nullable=False)
    trailing_stop_price = Column(Float, nullable=False)
    highest_price = Column(Float, nullable=False)
    unrealized_pnl_usdt = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, nullable=True)

    asset = relationship("Asset", back_populates="positions")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status,
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "entry_price": round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "total_invested_usdt": round(self.total_invested_usdt, 2),
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "highest_price": round(self.highest_price, 4),
            "unrealized_pnl_usdt": round(self.unrealized_pnl_usdt, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    order_type = Column(String(30), nullable=False)  # TRAILING_BUY, TRAILING_STOP, MARKET_BUY, MARKET_SELL
    side = Column(String(10), nullable=False)        # BUY, SELL
    status = Column(String(20), default="ARMED", index=True)  # ARMED, PENDING, FILLED, CANCELLED, TRIGGERED
    trigger_price = Column(Float, nullable=False)    # Preço calculado para ativação
    reference_price = Column(Float, nullable=False)  # Mínima P_min ou Máxima P_max
    executed_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    usdt_amount = Column(Float, nullable=False)
    is_simulated = Column(Boolean, default=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    asset = relationship("Asset", back_populates="orders")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "order_type": self.order_type,
            "side": self.side,
            "status": self.status,
            "trigger_price": round(self.trigger_price, 4) if self.trigger_price else 0.0,
            "reference_price": round(self.reference_price, 4) if self.reference_price else 0.0,
            "executed_price": round(self.executed_price, 4) if self.executed_price else None,
            "quantity": round(self.quantity, 6) if self.quantity else 0.0,
            "usdt_amount": round(self.usdt_amount, 2) if self.usdt_amount else 0.0,
            "is_simulated": self.is_simulated,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    buy_order_id = Column(Integer, nullable=True)
    sell_order_id = Column(Integer, nullable=True)
    buy_price = Column(Float, nullable=False)
    sell_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    invested_usdt = Column(Float, nullable=False)
    return_usdt = Column(Float, nullable=False)
    pnl_usdt = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)
    exit_reason = Column(String(100), default="TRAILING_STOP_TRIGGERED")
    duration_seconds = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, default=utc_now)

    asset = relationship("Asset", back_populates="trades")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_price": round(self.buy_price, 4),
            "sell_price": round(self.sell_price, 4),
            "quantity": round(self.quantity, 6),
            "invested_usdt": round(self.invested_usdt, 2),
            "return_usdt": round(self.return_usdt, 2),
            "pnl_usdt": round(self.pnl_usdt, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "exit_reason": self.exit_reason,
            "duration_seconds": round(self.duration_seconds, 1),
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }
