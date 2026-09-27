import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, desc, func, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

from config import Config
from database.models import Base, Asset, BotConfig, Position, Order, TradeLog

logger = logging.getLogger(__name__)

class DatabaseHandler:
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.db_type = None
        self._setup_engine()

    def _setup_engine(self):
        """Tenta conectar primeiro no PostgreSQL. Se falhar, faz fallback automático para SQLite."""
        try:
            logger.info(f"Tentando conectar ao PostgreSQL em: {Config.POSTGRES_URI}")
            engine = create_engine(
                Config.POSTGRES_URI,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 3}
            )
            # Testa conexão
            with engine.connect() as conn:
                conn.execute(func.now().select())
            self.engine = engine
            self.db_type = "PostgreSQL"
            logger.info("Conexão com PostgreSQL estabelecida com sucesso!")
        except Exception as e:
            logger.warning(
                f"Não foi possível conectar ao PostgreSQL ({e}). "
                f"Utilizando fallback seguro para SQLite local ({Config.SQLITE_URI})."
            )
            self.engine = create_engine(
                Config.SQLITE_URI,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True
            )
            self.db_type = "SQLite (Fallback Seguro)"
            logger.info(f"Banco de dados inicializado em modo: {self.db_type}")

        self.SessionLocal = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        )

    def init_db(self):
        """Cria as tabelas e inicializa dados padrão se vazios."""
        Base.metadata.create_all(bind=self.engine)

        # Migração automática se as colunas execution_mode ou can_buy não existirem na tabela
        try:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE bot_configs ADD COLUMN execution_mode VARCHAR(20) DEFAULT 'PAPER'"))
        except Exception:
            pass  # Coluna já existe

        try:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE bot_configs ADD COLUMN can_buy BOOLEAN DEFAULT 1"))
        except Exception:
            pass  # Coluna já existe

        with self.get_session() as session:
            # Inicializar ativos padrão
            for symbol in Config.AVAILABLE_SYMBOLS:
                asset = session.query(Asset).filter_by(symbol=symbol).first()
                if not asset:
                    base = symbol.replace("USDT", "")
                    asset = Asset(
                        symbol=symbol,
                        base_asset=base,
                        quote_asset="USDT",
                        is_active=True
                    )
                    session.add(asset)
                    session.flush()

                # Inicializar configuração para o ativo
                cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
                if not cfg:
                    cfg = BotConfig(
                        symbol=symbol,
                        is_global=False,
                        is_bot_running=True,
                        can_buy=True,
                        rsi_period=Config.DEFAULT_RSI_PERIOD,
                        rsi_oversold=Config.DEFAULT_RSI_OVERSOLD,
                        rsi_overbought=Config.DEFAULT_RSI_OVERBOUGHT,
                        bb_period=Config.DEFAULT_BB_PERIOD,
                        bb_std=Config.DEFAULT_BB_STD,
                        activation_trigger=Config.DEFAULT_ACTIVATION_TRIGGER,
                        trailing_buy_delta=Config.DEFAULT_TRAILING_BUY_DELTA,
                        buy_hysteresis=Config.DEFAULT_BUY_HYSTERESIS,
                        trailing_stop_delta=Config.DEFAULT_TRAILING_STOP_DELTA,
                        sell_hysteresis=Config.DEFAULT_SELL_HYSTERESIS,
                        base_order_usdt=Config.DEFAULT_BASE_ORDER_USDT,
                        max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                        max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                        drop_multiplier=Config.DEFAULT_DROP_MULTIPLIER,
                        drop_threshold_pct=Config.DEFAULT_DROP_THRESHOLD_PCT,
                        timeframe=Config.DEFAULT_TIMEFRAME
                    )
                    session.add(cfg)

            # Inicializar configuração global
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if not global_cfg:
                global_cfg = BotConfig(
                    symbol=None,
                    is_global=True,
                    is_bot_running=True,
                    can_buy=True,
                    rsi_period=Config.DEFAULT_RSI_PERIOD,
                    rsi_oversold=Config.DEFAULT_RSI_OVERSOLD,
                    rsi_overbought=Config.DEFAULT_RSI_OVERBOUGHT,
                    bb_period=Config.DEFAULT_BB_PERIOD,
                    bb_std=Config.DEFAULT_BB_STD,
                    activation_trigger=Config.DEFAULT_ACTIVATION_TRIGGER,
                    trailing_buy_delta=Config.DEFAULT_TRAILING_BUY_DELTA,
                    buy_hysteresis=Config.DEFAULT_BUY_HYSTERESIS,
                    trailing_stop_delta=Config.DEFAULT_TRAILING_STOP_DELTA,
                    sell_hysteresis=Config.DEFAULT_SELL_HYSTERESIS,
                    base_order_usdt=Config.DEFAULT_BASE_ORDER_USDT,
                    max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                    max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                    drop_multiplier=Config.DEFAULT_DROP_MULTIPLIER,
                    drop_threshold_pct=Config.DEFAULT_DROP_THRESHOLD_PCT,
                    timeframe=Config.DEFAULT_TIMEFRAME,
                    execution_mode="PAPER"
                )
                session.add(global_cfg)

            session.commit()
            logger.info("Tabelas e registros iniciais configurados com sucesso.")

    @contextmanager
    def get_session(self):
        """Fornece um escopo transacional seguro para operações de banco."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Erro em transação do banco: {e}")
            raise
        finally:
            session.close()

    # --- Operações de Ativos ---
    def get_active_symbols(self):
        with self.get_session() as session:
            assets = session.query(Asset).filter_by(is_active=True).all()
            return [a.symbol for a in assets]

    def get_all_assets(self):
        with self.get_session() as session:
            assets = session.query(Asset).all()
            return [a.to_dict() for a in assets]

    def add_asset(self, symbol: str, base_asset: str = None, quote_asset: str = "USDT"):
        symbol = symbol.upper().strip()
        if not base_asset:
            base_asset = symbol.replace(quote_asset, "") if symbol.endswith(quote_asset) else symbol

        with self.get_session() as session:
            asset = session.query(Asset).filter_by(symbol=symbol).first()
            if not asset:
                asset = Asset(
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    is_active=True
                )
                session.add(asset)
                session.flush()
            else:
                asset.is_active = True

            # Cria configuração padrão se não existir
            cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
            if not cfg:
                # Copia valores da configuração global se disponível
                global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
                exec_mode = global_cfg.execution_mode if (global_cfg and hasattr(global_cfg, "execution_mode")) else "PAPER"

                cfg = BotConfig(
                    symbol=symbol,
                    is_global=False,
                    is_bot_running=True,
                    can_buy=True,
                    execution_mode=exec_mode,
                    rsi_period=Config.DEFAULT_RSI_PERIOD,
                    rsi_oversold=Config.DEFAULT_RSI_OVERSOLD,
                    rsi_overbought=Config.DEFAULT_RSI_OVERBOUGHT,
                    bb_period=Config.DEFAULT_BB_PERIOD,
                    bb_std=Config.DEFAULT_BB_STD,
                    activation_trigger=Config.DEFAULT_ACTIVATION_TRIGGER,
                    trailing_buy_delta=Config.DEFAULT_TRAILING_BUY_DELTA,
                    buy_hysteresis=Config.DEFAULT_BUY_HYSTERESIS,
                    trailing_stop_delta=Config.DEFAULT_TRAILING_STOP_DELTA,
                    sell_hysteresis=Config.DEFAULT_SELL_HYSTERESIS,
                    base_order_usdt=Config.DEFAULT_BASE_ORDER_USDT,
                    max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                    max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                    drop_multiplier=Config.DEFAULT_DROP_MULTIPLIER,
                    drop_threshold_pct=Config.DEFAULT_DROP_THRESHOLD_PCT,
                    timeframe=Config.DEFAULT_TIMEFRAME
                )
                session.add(cfg)

            session.commit()
            return asset.to_dict()

    def get_all_assets_config(self):
        """Retorna resumo de todos os pares cadastrados com status de compra, timeframe e posições."""
        with self.get_session() as session:
            assets = session.query(Asset).filter_by(is_active=True).all()
            res = []
            for a in assets:
                cfg = session.query(BotConfig).filter_by(symbol=a.symbol).first()
                pos = session.query(Position).filter_by(symbol=a.symbol, status="OPEN").first()
                can_buy_val = True
                tf_val = Config.DEFAULT_TIMEFRAME
                if cfg:
                    if hasattr(cfg, "can_buy") and cfg.can_buy is not None:
                        can_buy_val = bool(cfg.can_buy)
                    if cfg.timeframe:
                        tf_val = cfg.timeframe
                res.append({
                    "symbol": a.symbol,
                    "base_asset": a.base_asset,
                    "quote_asset": a.quote_asset,
                    "can_buy": can_buy_val,
                    "timeframe": tf_val,
                    "is_bot_running": cfg.is_bot_running if cfg else True,
                    "has_open_position": pos is not None,
                    "position_pnl": pos.unrealized_pnl_pct if pos else 0.0
                })
            return res

    def bulk_update_assets_config(self, updates: list):
        """Atualiza múltiplos pares (ex: can_buy e timeframe) em lote de forma transacional."""
        updated_symbols = []
        with self.get_session() as session:
            for item in updates:
                sym = item.get("symbol")
                if not sym:
                    continue
                cfg = session.query(BotConfig).filter_by(symbol=sym).first()
                if cfg:
                    if "can_buy" in item:
                        cfg.can_buy = bool(item["can_buy"])
                    if "timeframe" in item and item["timeframe"]:
                        cfg.timeframe = str(item["timeframe"]).lower().strip()
                    if "is_bot_running" in item:
                        cfg.is_bot_running = bool(item["is_bot_running"])
                    cfg.updated_at = datetime.now(timezone.utc)
                    updated_symbols.append(sym)
            session.commit()
        return updated_symbols

    def get_execution_mode(self) -> str:
        with self.get_session() as session:
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if global_cfg and hasattr(global_cfg, "execution_mode") and global_cfg.execution_mode:
                return global_cfg.execution_mode
            return "PAPER"

    def set_execution_mode(self, mode: str) -> str:
        mode = mode.upper().strip()
        if mode not in ("PAPER", "REAL"):
            mode = "PAPER"
        with self.get_session() as session:
            session.query(BotConfig).update({"execution_mode": mode})
            session.commit()
            return mode

    # --- Operações de Configuração ---
    def get_config(self, symbol=None):
        with self.get_session() as session:
            if symbol:
                cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
                if cfg:
                    return cfg.to_dict()
            # fallback para global
            cfg = session.query(BotConfig).filter_by(is_global=True).first()
            return cfg.to_dict() if cfg else {}

    def get_all_configs(self):
        with self.get_session() as session:
            cfgs = session.query(BotConfig).all()
            return [c.to_dict() for c in cfgs]

    def update_config(self, symbol, data: dict):
        with self.get_session() as session:
            if symbol:
                cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
            else:
                cfg = session.query(BotConfig).filter_by(is_global=True).first()

            if not cfg:
                return None

            for key, val in data.items():
                if hasattr(cfg, key) and key not in ("id", "symbol", "is_global", "created_at"):
                    setattr(cfg, key, val)
            cfg.updated_at = datetime.now(timezone.utc)
            session.commit()
            return cfg.to_dict()

    # --- Operações de Posições ---
    def get_open_position(self, symbol: str):
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            return pos.to_dict() if pos else None

    def get_all_open_positions(self):
        with self.get_session() as session:
            positions = session.query(Position).filter_by(status="OPEN").all()
            return [p.to_dict() for p in positions]

    def save_position(self, symbol: str, quantity: float, entry_price: float, trailing_stop_price: float):
        with self.get_session() as session:
            total_invested = quantity * entry_price
            pos = Position(
                symbol=symbol,
                status="OPEN",
                side="BUY",
                quantity=quantity,
                entry_price=entry_price,
                current_price=entry_price,
                total_invested_usdt=total_invested,
                trailing_stop_price=trailing_stop_price,
                highest_price=entry_price,
                unrealized_pnl_usdt=0.0,
                unrealized_pnl_pct=0.0,
                opened_at=datetime.now(timezone.utc)
            )
            session.add(pos)
            session.flush()
            return pos.to_dict()

    def update_position_price(self, symbol: str, current_price: float, new_trailing_stop: float = None):
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            if not pos:
                return None
            pos.current_price = current_price
            if current_price > pos.highest_price:
                pos.highest_price = current_price
            if new_trailing_stop is not None and new_trailing_stop > pos.trailing_stop_price:
                pos.trailing_stop_price = new_trailing_stop

            current_val = pos.quantity * current_price
            pos.unrealized_pnl_usdt = current_val - pos.total_invested_usdt
            if pos.total_invested_usdt > 0:
                pos.unrealized_pnl_pct = (pos.unrealized_pnl_usdt / pos.total_invested_usdt) * 100.0
            session.commit()
            return pos.to_dict()

    def close_position(self, symbol: str, exit_price: float, exit_reason: str):
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            if not pos:
                return None
            pos.status = "CLOSED"
            pos.closed_at = datetime.now(timezone.utc)
            return_usdt = pos.quantity * exit_price
            pnl_usdt = return_usdt - pos.total_invested_usdt
            pnl_pct = (pnl_usdt / pos.total_invested_usdt * 100.0) if pos.total_invested_usdt > 0 else 0.0

            duration = 0.0
            if pos.opened_at:
                duration = (datetime.now(timezone.utc) - pos.opened_at.replace(tzinfo=timezone.utc)).total_seconds()

            trade_log = TradeLog(
                symbol=symbol,
                buy_price=pos.entry_price,
                sell_price=exit_price,
                quantity=pos.quantity,
                invested_usdt=pos.total_invested_usdt,
                return_usdt=return_usdt,
                pnl_usdt=pnl_usdt,
                pnl_pct=pnl_pct,
                exit_reason=exit_reason,
                duration_seconds=duration,
                opened_at=pos.opened_at,
                closed_at=pos.closed_at
            )
            session.add(trade_log)
            session.commit()
            return trade_log.to_dict()

    # --- Operações de Ordens ---
    def save_order(self, symbol: str, order_type: str, side: str, trigger_price: float,
                   reference_price: float, quantity: float, usdt_amount: float, status: str = "ARMED", notes: str = ""):
        with self.get_session() as session:
            # Cancela ordens ativas anteriores do mesmo tipo para este ativo
            session.query(Order).filter(
                Order.symbol == symbol,
                Order.order_type == order_type,
                Order.status.in_(["ARMED", "PENDING"])
            ).update({"status": "CANCELLED"})

            order = Order(
                symbol=symbol,
                order_type=order_type,
                side=side,
                status=status,
                trigger_price=trigger_price,
                reference_price=reference_price,
                quantity=quantity,
                usdt_amount=usdt_amount,
                is_simulated=True,
                notes=notes,
                created_at=datetime.now(timezone.utc)
            )
            session.add(order)
            session.flush()
            return order.to_dict()

    def update_order(self, order_id: int, status: str = None, executed_price: float = None, trigger_price: float = None, reference_price: float = None, quantity: float = None, usdt_amount: float = None, notes: str = None):
        with self.get_session() as session:
            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                return None
            if status:
                order.status = status
            if executed_price is not None:
                order.executed_price = executed_price
            if trigger_price is not None:
                order.trigger_price = trigger_price
            if reference_price is not None:
                order.reference_price = reference_price
            if quantity is not None:
                order.quantity = quantity
            if usdt_amount is not None:
                order.usdt_amount = usdt_amount
            if notes is not None:
                order.notes = notes
            order.updated_at = datetime.now(timezone.utc)
            session.commit()
            return order.to_dict()

    def get_active_orders(self, symbol: str = None):
        with self.get_session() as session:
            query = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING"]))
            if symbol:
                query = query.filter_by(symbol=symbol)
            orders = query.order_by(desc(Order.created_at)).all()
            return [o.to_dict() for o in orders]

    def cancel_active_orders(self, symbol: str = None, order_type: str = None):
        with self.get_session() as session:
            query = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING"]))
            if symbol:
                query = query.filter_by(symbol=symbol)
            if order_type:
                query = query.filter_by(order_type=order_type)
            updated_count = query.update({"status": "CANCELLED"}, synchronize_session=False)
            session.commit()
            return updated_count

    # --- Operações de Histórico / Estatísticas ---
    def get_trade_logs(self, symbol: str = None, limit: int = 50):
        with self.get_session() as session:
            query = session.query(TradeLog)
            if symbol:
                query = query.filter_by(symbol=symbol)
            trades = query.order_by(desc(TradeLog.closed_at)).limit(limit).all()
            return [t.to_dict() for t in trades]

    def get_portfolio_summary(self):
        with self.get_session() as session:
            open_positions = session.query(Position).filter_by(status="OPEN").all()
            total_open_capital = sum(p.total_invested_usdt for p in open_positions)
            total_unrealized_pnl = sum(p.unrealized_pnl_usdt for p in open_positions)

            all_trades = session.query(TradeLog).all()
            total_realized_pnl = sum(t.pnl_usdt for t in all_trades)
            winning_trades = sum(1 for t in all_trades if t.pnl_usdt > 0)
            total_trades = len(all_trades)
            win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

            active_orders_count = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING"])).count()

            return {
                "db_type": self.db_type,
                "total_open_capital": round(total_open_capital, 2),
                "total_unrealized_pnl": round(total_unrealized_pnl, 2),
                "total_realized_pnl": round(total_realized_pnl, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": round(win_rate, 1),
                "active_orders_count": active_orders_count,
                "open_positions_count": len(open_positions)
            }

# Instância Singleton
db = DatabaseHandler()
