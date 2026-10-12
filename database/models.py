from datetime import datetime, timezone
import json
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

    # Alocação Financeira & Risco (RF-RISCO-002 a 006)
    base_order_usdt = Column(Float, default=50.0)           # valor_ordem_inicial_usdt
    max_order_amount_usdt = Column(Float, default=150.0)    # valor_maximo_por_entrada_usdt
    max_asset_allocation_usdt = Column(Float, default=250.0)# exposicao_maxima_por_ativo_usdt
    max_total_open_capital_usdt = Column(Float, default=1000.0)
    max_entries_count = Column(Integer, default=5)          # quantidade_maxima_de_entradas

    # Escalonamento de Entrada / Aumento Progressivo de Exposição (substitui Martingale - RF-RISCO-001)
    drop_multiplier = Column(Float, default=1.25)           # multiplicador_entrada
    drop_threshold_pct = Column(Float, default=0.015)       # queda_minima_nova_entrada (1.5%)

    timeframe = Column(String(10), default="1m")
    can_buy = Column(Boolean, default=True, nullable=False)
    execution_mode = Column(String(20), default="PAPER")  # 'PAPER' ou 'REAL'

    # Parada de Emergência (Kill Switch) & Modo Seguro (RF-KILL / RF-14)
    kill_switch_active = Column(Boolean, default=False, nullable=False)
    kill_switch_mode = Column(String(30), default="PARADA_OPERACIONAL") # 'PARADA_OPERACIONAL' ou 'PARADA_COM_ENCERRAMENTO'
    safe_mode_active = Column(Boolean, default=False, nullable=False)
    safe_mode_reason = Column(String(255), default="")

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
            "max_order_amount_usdt": self.max_order_amount_usdt if hasattr(self, "max_order_amount_usdt") else 150.0,
            "max_asset_allocation_usdt": self.max_asset_allocation_usdt,
            "max_total_open_capital_usdt": self.max_total_open_capital_usdt,
            "max_entries_count": self.max_entries_count if hasattr(self, "max_entries_count") else 5,
            "drop_multiplier": self.drop_multiplier,
            "drop_threshold_pct": self.drop_threshold_pct,
            "timeframe": self.timeframe or "1m",
            "kill_switch_active": bool(self.kill_switch_active) if hasattr(self, "kill_switch_active") else False,
            "kill_switch_mode": self.kill_switch_mode if hasattr(self, "kill_switch_mode") else "PARADA_OPERACIONAL",
            "safe_mode_active": bool(self.safe_mode_active) if hasattr(self, "safe_mode_active") else False,
            "safe_mode_reason": self.safe_mode_reason if hasattr(self, "safe_mode_reason") else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class Position(Base):
    """
    Entidade de Posição com Máquina de Estados Explícita (RF-ESTADO-001)
    Estados: SEM_POSICAO, AGUARDANDO_ENTRADA, ENTRADA_DISPARADA, ABERTA, PROTECAO_ATIVA, SAIDA_DISPARADA, ENCERRANDO, ENCERRADA, ERRO, RECUPERACAO
    """
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    status = Column(String(20), default="OPEN", index=True)  # OPEN, CLOSED (retrocompatibilidade)
    state = Column(String(30), default="PROTECAO_ATIVA", index=True) # RF-ESTADO-001
    side = Column(String(10), default="BUY")
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    total_invested_usdt = Column(Float, nullable=False)
    trailing_stop_price = Column(Float, nullable=False)
    highest_price = Column(Float, nullable=False)
    unrealized_pnl_usdt = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)
    entry_count = Column(Integer, default=1) # Número de entradas acumuladas
    trade_id = Column(Integer, nullable=True, index=True) # Vínculo com entidade Trade (RF-TRADE-001)
    opened_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, nullable=True)

    asset = relationship("Asset", back_populates="positions")

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status,
            "state": self.state or ("PROTECAO_ATIVA" if self.status == "OPEN" else "ENCERRADA"),
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "entry_price": round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "total_invested_usdt": round(self.total_invested_usdt, 2),
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "highest_price": round(self.highest_price, 4),
            "unrealized_pnl_usdt": round(self.unrealized_pnl_usdt, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "entry_count": self.entry_count or 1,
            "trade_id": self.trade_id,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }

