import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, desc, func, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

from config import Config
from database.models import (
    Base, Asset, BotConfig, Position, PositionTransition, Order, Execution, Trade, TradeLog, TrailingState, EventLog
)

logger = logging.getLogger(__name__)

VALID_POSITION_STATES = [
    "SEM_POSICAO",
    "AGUARDANDO_ENTRADA",
    "ENTRADA_DISPARADA",
    "ABERTA",
    "PROTECAO_ATIVA",
    "SAIDA_DISPARADA",
    "ENCERRANDO",
    "ENCERRADA",
    "ERRO",
    "RECUPERACAO"
]

class DatabaseHandler:
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.db_type = None
        self.is_safe_mode = False
        self.safe_mode_reason = ""
        self._setup_engine()

    def _setup_engine(self):
        """
        Configura o engine de banco de dados.
        Se ambiente for explicitamente de produção e PostgreSQL falhar,
        não troca silenciosamente para SQLite sem aviso (RF-DB-002 / RF-DB-004).
        """
        is_production = os_is_prod = not Config.DEBUG and not getattr(Config, "PAPER_TRADING", True)

        try:
            logger.info(f"Tentando conectar ao PostgreSQL em: {Config.POSTGRES_URI}")
            engine = create_engine(
                Config.POSTGRES_URI,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 3}
            )
            with engine.connect() as conn:
                conn.execute(func.now().select())
            self.engine = engine
            self.db_type = "PostgreSQL"
            logger.info("Conexão com PostgreSQL estabelecida com sucesso!")
        except Exception as e:
            if is_production:
                logger.critical(
                    f"[RF-DB-002/004] Falha crítica de conexão com PostgreSQL em ambiente de produção: {e}. "
                    f"Ativando MODO SEGURO (SAFE MODE) - Bloqueando operações silenciosas no SQLite."
                )
                self.is_safe_mode = True
                self.safe_mode_reason = f"Banco PostgreSQL de produção indisponível: {e}"
                # Mesmo assim inicializa SQLite em modo contingência segura
                self.engine = create_engine(
                    Config.SQLITE_URI,
                    connect_args={"check_same_thread": False},
                    pool_pre_ping=True
                )
                self.db_type = "SQLite (SAFE_MODE Contingência)"
            else:
                logger.warning(
                    f"PostgreSQL não disponível ({e}). Utilizando SQLite local de desenvolvimento ({Config.SQLITE_URI})."
                )
                self.engine = create_engine(
                    Config.SQLITE_URI,
                    connect_args={"check_same_thread": False},
                    pool_pre_ping=True
                )
                self.db_type = "SQLite (Desenvolvimento)"
                logger.info(f"Banco de dados inicializado em modo: {self.db_type}")

        self.SessionLocal = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        )

    def init_db(self):
        """Cria as tabelas e aplica migrações incrementais seguras para colunas novas."""
        from sqlalchemy import inspect
        Base.metadata.create_all(bind=self.engine)

        # Migrações seguras inspecionando colunas existentes para evitar erros de transação abortada no PostgreSQL
        migrations = [
            ("bot_configs", "execution_mode", "VARCHAR(20) DEFAULT 'PAPER'"),
            ("bot_configs", "can_buy", "BOOLEAN DEFAULT TRUE"),
            ("bot_configs", "max_order_amount_usdt", "FLOAT DEFAULT 150.0"),
            ("bot_configs", "max_entries_count", "INTEGER DEFAULT 5"),
            ("bot_configs", "kill_switch_active", "BOOLEAN DEFAULT FALSE"),
            ("bot_configs", "kill_switch_mode", "VARCHAR(30) DEFAULT 'PARADA_OPERACIONAL'"),
            ("bot_configs", "safe_mode_active", "BOOLEAN DEFAULT FALSE"),
            ("bot_configs", "safe_mode_reason", "VARCHAR(255) DEFAULT ''"),
            ("positions", "state", "VARCHAR(30) DEFAULT 'PROTECAO_ATIVA'"),
            ("positions", "entry_count", "INTEGER DEFAULT 1"),
            ("positions", "trade_id", "INTEGER"),
            ("orders", "client_order_id", "VARCHAR(64)"),
            ("orders", "idempotency_key", "VARCHAR(64)"),
            ("orders", "trade_id", "INTEGER")
        ]

        try:
            inspector = inspect(self.engine)
            table_cols = {}
            for tbl, _, _ in migrations:
                if tbl not in table_cols:
                    try:
                        table_cols[tbl] = {c["name"].lower() for c in inspector.get_columns(tbl)}
                    except Exception:
                        table_cols[tbl] = set()

            for tbl, col, col_def in migrations:
                if col.lower() not in table_cols.get(tbl, set()):
                    try:
                        with self.engine.connect() as conn:
                            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}"))
                            conn.commit()
                            logger.info(f"Coluna {col} adicionada à tabela {tbl} com sucesso.")
                    except Exception as ex:
                        logger.warning(f"Não foi possível adicionar coluna {col} em {tbl}: {ex}")
        except Exception as e:
            logger.error(f"Erro ao verificar migrações do banco: {e}")

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
                        max_order_amount_usdt=150.0,
                        max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                        max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                        max_entries_count=5,
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
                    max_order_amount_usdt=150.0,
                    max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                    max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                    max_entries_count=5,
                    drop_multiplier=Config.DEFAULT_DROP_MULTIPLIER,
                    drop_threshold_pct=Config.DEFAULT_DROP_THRESHOLD_PCT,
                    timeframe=Config.DEFAULT_TIMEFRAME,
                    execution_mode="PAPER",
                    kill_switch_active=False,
                    kill_switch_mode="PARADA_OPERACIONAL"
                )
                session.add(global_cfg)

            session.commit()
            logger.info("Tabelas e registros iniciais configurados com sucesso.")

        # Registra evento inicial no EventLog (RF-EVENT-001)
        self.log_event(
            event_type="BOT_INICIADO",
            message=f"Sistema iniciado com sucesso utilizando banco {self.db_type}",
            level="INFO",
            details={"db_type": self.db_type, "symbols": Config.AVAILABLE_SYMBOLS}
        )

    @contextmanager
    def get_session(self):
        """Fornece escopo transacional seguro para operações de banco."""
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

    # ==========================================
    # REGISTRO DE EVENTOS & AUDITORIA (RF-EVENT)
    # ==========================================

    def log_event(self, event_type: str, message: str, level: str = "INFO",
                  symbol: str = None, position_id: int = None, order_id: int = None,
                  trade_id: int = None, details: dict = None) -> dict:
        """Registra evento centralizado no EventLog para auditoria completa (RF-EVENT-001 a 004)."""
        details_str = json.dumps(details) if isinstance(details, (dict, list)) else (str(details) if details else None)
        try:
            with self.get_session() as session:
                evt = EventLog(
                    event_type=event_type,
                    level=level.upper(),
                    symbol=symbol,
                    position_id=position_id,
                    order_id=order_id,
                    trade_id=trade_id,
                    message=message,
                    details=details_str,
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(evt)
                session.flush()
                return evt.to_dict()
        except Exception as e:
            logger.error(f"Erro ao persistir evento no EventLog ({event_type}): {e}")
            return {}

    def get_recent_events(self, limit: int = 50, symbol: str = None, level: str = None):
        """Recupera histórico recente de eventos para o dashboard e auditoria."""
        with self.get_session() as session:
            q = session.query(EventLog)
            if symbol:
                q = q.filter_by(symbol=symbol)
            if level:
                q = q.filter_by(level=level.upper())
            evts = q.order_by(desc(EventLog.timestamp)).limit(limit).all()
            return [e.to_dict() for e in evts]

    # ==========================================
    # OPERAÇÕES DE ATIVOS & EXCLUSÃO DE PARES
    # ==========================================

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

            cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
            if not cfg:
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
                    max_order_amount_usdt=150.0,
                    max_asset_allocation_usdt=Config.DEFAULT_MAX_ASSET_ALLOCATION_USDT,
                    max_total_open_capital_usdt=Config.DEFAULT_MAX_TOTAL_OPEN_CAPITAL_USDT,
                    max_entries_count=5,
                    drop_multiplier=Config.DEFAULT_DROP_MULTIPLIER,
                    drop_threshold_pct=Config.DEFAULT_DROP_THRESHOLD_PCT,
                    timeframe=Config.DEFAULT_TIMEFRAME
                )
                session.add(cfg)

            session.commit()
            res = asset.to_dict()

        self.log_event(
            event_type="ATIVO_ADICIONADO",
            message=f"Par {symbol} cadastrado e ativado para monitoramento",
            level="INFO",
            symbol=symbol
        )
        return res

    def delete_asset(self, symbol: str) -> tuple[bool, str]:
        """
        Exclui / desativa um par de criptoativo de forma segura e recuperável:
        - Bloqueia exclusão se houver posição aberta (evita deixar posições órfãs).
        - Cancela ordens pendentes/armadas.
        - Limpa estado do Trailing.
        - Desativa o ativo (is_active = False) preservando histórico financeiro e de auditoria.
        """
        sym = symbol.upper().strip()
        with self.get_session() as session:
            asset = session.query(Asset).filter_by(symbol=sym).first()
            if not asset:
                return False, f"Par {sym} não encontrado no banco de dados."

            # Valida se há posições em aberto
            open_pos = session.query(Position).filter(
                Position.symbol == sym,
                Position.status == "OPEN"
            ).first()
            if open_pos:
                return False, f"Não é possível excluir {sym}: existe uma posição aberta (Qtd: {open_pos.quantity}). Encerre a posição primeiro."

            # Cancela ordens ativas
            session.query(Order).filter(
                Order.symbol == sym,
                Order.status.in_(["ARMED", "PENDING", "SUBMITTED"])
            ).update({"status": "CANCELLED"}, synchronize_session=False)

            # Remove trailing states
            session.query(TrailingState).filter_by(symbol=sym).delete(synchronize_session=False)

            # Desativa o par no registro de ativos
            asset.is_active = False

            # Desativa o bot config do par
            cfg = session.query(BotConfig).filter_by(symbol=sym).first()
            if cfg:
                cfg.can_buy = False
                cfg.is_bot_running = False

            session.commit()

        self.log_event(
            event_type="ATIVO_REMOVIDO",
            message=f"Par {sym} foi removido/desativado com sucesso.",
            level="WARNING",
            symbol=sym
        )
        logger.info(f"Par {sym} removido/desativado do sistema com sucesso.")
        return True, f"Par {sym} removido com sucesso."

    def get_all_assets_config(self):
        """Retorna resumo de todos os pares cadastrados ativos."""
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
                    "position_state": pos.state if pos else "SEM_POSICAO",
                    "position_pnl": pos.unrealized_pnl_pct if pos else 0.0
                })
            return res

    def bulk_update_assets_config(self, updates: list):
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

    # ==========================================
    # HIERARQUIA OPERACIONAL & KILL SWITCH (RF-13, RF-14)
    # ==========================================

    def set_kill_switch(self, active: bool, mode: str = "PARADA_OPERACIONAL", reason: str = "") -> dict:
        """
        Ativa ou desativa a Parada de Emergência (Kill Switch) de forma persistente (RF-KILL-001 a 007).
        """
        mode = mode if mode in ("PARADA_OPERACIONAL", "PARADA_COM_ENCERRAMENTO") else "PARADA_OPERACIONAL"
        with self.get_session() as session:
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if global_cfg:
                global_cfg.kill_switch_active = bool(active)
                global_cfg.kill_switch_mode = mode
                global_cfg.updated_at = datetime.now(timezone.utc)
            session.commit()

        evt_type = "KILL_SWITCH_ATIVADO" if active else "KILL_SWITCH_DESATIVADO"
        level = "CRITICAL" if active else "INFO"
        msg = f"Kill Switch {'ATIVADO' if active else 'DESATIVADO'} ({mode}). Motivo: {reason or 'Ação manual'}"
        self.log_event(event_type=evt_type, message=msg, level=level, details={"mode": mode, "reason": reason})

        return {"kill_switch_active": active, "kill_switch_mode": mode}

    def get_kill_switch_status(self) -> dict:
        with self.get_session() as session:
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if global_cfg:
                return {
                    "active": bool(global_cfg.kill_switch_active),
                    "mode": global_cfg.kill_switch_mode or "PARADA_OPERACIONAL"
                }
            return {"active": False, "mode": "PARADA_OPERACIONAL"}

    def set_safe_mode(self, active: bool, reason: str = ""):
        """Ativa/Desativa Modo Seguro (SAFE_MODE) decorrente de falhas do banco ou inconsistências (RF-DB-004)."""
        self.is_safe_mode = active
        self.safe_mode_reason = reason if active else ""
        with self.get_session() as session:
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if global_cfg:
                global_cfg.safe_mode_active = bool(active)
                global_cfg.safe_mode_reason = reason
            session.commit()

        evt_type = "MODO_SEGURO_ATIVADO" if active else "MODO_SEGURO_DESATIVADO"
        self.log_event(
            event_type=evt_type,
            message=f"Modo Seguro {'ATIVADO' if active else 'DESATIVADO'}. Motivo: {reason}",
            level="WARNING" if active else "INFO"
        )

    def get_operational_status(self) -> dict:
        """
        Retorna o estado operacional de acordo com a hierarquia rigorosa (RF-14):
        EMERGÊNCIA (KILL SWITCH) > MODO SEGURO (SAFE MODE) > PAUSADO > OPERANDO
        """
        ks = self.get_kill_switch_status()
        if ks["active"]:
            return {
                "level": "EMERGENCIA",
                "status": "KILL_SWITCH",
                "label": f"PARADA DE EMERGÊNCIA ({ks['mode']})",
                "can_operate": False,
                "can_buy": False
            }

        with self.get_session() as session:
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            if self.is_safe_mode or (global_cfg and global_cfg.safe_mode_active):
                reason = self.safe_mode_reason or (global_cfg.safe_mode_reason if global_cfg else "")
                return {
                    "level": "MODO_SEGURO",
                    "status": "SAFE_MODE",
                    "label": f"MODO SEGURO ATIVO ({reason})",
                    "can_operate": False,
                    "can_buy": False
                }

            if global_cfg and not global_cfg.is_bot_running:
                return {
                    "level": "PAUSADO",
                    "status": "PAUSADO",
                    "label": "BOT PAUSADO (Monitorando sem novas entradas)",
                    "can_operate": True,
                    "can_buy": False
                }

        return {
            "level": "OPERANDO",
            "status": "OPERANDO",
            "label": "BOT OPERANDO NORMALMENTE",
            "can_operate": True,
            "can_buy": True
        }

    # ==========================================
    # CONFIGURAÇÕES GERAIS E EXECUÇÃO
    # ==========================================

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
        self.log_event(
            event_type="MODO_EXECUCAO_ALTERADO",
            message=f"Modo de execução alterado para {mode}",
            level="WARNING" if mode == "REAL" else "INFO"
        )
        return mode

    def get_config(self, symbol=None):
        with self.get_session() as session:
            if symbol:
                cfg = session.query(BotConfig).filter_by(symbol=symbol).first()
                if cfg:
                    return cfg.to_dict()
            global_cfg = session.query(BotConfig).filter_by(is_global=True).first()
            return global_cfg.to_dict() if global_cfg else {}

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

    # ==========================================
    # MÁQUINA DE ESTADOS DA POSIÇÃO (RF-ESTADO)
    # ==========================================

    def transition_position_state(self, position_id: int, new_state: str, reason: str,
                                  price: float = None, quantity: float = None, order_id: int = None) -> bool:
        """Aplica transição explícita e controlada na máquina de estados da posição (RF-ESTADO-001 a 003)."""
        if new_state not in VALID_POSITION_STATES:
            logger.error(f"Estado inválido solicitado: {new_state}")
            return False

        with self.get_session() as session:
            pos = session.query(Position).filter_by(id=position_id).first()
            if not pos:
                return False

            old_state = pos.state or "SEM_POSICAO"
            pos.state = new_state
            if new_state == "ENCERRADA":
                pos.status = "CLOSED"
                pos.closed_at = datetime.now(timezone.utc)
            elif new_state in ("ABERTA", "PROTECAO_ATIVA"):
                pos.status = "OPEN"

            transition = PositionTransition(
                position_id=pos.id,
                symbol=pos.symbol,
                previous_state=old_state,
                new_state=new_state,
                reason=reason,
                price=price,
                quantity=quantity,
                order_id=order_id,
                created_at=datetime.now(timezone.utc)
            )
            session.add(transition)
            session.commit()

        self.log_event(
            event_type=f"ESTADO_{new_state}",
            message=f"[{pos.symbol}] Transição de estado: {old_state} -> {new_state}. Motivo: {reason}",
            level="INFO",
            symbol=pos.symbol,
            position_id=pos.id,
            order_id=order_id,
            details={"previous_state": old_state, "new_state": new_state, "price": price, "quantity": quantity}
        )
        return True

    def get_open_position(self, symbol: str):
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            return pos.to_dict() if pos else None

    def get_all_open_positions(self):
        with self.get_session() as session:
            positions = session.query(Position).filter_by(status="OPEN").all()
            return [p.to_dict() for p in positions]

    def save_position(self, symbol: str, quantity: float, entry_price: float, trailing_stop_price: float,
                      entry_count: int = 1, trade_id: int = None):
        """Salva ou atualiza posição aberta persistindo o estado explícito (RF-ESTADO-004)."""
        with self.get_session() as session:
            total_invested = quantity * entry_price
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            if not pos:
                pos = Position(
                    symbol=symbol,
                    status="OPEN",
                    state="PROTECAO_ATIVA",
                    side="BUY",
                    quantity=quantity,
                    entry_price=entry_price,
                    current_price=entry_price,
                    total_invested_usdt=total_invested,
                    trailing_stop_price=trailing_stop_price,
                    highest_price=entry_price,
                    unrealized_pnl_usdt=0.0,
                    unrealized_pnl_pct=0.0,
                    entry_count=entry_count,
                    trade_id=trade_id,
                    opened_at=datetime.now(timezone.utc)
                )
                session.add(pos)
                session.flush()
                pos_dict = pos.to_dict()

                transition = PositionTransition(
                    position_id=pos.id,
                    symbol=symbol,
                    previous_state="SEM_POSICAO",
                    new_state="PROTECAO_ATIVA",
                    reason="Posição inicial aberta",
                    price=entry_price,
                    quantity=quantity,
                    created_at=datetime.now(timezone.utc)
                )
                session.add(transition)
            else:
                # Aumento de exposição / Escalonamento (RF-RISCO-008)
                new_qty = pos.quantity + quantity
                new_invested = pos.total_invested_usdt + total_invested
                new_avg_entry = new_invested / new_qty if new_qty > 0 else entry_price

                pos.quantity = new_qty
                pos.entry_price = new_avg_entry
                pos.total_invested_usdt = new_invested
                pos.current_price = entry_price
                pos.entry_count = (pos.entry_count or 1) + 1
                pos.state = "PROTECAO_ATIVA"

                # Stop NUNCA retrocede
                if trailing_stop_price > pos.trailing_stop_price:
                    pos.trailing_stop_price = trailing_stop_price

                session.flush()
                pos_dict = pos.to_dict()

                transition = PositionTransition(
                    position_id=pos.id,
                    symbol=symbol,
                    previous_state="PROTECAO_ATIVA",
                    new_state="PROTECAO_ATIVA",
                    reason=f"Aumento progressivo de exposição #{pos.entry_count}",
                    price=entry_price,
                    quantity=quantity,
                    created_at=datetime.now(timezone.utc)
                )
                session.add(transition)

            session.commit()
            return pos_dict

    def update_position_price(self, symbol: str, current_price: float, new_trailing_stop: float = None):
        """Atualiza preço corrente da posição garantindo que o Stop NUNCA retroceda (RF-TRAIL-003)."""
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            if not pos:
                return None
            pos.current_price = current_price
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # Trava estrita de descida do Stop: novo_stop >= stop_anterior
            if new_trailing_stop is not None:
                if new_trailing_stop >= pos.trailing_stop_price:
                    pos.trailing_stop_price = new_trailing_stop
                else:
                    logger.warning(
                        f"[{symbol}] [RF-TRAIL-003] Tentativa de recuar Stop bloqueada! "
                        f"Atual: {pos.trailing_stop_price:.4f}, Proposto: {new_trailing_stop:.4f}"
                    )

            current_val = pos.quantity * current_price
            pos.unrealized_pnl_usdt = current_val - pos.total_invested_usdt
            if pos.total_invested_usdt > 0:
                pos.unrealized_pnl_pct = (pos.unrealized_pnl_usdt / pos.total_invested_usdt) * 100.0

            session.commit()
            return pos.to_dict()

    def close_position(self, symbol: str, exit_price: float, exit_reason: str):
        """Encerra a posição, transiciona máquina de estados e registra TradeLog / Trade (RF-TRADE)."""
        with self.get_session() as session:
            pos = session.query(Position).filter_by(symbol=symbol, status="OPEN").first()
            if not pos:
                return None
            pos.status = "CLOSED"
            pos.state = "ENCERRADA"
            pos.closed_at = datetime.now(timezone.utc)
            return_usdt = pos.quantity * exit_price
            pnl_usdt = return_usdt - pos.total_invested_usdt
            pnl_pct = (pnl_usdt / pos.total_invested_usdt * 100.0) if pos.total_invested_usdt > 0 else 0.0

            duration = 0.0
            if pos.opened_at:
                duration = (datetime.now(timezone.utc) - pos.opened_at.replace(tzinfo=timezone.utc)).total_seconds()

            # Registra TradeLog (compatibilidade)
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

            # Transição de estado registrada
            transition = PositionTransition(
                position_id=pos.id,
                symbol=symbol,
                previous_state="PROTECAO_ATIVA",
                new_state="ENCERRADA",
                reason=exit_reason,
                price=exit_price,
                quantity=pos.quantity,
                created_at=datetime.now(timezone.utc)
            )
            session.add(transition)

            # Se houver entidade Trade associada, encerra o Trade
            if pos.trade_id:
                tr = session.query(Trade).filter_by(id=pos.trade_id).first()
                if tr:
                    tr.status = "CLOSED"
                    tr.exit_price = exit_price
                    tr.return_usdt = return_usdt
                    tr.realized_pnl_usdt = pnl_usdt
                    tr.realized_pnl_pct = pnl_pct
                    tr.exit_reason = exit_reason
                    tr.duration_seconds = duration
                    tr.closed_at = datetime.now(timezone.utc)

            session.commit()
            res = trade_log.to_dict()

        self.log_event(
            event_type="POSICAO_ENCERRADA",
            message=f"[{symbol}] Posição encerrada @ ${exit_price:.4f} ({exit_reason}) | PnL: ${pnl_usdt:.2f} ({pnl_pct:.2f}%)",
            level="INFO" if pnl_usdt >= 0 else "WARNING",
            symbol=symbol,
            details={"exit_price": exit_price, "pnl_usdt": pnl_usdt, "pnl_pct": pnl_pct, "reason": exit_reason}
        )
        return res

    # ==========================================
    # PERSISTÊNCIA DO ESTADO DO TRAILING (RF-TRAIL)
    # ==========================================

    def save_trailing_state(self, symbol: str, trailing_type: str, reference_price: float,
                            trigger_price: float, delta: float, hysteresis: float = 0.002,
                            allocated_usdt: float = 50.0, entry_count: int = 1,
                            initial_trigger_price: float = None, order_id: int = None, notes: str = ""):
        """Persiste o estado do Trailing Buy ou Trailing Stop no banco de dados (RF-TRAIL-001 a 005)."""
        with self.get_session() as session:
            st = session.query(TrailingState).filter_by(symbol=symbol).first()
            if not st:
                st = TrailingState(
                    symbol=symbol,
                    trailing_type=trailing_type,
                    is_active=True,
                    reference_price=reference_price,
                    trigger_price=trigger_price,
                    initial_trigger_price=initial_trigger_price or reference_price,
                    delta=delta,
                    hysteresis=hysteresis,
                    allocated_usdt=allocated_usdt,
                    entry_count=entry_count,
                    order_id=order_id,
                    notes=notes
                )
                session.add(st)
            else:
                st.trailing_type = trailing_type
                st.is_active = True
                st.reference_price = reference_price
                st.trigger_price = trigger_price
                if initial_trigger_price:
                    st.initial_trigger_price = initial_trigger_price
                st.delta = delta
                st.hysteresis = hysteresis
                st.allocated_usdt = allocated_usdt
                st.entry_count = entry_count
                if order_id:
                    st.order_id = order_id
                st.notes = notes
                st.updated_at = datetime.now(timezone.utc)
            session.commit()
            return st.to_dict()

    def get_trailing_state(self, symbol: str):
        with self.get_session() as session:
            st = session.query(TrailingState).filter_by(symbol=symbol, is_active=True).first()
            return st.to_dict() if st else None

    def get_all_active_trailing_states(self):
        with self.get_session() as session:
            sts = session.query(TrailingState).filter_by(is_active=True).all()
            return [s.to_dict() for s in sts]

    def clear_trailing_state(self, symbol: str):
        with self.get_session() as session:
            session.query(TrailingState).filter_by(symbol=symbol).delete(synchronize_session=False)
            session.commit()

    # ==========================================
    # OPERAÇÕES DE ORDENS & IDEMPOTÊNCIA (RF-IDEMP)
    # ==========================================

    def get_order_by_client_id(self, client_order_id: str):
        if not client_order_id:
            return None
        with self.get_session() as session:
            ord_obj = session.query(Order).filter_by(client_order_id=client_order_id).first()
            return ord_obj.to_dict() if ord_obj else None

    def get_order_by_idempotency_key(self, idempotency_key: str):
        if not idempotency_key:
            return None
        with self.get_session() as session:
            ord_obj = session.query(Order).filter_by(idempotency_key=idempotency_key).first()
            return ord_obj.to_dict() if ord_obj else None

    def save_order(self, symbol: str, order_type: str, side: str, trigger_price: float,
                   reference_price: float, quantity: float, usdt_amount: float, status: str = "ARMED",
                   notes: str = "", client_order_id: str = None, idempotency_key: str = None, trade_id: int = None):
        """
        Salva ordem com identificador único de negócio e chave de idempotência (RF-IDEMP-001/002).
        """
        with self.get_session() as session:
            # Proteção contra duplicidade de submissão (RF-IDEMP-002)
            if idempotency_key:
                existing = session.query(Order).filter_by(idempotency_key=idempotency_key).first()
                if existing:
                    logger.warning(f"[{symbol}] Ordem já existente para idempotency_key={idempotency_key}. Retornando ordem existente.")
                    return existing.to_dict()

            # Cancela ordens ativas anteriores do mesmo tipo para o mesmo par
            session.query(Order).filter(
                Order.symbol == symbol,
                Order.order_type == order_type,
                Order.status.in_(["ARMED", "PENDING"])
            ).update({"status": "CANCELLED"}, synchronize_session=False)

            order = Order(
                symbol=symbol,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
                trade_id=trade_id,
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
            res = order.to_dict()

        self.log_event(
            event_type="ORDEM_CRIADA",
            message=f"[{symbol}] Ordem {order_type} ({side}) criada. Gatilho: ${trigger_price:.4f}, Qtd: {quantity:.6f}",
            level="INFO",
            symbol=symbol,
            order_id=res["id"],
            details=res
        )
        return res

    def update_order(self, order_id: int, status: str = None, executed_price: float = None,
                     trigger_price: float = None, reference_price: float = None, quantity: float = None,
                     usdt_amount: float = None, notes: str = None):
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
            query = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING", "SUBMITTED"]))
            if symbol:
                query = query.filter_by(symbol=symbol)
            orders = query.order_by(desc(Order.created_at)).all()
            return [o.to_dict() for o in orders]

    def cancel_active_orders(self, symbol: str = None, order_type: str = None):
        with self.get_session() as session:
            query = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING", "SUBMITTED"]))
            if symbol:
                query = query.filter_by(symbol=symbol)
            if order_type:
                query = query.filter_by(order_type=order_type)
            updated_count = query.update({"status": "CANCELLED"}, synchronize_session=False)
            session.commit()
            return updated_count

    # ==========================================
    # HISTÓRICO E ESTATÍSTICAS DO PORTFÓLIO
    # ==========================================

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

            active_orders_count = session.query(Order).filter(Order.status.in_(["ARMED", "PENDING", "SUBMITTED"])).count()

            operational = self.get_operational_status()

            return {
                "db_type": self.db_type,
                "operational_status": operational["status"],
                "operational_label": operational["label"],
                "operational_level": operational["level"],
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
