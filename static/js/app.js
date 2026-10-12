/**
 * Orquestrador da Interface do Bot Binance (WebSocket + UI + Eventos)
 * Inclui:
 * - Adição e Exclusão dinâmica de pares de criptoativos
 * - Controle de Aumento Progressivo de Exposição / Escalonamento de Entrada
 * - Modo Explicar (diagnóstico em linguagem natural)
 * - Parada de Emergência (Kill Switch) e Hierarquia Operacional
 * - Auditoria em tempo real via EventLog
 * - Status de conexão do WebSocket
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Inicializa Conexão Socket.IO
    const socket = io();

    // 2. Inicializa Gerenciador do Gráfico
    const chartManager = new BotChartManager("candlestick-chart", "rsi-chart");

    // Elementos DOM - Topo & Controles
    const symbolSelect = document.getElementById("symbol-select");
    const timeframeBtns = document.querySelectorAll(".tf-btn");
    const botStatusDot = document.getElementById("bot-status-dot");
    const botStatusText = document.getElementById("bot-status-text");
    const botToggleBtn = document.getElementById("btn-toggle-bot");
    const btnToggleMode = document.getElementById("btn-toggle-mode");
    const modeTextEl = document.getElementById("mode-text");
    const headerBrandBadge = document.getElementById("header-brand-badge");
    const wsStatusBadge = document.getElementById("ws-status-badge");
    const operationalHierarchyBadge = document.getElementById("operational-hierarchy-badge");

    // Modais & Ações de Pares
    const btnOpenAddAsset = document.getElementById("btn-open-add-asset");
    const modalAddAsset = document.getElementById("modal-add-asset");
    const inputNewSymbol = document.getElementById("input-new-symbol");
    const btnConfirmAddAsset = document.getElementById("btn-confirm-add-asset");
    const btnCloseModalAsset = document.getElementById("btn-close-modal-asset");
    const btnCancelAddAsset = document.getElementById("btn-cancel-add-asset");

    const btnOpenManagePairs = document.getElementById("btn-open-manage-pairs");
    const modalManagePairs = document.getElementById("modal-manage-pairs");
    const btnCloseModalPairs = document.getElementById("btn-close-modal-pairs");
    const btnCancelManagePairs = document.getElementById("btn-cancel-manage-pairs");
    const btnSaveManagePairs = document.getElementById("btn-save-manage-pairs");
    const btnBulkEnableBuy = document.getElementById("btn-bulk-enable-buy");
    const btnBulkDisableBuy = document.getElementById("btn-bulk-disable-buy");
    const managePairsTableBody = document.getElementById("manage-pairs-table-body");

    // Kill Switch (Parada de Emergência)
    const btnOpenKillSwitch = document.getElementById("btn-open-kill-switch");
    const modalKillSwitch = document.getElementById("modal-kill-switch");
    const btnCloseModalKill = document.getElementById("btn-close-modal-kill");
    const btnCancelKillSwitch = document.getElementById("btn-cancel-kill-switch");
    const btnConfirmKillSwitch = document.getElementById("btn-confirm-kill-switch");
    const killSwitchModeSelect = document.getElementById("kill-switch-mode-select");
    const killSwitchReason = document.getElementById("kill-switch-reason");
    let isKillSwitchActive = false;

    // Modo Explicar
    const btnExplainDecision = document.getElementById("btn-explain-decision");
    const modalExplainDecision = document.getElementById("modal-explain-decision");
    const btnCloseModalExplain = document.getElementById("btn-close-modal-explain");
    const btnCloseExplainOk = document.getElementById("btn-close-explain-ok");
    const explainContent = document.getElementById("explain-content");

    // Modo Real
    const modalConfirmReal = document.getElementById("modal-confirm-real");
    const btnConfirmRealMode = document.getElementById("btn-confirm-real-mode");
    const btnCloseModalReal = document.getElementById("btn-close-modal-real");
    const btnCancelRealMode = document.getElementById("btn-cancel-real-mode");

    // Controles de Permissão e Timeframe do Par
    const currentPairCanBuyBadge = document.getElementById("current-pair-can-buy-badge");
    const cfgCanBuy = document.getElementById("cfg-can-buy");
    const cfgCanBuyStatusText = document.getElementById("cfg-can-buy-status-text");
    const cfgStrategyTimeframe = document.getElementById("cfg-strategy-timeframe");

    // Preço e Ticker Header
    const currentPriceEl = document.getElementById("current-price");
    const priceChangeEl = document.getElementById("price-change");
    const tickerHighEl = document.getElementById("ticker-high");
    const tickerLowEl = document.getElementById("ticker-low");
    const tickerVolEl = document.getElementById("ticker-volume");

    // Indicadores Chips
    const rsiValEl = document.getElementById("chip-rsi-val");
    const bbUpperEl = document.getElementById("chip-bb-upper");
    const bbMiddleEl = document.getElementById("chip-bb-middle");
    const bbLowerEl = document.getElementById("chip-bb-lower");

    // Métricas do Portfólio
    const portfolioEquityEl = document.getElementById("portfolio-equity");
    const portfolioOpenCapEl = document.getElementById("portfolio-open-cap");
    const portfolioRealizedPnlEl = document.getElementById("portfolio-realized-pnl");
    const portfolioWinRateEl = document.getElementById("portfolio-win-rate");
    const portfolioTotalTradesEl = document.getElementById("portfolio-total-trades");

    // Formulário de Configuração
    const configForm = document.getElementById("bot-config-form");
    const rsiPeriodInput = document.getElementById("cfg-rsi-period");
    const rsiOversoldInput = document.getElementById("cfg-rsi-oversold");
    const bbPeriodInput = document.getElementById("cfg-bb-period");
    const bbStdInput = document.getElementById("cfg-bb-std");
    const triggerModeSelect = document.getElementById("cfg-trigger-mode");
    const trailingBuyDeltaInput = document.getElementById("cfg-tb-delta");
    const buyHysteresisInput = document.getElementById("cfg-buy-hyst");
    const trailingStopDeltaInput = document.getElementById("cfg-ts-delta");
    const sellHysteresisInput = document.getElementById("cfg-sell-hyst");
    const baseOrderUsdtInput = document.getElementById("cfg-base-order");
    const maxOrderAmountInput = document.getElementById("cfg-max-order-amount");
    const maxEntriesInput = document.getElementById("cfg-max-entries");
    const maxAssetAllocInput = document.getElementById("cfg-max-asset");
    const maxTotalOpenInput = document.getElementById("cfg-max-total");
    const dropMultInput = document.getElementById("cfg-drop-mult");
    const dropThreshInput = document.getElementById("cfg-drop-thresh");

    // Elementos de Pré-Visualização
    const previewTbDelta = document.getElementById("preview-tb-delta");
    const previewBuyHyst = document.getElementById("preview-buy-hyst");
    const previewTsDelta = document.getElementById("preview-ts-delta");
    const previewSellHyst = document.getElementById("preview-sell-hyst");

    // Tabelas e Abas
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    const ordersTableBody = document.getElementById("orders-table-body");
    const positionsTableBody = document.getElementById("positions-table-body");
    const tradesTableBody = document.getElementById("trades-table-body");
    const eventsTableBody = document.getElementById("events-table-body");
    const ordersBadge = document.getElementById("badge-orders-count");
    const positionsBadge = document.getElementById("badge-positions-count");

    // Estado da Aplicação
    let currentSymbol = symbolSelect.value || "BTCUSDT";
    let currentTimeframe = "1m";
    let lastKnownPrice = 0.0;
    let currentExecutionMode = "PAPER";

    // ==========================================
    // FUNÇÕES DE CARREGAMENTO DE DADOS
    // ==========================================

    async function loadSymbolData(symbol) {
        currentSymbol = symbol;
        symbolSelect.value = symbol;

        try {
            const resp = await fetch(`/api/chart-data?symbol=${symbol}&timeframe=${currentTimeframe}`);
            const data = await resp.json();

            if (data.success) {
                const cd = data.chart_data;
                chartManager.setData(cd.candles, cd.bb_upper, cd.bb_middle, cd.bb_lower, cd.rsi);
                chartManager.updateDynamicLines(data.position, data.active_orders);

                if (cd.candles.length > 0) {
                    const last = cd.candles[cd.candles.length - 1];
                    lastKnownPrice = last.close;
                    currentPriceEl.textContent = `$${last.close.toFixed(2)}`;
                }

                if (cd.rsi.length > 0) {
                    const lastRsi = cd.rsi[cd.rsi.length - 1].value;
                    rsiValEl.textContent = lastRsi.toFixed(1);
                    rsiValEl.className = lastRsi <= 30 ? "text-green font-bold" : (lastRsi >= 70 ? "text-red font-bold" : "mono");
                }
                if (cd.bb_upper.length > 0) bbUpperEl.textContent = `$${cd.bb_upper[cd.bb_upper.length - 1].value.toFixed(2)}`;
                if (cd.bb_middle.length > 0) bbMiddleEl.textContent = `$${cd.bb_middle[cd.bb_middle.length - 1].value.toFixed(2)}`;
                if (cd.bb_lower.length > 0) bbLowerEl.textContent = `$${cd.bb_lower[cd.bb_lower.length - 1].value.toFixed(2)}`;
            }

            await loadConfig(symbol);
            refreshOrders();
            refreshPositions();
            refreshTrades();
            updatePercentagePreviews();
        } catch (e) {
            console.error("Erro ao carregar dados do símbolo:", e);
        }
    }

    async function loadConfig(symbol) {
        try {
            const resp = await fetch(`/api/config?symbol=${symbol}`);
            const data = await resp.json();

            if (data.success && data.config) {
                const c = data.config;
                rsiPeriodInput.value = c.rsi_period;
                rsiOversoldInput.value = c.rsi_oversold;
                bbPeriodInput.value = c.bb_period;
                bbStdInput.value = c.bb_std;
                triggerModeSelect.value = c.activation_trigger || "or";
                trailingBuyDeltaInput.value = (c.trailing_buy_delta * 100).toFixed(2);
                buyHysteresisInput.value = (c.buy_hysteresis * 100).toFixed(2);
                trailingStopDeltaInput.value = (c.trailing_stop_delta * 100).toFixed(2);
                sellHysteresisInput.value = (c.sell_hysteresis * 100).toFixed(2);
                baseOrderUsdtInput.value = c.base_order_usdt;
                if (maxOrderAmountInput) maxOrderAmountInput.value = c.max_order_amount_usdt || 150.0;
                if (maxEntriesInput) maxEntriesInput.value = c.max_entries_count || 5;
                maxAssetAllocInput.value = c.max_asset_allocation_usdt;
                maxTotalOpenInput.value = c.max_total_open_capital_usdt;
                dropMultInput.value = c.drop_multiplier;
                dropThreshInput.value = (c.drop_threshold_pct * 100).toFixed(2);

                const canBuy = (c.can_buy !== false);
                updateCanBuyUI(canBuy);
                if (c.timeframe && cfgStrategyTimeframe) {
                    cfgStrategyTimeframe.value = c.timeframe;
                }

                updateBotStatusUI(c.is_bot_running);
                if (c.execution_mode) {
                    updateExecutionModeUI(c.execution_mode);
                }

                updatePercentagePreviews();
            }
        } catch (e) {
            console.error("Erro ao carregar configurações:", e);
        }
    }

    function updateCanBuyUI(canBuy) {
        if (cfgCanBuy) cfgCanBuy.checked = canBuy;
        if (cfgCanBuyStatusText) {
            if (canBuy) {
                cfgCanBuyStatusText.textContent = "HABILITADO (Novas compras permitidas)";
                cfgCanBuyStatusText.className = "text-green mono";
            } else {
                cfgCanBuyStatusText.textContent = "BLOQUEADO (Novas compras desativadas)";
                cfgCanBuyStatusText.className = "text-red mono";
            }
        }
        updateCurrentPairCanBuyBadge(canBuy);
    }

    function updateCurrentPairCanBuyBadge(canBuy) {
        if (!currentPairCanBuyBadge) return;
        if (canBuy) {
            currentPairCanBuyBadge.className = "badge-status-pill can-buy-enabled";
            currentPairCanBuyBadge.textContent = "COMPRA LIBERADA";
            currentPairCanBuyBadge.title = "Novas compras de Trailing Buy estão autorizadas para este par.";
        } else {
            currentPairCanBuyBadge.className = "badge-status-pill can-buy-disabled";
            currentPairCanBuyBadge.textContent = "COMPRA BLOQUEADA";
            currentPairCanBuyBadge.title = "Novas compras estão pausadas para este par. Posições existentes continuam protegidas pelo Trailing Stop.";
        }
    }

    function updateBotStatusUI(isRunning) {
        if (isRunning) {
            botStatusDot.className = "pulse-dot online";
            botStatusText.textContent = "BOT ATIVO";
            botStatusText.className = "text-green mono";
            botToggleBtn.textContent = "Pausar Bot";
            botToggleBtn.className = "btn-secondary";
        } else {
            botStatusDot.className = "pulse-dot offline";
            botStatusText.textContent = "BOT PAUSADO";
            botStatusText.className = "text-red mono";
            botToggleBtn.textContent = "Ativar Bot";
            botToggleBtn.className = "btn-primary";
        }
    }

    function updateExecutionModeUI(mode) {
        currentExecutionMode = mode;
        if (mode === "REAL") {
            btnToggleMode.className = "mode-badge-btn real";
            modeTextEl.textContent = "MODO REAL (Binance)";
            headerBrandBadge.textContent = "MODO REAL";
            headerBrandBadge.style.background = "rgba(245, 158, 11, 0.2)";
            headerBrandBadge.style.color = "#f59e0b";
            headerBrandBadge.style.borderColor = "rgba(245, 158, 11, 0.4)";
        } else {
            btnToggleMode.className = "mode-badge-btn paper";
            modeTextEl.textContent = "SIMULAÇÃO (Paper)";
            headerBrandBadge.textContent = "SIMULAÇÃO";
            headerBrandBadge.style.background = "rgba(0, 210, 255, 0.15)";
            headerBrandBadge.style.color = "var(--color-cyan)";
            headerBrandBadge.style.borderColor = "rgba(0, 210, 255, 0.3)";
        }
    }

    function updateOperationalStatusUI(op) {
        if (!operationalHierarchyBadge) return;
        operationalHierarchyBadge.textContent = op.level || op.status;

        if (op.level === "EMERGENCIA" || op.status === "KILL_SWITCH") {
            operationalHierarchyBadge.style.background = "rgba(239, 68, 68, 0.25)";
            operationalHierarchyBadge.style.color = "#ef4444";
            operationalHierarchyBadge.style.borderColor = "#ef4444";
            operationalHierarchyBadge.classList.add("badge-kill-switch");
            isKillSwitchActive = true;
            btnOpenKillSwitch.textContent = "⚠️ REATIVAR BOT (Kill Switch Ativo)";
            btnOpenKillSwitch.style.background = "#dc2626";
            btnOpenKillSwitch.style.color = "#fff";
        } else if (op.level === "MODO_SEGURO") {
            operationalHierarchyBadge.style.background = "rgba(245, 158, 11, 0.25)";
            operationalHierarchyBadge.style.color = "#f59e0b";
            operationalHierarchyBadge.style.borderColor = "#f59e0b";
            operationalHierarchyBadge.classList.remove("badge-kill-switch");
            isKillSwitchActive = false;
            btnOpenKillSwitch.textContent = "🛑 Kill Switch";
            btnOpenKillSwitch.style.background = "";
            btnOpenKillSwitch.style.color = "#ef4444";
        } else if (op.level === "PAUSADO") {
            operationalHierarchyBadge.style.background = "rgba(234, 179, 8, 0.2)";
            operationalHierarchyBadge.style.color = "#eab308";
            operationalHierarchyBadge.style.borderColor = "#eab308";
            operationalHierarchyBadge.classList.remove("badge-kill-switch");
            isKillSwitchActive = false;
            btnOpenKillSwitch.textContent = "🛑 Kill Switch";
            btnOpenKillSwitch.style.background = "";
            btnOpenKillSwitch.style.color = "#ef4444";
        } else {
            operationalHierarchyBadge.style.background = "rgba(0, 210, 255, 0.15)";
            operationalHierarchyBadge.style.color = "#00d2ff";
            operationalHierarchyBadge.style.borderColor = "rgba(0, 210, 255, 0.3)";
            operationalHierarchyBadge.classList.remove("badge-kill-switch");
            isKillSwitchActive = false;
            btnOpenKillSwitch.textContent = "🛑 Kill Switch";
            btnOpenKillSwitch.style.background = "";
            btnOpenKillSwitch.style.color = "#ef4444";
        }
    }

    function updateWsStatusUI(status) {
        if (!wsStatusBadge) return;
        wsStatusBadge.textContent = `● WS: ${status}`;
        if (status === "CONECTADO") {
            wsStatusBadge.style.background = "rgba(16, 185, 129, 0.15)";
            wsStatusBadge.style.color = "#10b981";
            wsStatusBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";
        } else if (status === "RECONECTANDO") {
            wsStatusBadge.style.background = "rgba(245, 158, 11, 0.2)";
            wsStatusBadge.style.color = "#f59e0b";
            wsStatusBadge.style.borderColor = "rgba(245, 158, 11, 0.4)";
        } else if (status === "RECUPERANDO") {
            wsStatusBadge.style.background = "rgba(56, 189, 248, 0.2)";
            wsStatusBadge.style.color = "#38bdf8";
            wsStatusBadge.style.borderColor = "rgba(56, 189, 248, 0.4)";
        } else {
            wsStatusBadge.style.background = "rgba(239, 68, 68, 0.2)";
            wsStatusBadge.style.color = "#ef4444";
            wsStatusBadge.style.borderColor = "rgba(239, 68, 68, 0.4)";
        }
    }

    function updatePercentagePreviews() {
        if (!lastKnownPrice || lastKnownPrice <= 0) return;

        const tbDelta = parseFloat(trailingBuyDeltaInput.value) || 0;
        const buyHyst = parseFloat(buyHysteresisInput.value) || 0;
        const tsDelta = parseFloat(trailingStopDeltaInput.value) || 0;
        const sellHyst = parseFloat(sellHysteresisInput.value) || 0;

        const tbVal = lastKnownPrice * (1.0 + (tbDelta / 100.0));
        const buyHystVal = lastKnownPrice * (buyHyst / 100.0);
        const tsVal = lastKnownPrice * (1.0 - (tsDelta / 100.0));
        const sellHystVal = lastKnownPrice * (sellHyst / 100.0);

        if (previewTbDelta) previewTbDelta.textContent = `Disparo se subir p/ $${tbVal.toFixed(2)}`;
        if (previewBuyHyst) previewBuyHyst.textContent = `Sensibilidade mín: $${buyHystVal.toFixed(2)}`;
        if (previewTsDelta) previewTsDelta.textContent = `Stop recua p/ $${tsVal.toFixed(2)}`;
        if (previewSellHyst) previewSellHyst.textContent = `Subida mín do stop: $${sellHystVal.toFixed(2)}`;
    }

    // ==========================================
    // REQUISIÇÕES E TABELAS
    // ==========================================

    async function refreshOrders() {
        try {
            const resp = await fetch(`/api/orders?symbol=${currentSymbol}`);
            const res = await resp.json();
            if (res.success) {
                renderOrdersTable(res.orders);
            }
        } catch (e) {
            console.error("Erro ao buscar ordens:", e);
        }
    }

    function renderOrdersTable(orders) {
        ordersBadge.textContent = orders.length;
        if (orders.length === 0) {
            ordersTableBody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align: center; padding: 2rem;">Nenhuma ordem ativa no momento.</td></tr>`;
            return;
        }

        ordersTableBody.innerHTML = orders.map(o => `
            <tr>
                <td class="mono font-bold">${o.symbol}</td>
                <td><span class="${o.order_type === 'TRAILING_BUY' ? 'text-cyan' : 'text-red'} font-bold">${o.order_type}</span></td>
                <td><span class="${o.side === 'BUY' ? 'text-green' : 'text-red'} font-bold">${o.side}</span></td>
                <td class="mono">$${o.trigger_price.toFixed(4)}</td>
                <td class="mono text-muted">$${o.reference_price.toFixed(4)}</td>
                <td class="mono">$${o.usdt_amount.toFixed(2)}</td>
                <td><span class="badge-counter">${o.status}</span></td>
                <td>
                    <button class="btn-danger btn-cancel-order" data-symbol="${o.symbol}">Cancelar</button>
                </td>
            </tr>
        `).join("");

        document.querySelectorAll(".btn-cancel-order").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                const sym = e.target.getAttribute("data-symbol");
                await fetch("/api/orders/cancel", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol: sym })
                });
                showToast(`Ordens canceladas para ${sym}`, "INFO");
                refreshOrders();
            });
        });
    }

    async function refreshPositions() {
        try {
            const resp = await fetch("/api/positions");
            const res = await resp.json();
            if (res.success) {
                renderPositionsTable(res.positions);
            }
        } catch (e) {
            console.error("Erro ao buscar posições:", e);
        }
    }

    function renderPositionsTable(positions) {
        positionsBadge.textContent = positions.length;
        if (positions.length === 0) {
            positionsTableBody.innerHTML = `<tr><td colspan="10" class="text-muted" style="text-align: center; padding: 2rem;">Nenhuma posição aberta no momento.</td></tr>`;
            return;
        }

        positionsTableBody.innerHTML = positions.map(p => {
            const isProfit = p.unrealized_pnl_usdt >= 0;
            const pnlClass = isProfit ? "text-green" : "text-red";
            return `
                <tr>
                    <td class="mono font-bold">${p.symbol}</td>
                    <td><span class="badge-status-pill can-buy-enabled" style="font-size: 0.72rem;">${p.state || 'PROTECAO_ATIVA'}</span></td>
                    <td class="mono" style="text-align: center;">#${p.entry_count || 1}</td>
                    <td class="mono">${p.quantity.toFixed(4)}</td>
                    <td class="mono">$${p.entry_price.toFixed(4)}</td>
                    <td class="mono font-bold">$${p.current_price.toFixed(4)}</td>
                    <td class="mono text-red">$${p.trailing_stop_price.toFixed(4)}</td>
                    <td class="mono">$${p.total_invested_usdt.toFixed(2)}</td>
                    <td class="mono font-bold ${pnlClass}">
                        ${isProfit ? "+" : ""}$${p.unrealized_pnl_usdt.toFixed(2)} (${isProfit ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%)
                    </td>
                    <td>
                        <button class="btn-danger btn-close-pos" data-symbol="${p.symbol}">Vender a Mercado</button>
                    </td>
                </tr>
            `;
        }).join("");

        document.querySelectorAll(".btn-close-pos").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                const sym = e.target.getAttribute("data-symbol");
                const res = await fetch("/api/positions/close", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol: sym })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`Posição em ${sym} encerrada a mercado!`, "SUCCESS");
                    refreshPositions();
                    refreshTrades();
                    refreshEvents();
                }
            });
        });
    }

    async function refreshTrades() {
        try {
            const resp = await fetch("/api/trades?limit=25");
            const res = await resp.json();
            if (res.success) {
                renderTradesTable(res.trades);
            }
        } catch (e) {
            console.error("Erro ao buscar histórico:", e);
        }
    }

    function renderTradesTable(trades) {
        if (trades.length === 0) {
            tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-muted" style="text-align: center; padding: 2rem;">Nenhum trade realizado ainda.</td></tr>`;
            return;
        }

        tradesTableBody.innerHTML = trades.map(t => {
            const isProfit = t.pnl_usdt >= 0;
            const pnlClass = isProfit ? "text-green" : "text-red";
            return `
                <tr>
                    <td class="mono font-bold">${t.symbol}</td>
                    <td class="mono">$${t.buy_price.toFixed(4)}</td>
                    <td class="mono">$${t.sell_price.toFixed(4)}</td>
                    <td class="mono">${t.quantity.toFixed(4)} ($${t.invested_usdt.toFixed(2)})</td>
                    <td class="mono font-bold ${pnlClass}">
                        ${isProfit ? "+" : ""}$${t.pnl_usdt.toFixed(2)} (${isProfit ? "+" : ""}${t.pnl_pct.toFixed(2)}%)
                    </td>
                    <td><span class="badge-counter">${t.exit_reason}</span></td>
                    <td class="text-muted">${t.closed_at ? new Date(t.closed_at).toLocaleTimeString() : "-"}</td>
                </tr>
            `;
        }).join("");
    }

    async function refreshEvents() {
        try {
            const resp = await fetch("/api/events?limit=50");
            const res = await resp.json();
            if (res.success && eventsTableBody) {
                renderEventsTable(res.events);
            }
        } catch (e) {
            console.error("Erro ao buscar eventos:", e);
        }
    }

    function renderEventsTable(events) {
        if (!events || events.length === 0) {
            eventsTableBody.innerHTML = `<tr><td colspan="6" class="text-muted" style="text-align: center; padding: 2rem;">Nenhum evento registrado ainda.</td></tr>`;
            return;
        }

        eventsTableBody.innerHTML = events.map(e => {
            let levelColor = "var(--color-cyan)";
            if (e.level === "WARNING") levelColor = "#f59e0b";
            if (e.level === "ERROR" || e.level === "CRITICAL") levelColor = "#ef4444";
            if (e.level === "INFO") levelColor = "#10b981";

            const detailsStr = e.details ? (typeof e.details === "object" ? JSON.stringify(e.details) : e.details) : "-";

            return `
                <tr>
                    <td class="text-muted mono" style="font-size: 0.76rem;">${e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "-"}</td>
                    <td class="mono font-bold" style="font-size: 0.8rem;">${e.event_type}</td>
                    <td><span class="badge-counter" style="color: ${levelColor}; border-color: ${levelColor};">${e.level}</span></td>
                    <td class="mono">${e.symbol || "GLOBAL"}</td>
                    <td style="font-size: 0.82rem;">${e.message}</td>
                    <td class="mono text-muted" style="font-size: 0.74rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${detailsStr}">${detailsStr}</td>
                </tr>
            `;
        }).join("");
    }

    // ==========================================
    // GERENCIADOR DE PARES & EXCLUSÃO DE PARES
    // ==========================================

    if (btnOpenManagePairs) {
        btnOpenManagePairs.addEventListener("click", async () => {
            modalManagePairs.classList.add("open");
            await loadManagePairsTable();
        });
    }

    [btnCloseModalPairs, btnCancelManagePairs].forEach(btn => {
        if (btn) {
            btn.addEventListener("click", () => {
                modalManagePairs.classList.remove("open");
            });
        }
    });

    async function loadManagePairsTable() {
        managePairsTableBody.innerHTML = `<tr><td colspan="5" class="text-muted" style="text-align: center; padding: 2rem;">Carregando dados dos pares...</td></tr>`;
        try {
            const resp = await fetch("/api/assets/config");
            const data = await resp.json();
            if (data.success && data.assets) {
                renderManagePairsTable(data.assets);
            }
        } catch (e) {
            console.error("Erro ao carregar pares:", e);
            managePairsTableBody.innerHTML = `<tr><td colspan="5" class="text-red" style="text-align: center; padding: 1.5rem;">Erro ao carregar lista de pares.</td></tr>`;
        }
    }

    function renderManagePairsTable(assets) {
        const tfOptions = [
            { val: "1m", label: "1m (1 Minuto)" },
            { val: "3m", label: "3m (3 Minutos)" },
            { val: "5m", label: "5m (5 Minutos)" },
            { val: "15m", label: "15m (15 Minutos)" },
            { val: "30m", label: "30m (30 Minutos)" },
            { val: "1h", label: "1h (1 Hora)" },
            { val: "2h", label: "2h (2 Horas)" },
            { val: "4h", label: "4h (4 Horas)" },
            { val: "1d", label: "1d (1 Dia)" }
        ];

        managePairsTableBody.innerHTML = assets.map(a => {
            const isBuy = a.can_buy !== false;
            const optionsHtml = tfOptions.map(opt => `
                <option value="${opt.val}" ${opt.val === (a.timeframe || "1m") ? "selected" : ""}>${opt.label}</option>
            `).join("");

            let posHtml = `<span class="text-muted mono" style="font-size: 0.8rem;">Nenhuma</span>`;
            if (a.has_open_position) {
                const pnl = a.position_pnl || 0;
                const pnlColor = pnl >= 0 ? "text-green" : "text-red";
                posHtml = `<span class="${pnlColor} mono font-bold" style="font-size: 0.82rem;">ABERTA (${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%)</span>`;
            }

            return `
                <tr data-symbol="${a.symbol}">
                    <td class="mono font-bold" style="font-size: 0.92rem; vertical-align: middle;">
                        <span style="display: flex; align-items: center; gap: 0.35rem;">
                            <span>${a.symbol}</span>
                            ${a.symbol === currentSymbol ? '<span style="font-size: 0.65rem; background: rgba(0, 210, 255, 0.2); color: var(--color-cyan); padding: 0.1rem 0.35rem; border-radius: 4px;">ATIVO</span>' : ''}
                        </span>
                    </td>
                    <td style="text-align: center; vertical-align: middle;">
                        <label class="toggle-switch">
                            <input type="checkbox" class="pair-row-can-buy" ${isBuy ? "checked" : ""}>
                            <span class="toggle-slider"></span>
                        </label>
                    </td>
                    <td style="vertical-align: middle;">
                        <select class="form-input mono pair-row-timeframe" style="padding: 0.35rem 0.6rem; font-size: 0.82rem; font-weight: 600;">
                            ${optionsHtml}
                        </select>
                    </td>
                    <td style="text-align: center; vertical-align: middle;">${posHtml}</td>
                    <td style="text-align: center; vertical-align: middle;">
                        <button class="btn-delete-row" data-symbol="${a.symbol}" title="Excluir este par de monitoramento">🗑️ Excluir</button>
                    </td>
                </tr>
            `;
        }).join("");

        // Listener para EXCLUSÃO DE PARES (USER REQUEST)
        document.querySelectorAll(".btn-delete-row").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                const sym = e.target.getAttribute("data-symbol");
                if (!confirm(`Deseja realmente excluir o par ${sym}? Ele será removido do monitoramento do bot.`)) {
                    return;
                }

                try {
                    const resp = await fetch("/api/assets/delete", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ symbol: sym })
                    });
                    const data = await resp.json();

                    if (data.success) {
                        showToast(`Par ${sym} excluído com sucesso!`, "SUCCESS");
                        await loadManagePairsTable();

                        // Atualiza seletor de símbolos no header
                        if (data.symbols && data.symbols.length > 0) {
                            symbolSelect.innerHTML = data.symbols.map(s => `
                                <option value="${s}" ${s === currentSymbol && s !== sym ? 'selected' : ''}>${s}</option>
                            `).join("");

                            // Se o par excluído era o ativo no gráfico, muda para o primeiro da lista
                            if (currentSymbol === sym) {
                                loadSymbolData(data.symbols[0]);
                            }
                        }
                    } else {
                        showToast(data.error || "Erro ao excluir par.", "ERROR");
                    }
                } catch (err) {
                    showToast("Erro na comunicação com o servidor ao excluir par.", "ERROR");
                }
            });
        });
    }

    if (btnBulkEnableBuy) {
        btnBulkEnableBuy.addEventListener("click", () => {
            document.querySelectorAll(".pair-row-can-buy").forEach(chk => chk.checked = true);
        });
    }

    if (btnBulkDisableBuy) {
        btnBulkDisableBuy.addEventListener("click", () => {
            document.querySelectorAll(".pair-row-can-buy").forEach(chk => chk.checked = false);
        });
    }

    if (btnSaveManagePairs) {
        btnSaveManagePairs.addEventListener("click", async () => {
            const rows = document.querySelectorAll("#manage-pairs-table-body tr[data-symbol]");
            const updates = [];

            rows.forEach(tr => {
                const sym = tr.getAttribute("data-symbol");
                const chk = tr.querySelector(".pair-row-can-buy");
                const sel = tr.querySelector(".pair-row-timeframe");
                if (sym && chk && sel) {
                    updates.push({
                        symbol: sym,
                        can_buy: chk.checked,
                        timeframe: sel.value
                    });
                }
            });

            btnSaveManagePairs.textContent = "Salvando...";
            btnSaveManagePairs.disabled = true;

            try {
                const resp = await fetch("/api/assets/bulk-update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ updates })
                });
                const data = await resp.json();

                if (data.success) {
                    showToast(`${updates.length} pares atualizados com sucesso!`, "SUCCESS");
                    modalManagePairs.classList.remove("open");
                    await loadConfig(currentSymbol);
                } else {
                    showToast(data.error || "Erro ao salvar alterações.", "ERROR");
                }
            } catch (err) {
                showToast("Erro ao conectar com o servidor.", "ERROR");
            } finally {
                btnSaveManagePairs.textContent = "Salvar Alterações";
                btnSaveManagePairs.disabled = false;
            }
        });
    }

    // ==========================================
    // PARADA DE EMERGÊNCIA (KILL SWITCH - RF-KILL)
    // ==========================================

    if (btnOpenKillSwitch) {
        btnOpenKillSwitch.addEventListener("click", () => {
            if (isKillSwitchActive) {
                // Se já ativo, prompt para reativar
                if (confirm("O Kill Switch está atualmente ATIVO. Deseja desativá-lo e restabelecer a operação normal do bot?")) {
                    triggerKillSwitch(false);
                }
            } else {
                modalKillSwitch.classList.add("open");
            }
        });
    }

    [btnCloseModalKill, btnCancelKillSwitch].forEach(btn => {
        if (btn) {
            btn.addEventListener("click", () => {
                modalKillSwitch.classList.remove("open");
            });
        }
    });

    if (btnConfirmKillSwitch) {
        btnConfirmKillSwitch.addEventListener("click", async () => {
            const mode = killSwitchModeSelect.value;
            const reason = killSwitchReason.value.trim() || "Acionamento manual via painel";
            await triggerKillSwitch(true, mode, reason);
            modalKillSwitch.classList.remove("open");
        });
    }

    async function triggerKillSwitch(active, mode = "PARADA_OPERACIONAL", reason = "") {
        try {
            const resp = await fetch("/api/kill-switch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ active, mode, reason })
            });
            const data = await resp.json();
            if (data.success) {
                showToast(active ? "🛑 PARADA DE EMERGÊNCIA (Kill Switch) ATIVADA!" : "✅ Kill Switch Desativado. Operação retomada.", active ? "ERROR" : "SUCCESS");
                updateOperationalStatusUI(data.operational);
                refreshPositions();
                refreshOrders();
                refreshEvents();
            }
        } catch (e) {
            showToast("Erro ao acionar comando Kill Switch.", "ERROR");
        }
    }

    // ==========================================
    // MODO EXPLICAR (RF-EXPLAIN)
    // ==========================================

    if (btnExplainDecision) {
        btnExplainDecision.addEventListener("click", async () => {
            modalExplainDecision.classList.add("open");
            explainContent.innerHTML = `<p class="text-muted">Analisando dados do mercado e estratégia para ${currentSymbol}...</p>`;
            try {
                const resp = await fetch(`/api/explain?symbol=${currentSymbol}`);
                const data = await resp.json();
                if (data.success && data.explanation) {
                    renderExplanation(data.explanation);
                } else {
                    explainContent.innerHTML = `<p class="text-red">Não foi possível gerar explicação no momento.</p>`;
                }
            } catch (e) {
                explainContent.innerHTML = `<p class="text-red">Erro ao carregar diagnóstico: ${e}</p>`;
            }
        });
    }

    function renderExplanation(exp) {
        const detailsList = exp.details.map(d => `<li style="margin-bottom: 0.35rem;">${d}</li>`).join("");
        explainContent.innerHTML = `
            <div style="margin-bottom: 1rem;">
                <span class="brand-badge" style="background: rgba(0, 210, 255, 0.2); color: var(--color-cyan); margin-bottom: 0.5rem; display: inline-block;">
                    ${exp.symbol} — Estado: ${exp.operational_status}
                </span>
                <div class="explain-box">
                    <strong style="color: #fff; font-size: 0.95rem;">Resumo da Decisão:</strong>
                    <p style="margin-top: 0.4rem; color: #38bdf8; font-weight: 600; line-height: 1.4;">
                        ${exp.summary}
                    </p>
                </div>
            </div>
            <div>
                <strong style="font-size: 0.85rem; color: var(--text-dim);">Detalhamento dos Indicadores e Limites:</strong>
                <ul style="padding-left: 1.25rem; margin-top: 0.5rem; font-size: 0.84rem; color: #e2e8f0;">
                    ${detailsList}
                </ul>
            </div>
        `;
    }

    [btnCloseModalExplain, btnCloseExplainOk].forEach(btn => {
        if (btn) {
            btn.addEventListener("click", () => {
                modalExplainDecision.classList.remove("open");
            });
        }
    });

    // ==========================================
    // MODAIS: ADICIONAR PAR E MODO REAL
    // ==========================================

    btnOpenAddAsset.addEventListener("click", () => {
        modalAddAsset.classList.add("open");
        inputNewSymbol.value = "";
        inputNewSymbol.focus();
    });

    [btnCloseModalAsset, btnCancelAddAsset].forEach(btn => {
        btn.addEventListener("click", () => {
            modalAddAsset.classList.remove("open");
        });
    });

    btnConfirmAddAsset.addEventListener("click", async () => {
        const raw = inputNewSymbol.value.trim().toUpperCase();
        if (!raw) {
            showToast("Informe o símbolo do par (ex: ADA ou ADAUSDT)", "WARNING");
            return;
        }

        btnConfirmAddAsset.textContent = "Validando...";
        btnConfirmAddAsset.disabled = true;

        try {
            const resp = await fetch("/api/assets/add", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ symbol: raw })
            });
            const data = await resp.json();

            if (data.success) {
                showToast(`Par ${data.symbol} validado e adicionado com sucesso!`, "SUCCESS");
                modalAddAsset.classList.remove("open");

                symbolSelect.innerHTML = data.symbols.map(s => `
                    <option value="${s}" ${s === data.symbol ? 'selected' : ''}>${s}</option>
                `).join("");

                loadSymbolData(data.symbol);
            } else {
                showToast(data.error || "Erro ao adicionar par.", "ERROR");
            }
        } catch (err) {
            showToast("Erro na comunicação com o servidor.", "ERROR");
        } finally {
            btnConfirmAddAsset.textContent = "Validar & Adicionar";
            btnConfirmAddAsset.disabled = false;
        }
    });

    // Modal Modo Real
    btnToggleMode.addEventListener("click", () => {
        if (currentExecutionMode === "PAPER") {
            modalConfirmReal.classList.add("open");
        } else {
            setExecutionMode("PAPER");
        }
    });

    [btnCloseModalReal, btnCancelRealMode].forEach(btn => {
        btn.addEventListener("click", () => {
            modalConfirmReal.classList.remove("open");
        });
    });

    btnConfirmRealMode.addEventListener("click", async () => {
        await setExecutionMode("REAL");
        modalConfirmReal.classList.remove("open");
    });

    async function setExecutionMode(mode) {
        try {
            const resp = await fetch("/api/mode", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode })
            });
            const res = await resp.json();
            if (res.success) {
                updateExecutionModeUI(res.mode);
                showToast(`Modo alterado para ${res.mode === 'REAL' ? 'MODO REAL' : 'SIMULAÇÃO'}`, "INFO");
            } else {
                showToast(res.error || "Não foi possível alterar modo.", "ERROR");
            }
        } catch (e) {
            showToast("Erro ao alternar modo de execução.", "ERROR");
        }
    }

    // ==========================================
    // LISTENERS DE WEBSOCKET (SOCKET.IO)
    // ==========================================

    socket.on("kline_update", (data) => {
        if (data.symbol === currentSymbol) {
            if (data.timeframe === currentTimeframe.toLowerCase()) {
                lastKnownPrice = data.candle.close;
                currentPriceEl.textContent = `$${data.candle.close.toFixed(2)}`;
                chartManager.updateTick(data.candle, data.indicators);

                if (data.indicators) {
                    const ind = data.indicators;
                    if (ind.rsi !== null) {
                        rsiValEl.textContent = ind.rsi.toFixed(1);
                        rsiValEl.className = ind.rsi <= 30 ? "text-green font-bold" : (ind.rsi >= 70 ? "text-red font-bold" : "mono");
                    }
                    if (ind.bb_upper !== null) bbUpperEl.textContent = `$${ind.bb_upper.toFixed(2)}`;
                    if (ind.bb_middle !== null) bbMiddleEl.textContent = `$${ind.bb_middle.toFixed(2)}`;
                    if (ind.bb_lower !== null) bbLowerEl.textContent = `$${ind.bb_lower.toFixed(2)}`;
                }
            }
            updatePercentagePreviews();
        }
    });

    socket.on("ticker_update", (ticker) => {
        if (ticker.symbol === currentSymbol) {
            lastKnownPrice = ticker.price;
            currentPriceEl.textContent = `$${ticker.price.toFixed(2)}`;
            const isPositive = ticker.price_change_pct >= 0;
            priceChangeEl.textContent = `${isPositive ? "+" : ""}${ticker.price_change_pct.toFixed(2)}%`;
            priceChangeEl.className = `price-change-badge ${isPositive ? 'bg-green-badge' : 'bg-red-badge'}`;

            tickerHighEl.textContent = `$${ticker.high.toFixed(2)}`;
            tickerLowEl.textContent = `$${ticker.low.toFixed(2)}`;
            tickerVolEl.textContent = ticker.volume.toFixed(1);

            updatePercentagePreviews();
        }
    });

    socket.on("portfolio_summary", (data) => {
        portfolioEquityEl.textContent = `$${data.total_equity_usdt.toFixed(2)}`;
        portfolioOpenCapEl.textContent = `$${data.total_open_capital.toFixed(2)}`;

        const pnl = data.total_realized_pnl;
        portfolioRealizedPnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
        portfolioRealizedPnlEl.className = `metric-value mono ${pnl >= 0 ? 'text-green' : 'text-red'}`;

        portfolioWinRateEl.textContent = `${data.win_rate.toFixed(1)}%`;
        portfolioTotalTradesEl.textContent = `${data.total_trades} trades (${data.winning_trades} wins)`;
    });

    socket.on("ws_status_update", (data) => {
        updateWsStatusUI(data.status);
    });

    socket.on("operational_status_changed", (data) => {
        updateOperationalStatusUI(data);
    });

    socket.on("asset_added", (data) => {
        if (data.symbols) {
            const selected = symbolSelect.value;
            symbolSelect.innerHTML = data.symbols.map(s => `
                <option value="${s}" ${s === selected ? 'selected' : ''}>${s}</option>
            `).join("");
        }
    });

    socket.on("asset_deleted", (data) => {
        if (data.symbols) {
            const selected = symbolSelect.value;
            symbolSelect.innerHTML = data.symbols.map(s => `
                <option value="${s}" ${s === selected && s !== data.symbol ? 'selected' : ''}>${s}</option>
            `).join("");
            if (currentSymbol === data.symbol && data.symbols.length > 0) {
                loadSymbolData(data.symbols[0]);
            }
        }
    });

    socket.on("order_update", () => {
        refreshOrders();
        fetch(`/api/chart-data?symbol=${currentSymbol}`)
            .then(r => r.json())
            .then(d => {
                if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
            });
    });

    socket.on("position_opened", () => {
        refreshPositions();
        refreshOrders();
        refreshEvents();
        fetch(`/api/chart-data?symbol=${currentSymbol}`)
            .then(r => r.json())
            .then(d => {
                if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
            });
    });

    socket.on("position_closed", () => {
        refreshPositions();
        refreshOrders();
        refreshTrades();
        refreshEvents();
        fetch(`/api/chart-data?symbol=${currentSymbol}`)
            .then(r => r.json())
            .then(d => {
                if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
            });
    });

    socket.on("stop_updated", (payload) => {
        if (payload.symbol === currentSymbol) {
            fetch(`/api/chart-data?symbol=${currentSymbol}`)
                .then(r => r.json())
                .then(d => {
                    if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
                });
            refreshPositions();
        }
    });

    socket.on("trade_alert", (alert) => {
        showToast(alert.message, alert.type);
    });

    socket.on("bot_status_changed", (data) => {
        if (!data.symbol || data.symbol === currentSymbol) {
            updateBotStatusUI(data.is_bot_running);
        }
    });

    // ==========================================
    // INTERAÇÕES DA INTERFACE
    // ==========================================

    symbolSelect.addEventListener("change", (e) => {
        loadSymbolData(e.target.value);
    });

    timeframeBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            timeframeBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTimeframe = btn.getAttribute("data-tf");
            loadSymbolData(currentSymbol);
        });
    });

    botToggleBtn.addEventListener("click", async () => {
        const resp = await fetch("/api/bot/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol: currentSymbol })
        });
        const res = await resp.json();
        if (res.success) {
            showToast(res.is_bot_running ? "Bot ativado!" : "Bot pausado!", "INFO");
        }
    });

    document.getElementById("btn-reset-paper").addEventListener("click", async () => {
        if (confirm("Deseja realmente resetar o saldo de simulação (paper trading) e fechar posições?")) {
            await fetch("/api/paper/reset", { method: "POST" });
            showToast("Ambiente de simulação resetado para $10,000 USDT.", "INFO");
            loadSymbolData(currentSymbol);
        }
    });

    // Salvar Configurações
    configForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
            rsi_period: parseInt(rsiPeriodInput.value),
            rsi_oversold: parseFloat(rsiOversoldInput.value),
            bb_period: parseInt(bbPeriodInput.value),
            bb_std: parseFloat(bbStdInput.value),
            activation_trigger: triggerModeSelect.value,
            trailing_buy_delta: parseFloat(trailingBuyDeltaInput.value) / 100.0,
            buy_hysteresis: parseFloat(buyHysteresisInput.value) / 100.0,
            trailing_stop_delta: parseFloat(trailingStopDeltaInput.value) / 100.0,
            sell_hysteresis: parseFloat(sellHysteresisInput.value) / 100.0,
            base_order_usdt: parseFloat(baseOrderUsdtInput.value),
            max_order_amount_usdt: maxOrderAmountInput ? parseFloat(maxOrderAmountInput.value) : 150.0,
            max_entries_count: maxEntriesInput ? parseInt(maxEntriesInput.value) : 5,
            max_asset_allocation_usdt: parseFloat(maxAssetAllocInput.value),
            max_total_open_capital_usdt: parseFloat(maxTotalOpenInput.value),
            drop_multiplier: parseFloat(dropMultInput.value),
            drop_threshold_pct: parseFloat(dropThreshInput.value) / 100.0,
            can_buy: cfgCanBuy ? cfgCanBuy.checked : true,
            timeframe: cfgStrategyTimeframe ? cfgStrategyTimeframe.value : "1m"
        };

        try {
            const resp = await fetch(`/api/config?symbol=${currentSymbol}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const res = await resp.json();
            if (res.success) {
                showToast("Parâmetros do ativo atualizados com sucesso!", "SUCCESS");
                updatePercentagePreviews();
                if (res.config && res.config.can_buy !== undefined) {
                    updateCanBuyUI(res.config.can_buy);
                }
            }
        } catch (err) {
            showToast("Erro ao salvar parâmetros.", "ERROR");
        }
    });

    if (cfgCanBuy) {
        cfgCanBuy.addEventListener("change", (e) => {
            updateCanBuyUI(e.target.checked);
        });
    }

    // Abas das Tabelas
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabName = btn.getAttribute("data-tab");
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.style.display = "none");

            btn.classList.add("active");
            const target = document.getElementById(`tab-${tabName}`);
            if (target) target.style.display = "block";

            if (tabName === "events") {
                refreshEvents();
            }
        });
    });

    function showToast(message, type = "INFO") {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = "toast";

        let color = "var(--color-cyan)";
        if (type === "SUCCESS") color = "var(--color-green)";
        if (type === "ERROR" || type === "WARNING") color = "var(--color-red)";

        toast.style.borderLeft = `4px solid ${color}`;
        toast.innerHTML = `<div>${message}</div>`;

        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transition = "opacity 0.3s ease";
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // Inicialização da Página
    fetch("/api/system/status")
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                updateOperationalStatusUI(d.operational);
                updateWsStatusUI(d.ws_status);
            }
        })
        .catch(e => console.error("Erro ao obter status inicial:", e));

    loadSymbolData(currentSymbol);
});