class PositionTransition(Base):
    """Registro de auditoria para transições de estado da posição (RF-ESTADO-003)"""
    __tablename__ = "position_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    previous_state = Column(String(30), nullable=False)
    new_state = Column(String(30), nullable=False)
    reason = Column(Text, nullable=False)
    price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    order_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "position_id": self.position_id,
            "symbol": self.symbol,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "reason": self.reason,
            "price": self.price,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Order(Base):
    """Entidade Ordem com Idempotência e Rastreabilidade Externa (RF-IDEMP-001 / RF-TRADE-001)"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    client_order_id = Column(String(64), unique=True, nullable=True, index=True) # Identificador externo/negócio
    idempotency_key = Column(String(64), nullable=True, index=True) # Chave para evitar reprocessamento
    trade_id = Column(Integer, nullable=True, index=True) # Vínculo com Trade
    order_type = Column(String(30), nullable=False)  # TRAILING_BUY, TRAILING_STOP, MARKET_BUY, MARKET_SELL
    side = Column(String(10), nullable=False)        # BUY, SELL
    status = Column(String(20), default="ARMED", index=True)  # ARMED, PENDING, SUBMITTED, FILLED, CANCELLED, TRIGGERED, REJECTED
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
            "client_order_id": self.client_order_id,
            "idempotency_key": self.idempotency_key,
            "trade_id": self.trade_id,
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

class Execution(Base):
    """Entidade Execução: Resultado efetivamente executado pela corretora ou motor de simulação (RF-TRADE-001)"""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    trade_id = Column(Integer, nullable=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    binance_execution_id = Column(String(64), nullable=True)
    side = Column(String(10), nullable=False) # BUY, SELL
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    quote_quantity = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    commission_asset = Column(String(10), default="USDT")
    is_simulated = Column(Boolean, default=True)
    executed_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "binance_execution_id": self.binance_execution_id,
            "side": self.side,
            "price": round(self.price, 4),
            "quantity": round(self.quantity, 6),
            "quote_quantity": round(self.quote_quantity, 2),
            "commission": round(self.commission, 6),
            "commission_asset": self.commission_asset,
            "is_simulated": self.is_simulated,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None
        }

class Trade(Base):
    """Entidade Trade: Conjunto lógico de entradas e saídas que representam uma operação completa (RF-TRADE-001/002)"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), ForeignKey("assets.symbol"), nullable=False, index=True)
    status = Column(String(20), default="OPEN", index=True) # OPEN, CLOSED
    entry_count = Column(Integer, default=1)
    total_quantity = Column(Float, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    total_invested_usdt = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    return_usdt = Column(Float, nullable=True)
    realized_pnl_usdt = Column(Float, nullable=True)
    realized_pnl_pct = Column(Float, nullable=True)
    exit_reason = Column(String(100), default="TRAILING_STOP_TRIGGERED")
    duration_seconds = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status,
            "entry_count": self.entry_count,
            "total_quantity": round(self.total_quantity, 6) if self.total_quantity else 0.0,
            "avg_entry_price": round(self.avg_entry_price, 4) if self.avg_entry_price else 0.0,
            "total_invested_usdt": round(self.total_invested_usdt, 2) if self.total_invested_usdt else 0.0,
            "exit_price": round(self.exit_price, 4) if self.exit_price else None,
            "return_usdt": round(self.return_usdt, 2) if self.return_usdt else None,
            "realized_pnl_usdt": round(self.realized_pnl_usdt, 2) if self.realized_pnl_usdt else None,
            "realized_pnl_pct": round(self.realized_pnl_pct, 2) if self.realized_pnl_pct else None,
            "exit_reason": self.exit_reason,
            "duration_seconds": round(self.duration_seconds, 1) if self.duration_seconds else 0.0,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }

class TradeLog(Base):
    """Compatibilidade com modelo TradeLog pré-existente"""
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

class TrailingState(Base):
    """Persistência do Estado das Estratégias de Trailing Buy e Trailing Stop (RF-TRAIL-001 a 005)"""
    __tablename__ = "trailing_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    trailing_type = Column(String(20), nullable=False)  # 'BUY' ou 'STOP'
    is_active = Column(Boolean, default=True, nullable=False)
    reference_price = Column(Float, nullable=False)    # P_min ou P_max
    trigger_price = Column(Float, nullable=False)      # P_buy ou P_stop
    initial_trigger_price = Column(Float, nullable=True) # Preço na armação inicial
    delta = Column(Float, nullable=False)
    hysteresis = Column(Float, default=0.002)
    allocated_usdt = Column(Float, default=50.0)
    entry_count = Column(Integer, default=1)
    order_id = Column(Integer, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "trailing_type": self.trailing_type,
            "is_active": self.is_active,
            "reference_price": round(self.reference_price, 4),
            "trigger_price": round(self.trigger_price, 4),
            "initial_trigger_price": round(self.initial_trigger_price, 4) if self.initial_trigger_price else None,
            "delta": self.delta,
            "hysteresis": self.hysteresis,
            "allocated_usdt": round(self.allocated_usdt, 2),
            "entry_count": self.entry_count,
            "order_id": self.order_id,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class EventLog(Base):
    """Registro Centralizado de Eventos e Auditoria (RF-EVENT-001 a 004)"""
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # BOT_INICIADO, SINAL_COMPRA_GERADO, etc.
    level = Column(String(20), default="INFO", index=True)       # INFO, WARNING, ERROR, CRITICAL
    symbol = Column(String(20), nullable=True, index=True)
    position_id = Column(Integer, nullable=True)
    order_id = Column(Integer, nullable=True)
    trade_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # JSON estruturado com dados adicionais

    def to_dict(self):
        parsed_details = None
        if self.details:
            try:
                parsed_details = json.loads(self.details)
            except Exception:
                parsed_details = self.details
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_type": self.event_type,
            "level": self.level,
            "symbol": self.symbol,
            "position_id": self.position_id,
            "order_id": self.order_id,
            "trade_id": self.trade_id,
            "message": self.message,
            "details": parsed_details
        }
