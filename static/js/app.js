/**
 * Orquestrador da Interface do Bot Binance (WebSocket + UI + Eventos)
 * Inclui:
 * - Adição dinâmica de novos pares de criptoativos
 * - Alternância entre Modo Simulação (Paper) e Modo Real (Binance Spot)
 * - Pré-visualização em tempo real de valores com percentuais calculados (Delta e Histerese)
 * - Tooltips e notificações
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

    // Botão e Modais
    const btnOpenAddAsset = document.getElementById("btn-open-add-asset");
    const modalAddAsset = document.getElementById("modal-add-asset");
    const inputNewSymbol = document.getElementById("input-new-symbol");
    const btnConfirmAddAsset = document.getElementById("btn-confirm-add-asset");
    const btnCloseModalAsset = document.getElementById("btn-close-modal-asset");
    const btnCancelAddAsset = document.getElementById("btn-cancel-add-asset");

    const modalConfirmReal = document.getElementById("modal-confirm-real");
    const btnConfirmRealMode = document.getElementById("btn-confirm-real-mode");
    const btnCloseModalReal = document.getElementById("btn-close-modal-real");
    const btnCancelRealMode = document.getElementById("btn-cancel-real-mode");

    // Controles de Permissão de Compra e Timeframe por Par
    const currentPairCanBuyBadge = document.getElementById("current-pair-can-buy-badge");
    const btnOpenManagePairs = document.getElementById("btn-open-manage-pairs");
    const modalManagePairs = document.getElementById("modal-manage-pairs");
    const btnCloseModalPairs = document.getElementById("btn-close-modal-pairs");
    const btnCancelManagePairs = document.getElementById("btn-cancel-manage-pairs");
    const btnSaveManagePairs = document.getElementById("btn-save-manage-pairs");
    const btnBulkEnableBuy = document.getElementById("btn-bulk-enable-buy");
    const btnBulkDisableBuy = document.getElementById("btn-bulk-disable-buy");
    const managePairsTableBody = document.getElementById("manage-pairs-table-body");

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
    const maxAssetAllocInput = document.getElementById("cfg-max-asset");
    const maxTotalOpenInput = document.getElementById("cfg-max-total");
    const dropMultInput = document.getElementById("cfg-drop-mult");
    const dropThreshInput = document.getElementById("cfg-drop-thresh");

    // Elementos de Pré-Visualização de Cálculo em Tempo Real
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
    const ordersBadge = document.getElementById("badge-orders-count");
    const positionsBadge = document.getElementById("badge-positions-count");

    let currentSymbol = symbolSelect.value || "BTCUSDT";
    let currentTimeframe = "1m";
    let lastKnownPrice = 0.0;
    let currentExecutionMode = "PAPER";

    // ==========================================
    // CÁLCULO DINÂMICO DOS PERCENTUAIS
    // ==========================================

    function updatePercentagePreviews() {
        const p = lastKnownPrice > 0 ? lastKnownPrice : (parseFloat(currentPriceEl.textContent.replace(/[^0-9.]/g, "")) || 0);
        if (p <= 0) return;

        // 1. Delta Trailing Buy (%)
        const tbDeltaPct = parseFloat(trailingBuyDeltaInput.value) || 0;
        const tbDeltaVal = p * (tbDeltaPct / 100.0);
        const estBuyTrigger = p + tbDeltaVal;
        previewTbDelta.innerHTML = `<span>+ $${tbDeltaVal.toFixed(4)}</span> &rarr; <strong class="mono">Gatilho est.: $${estBuyTrigger.toFixed(4)}</strong>`;

        // 2. Histerese de Compra (%)
        const buyHystPct = parseFloat(buyHysteresisInput.value) || 0;
        const buyHystVal = p * (buyHystPct / 100.0);
        const recalcThreshold = p - buyHystVal;
        previewBuyHyst.innerHTML = `<span>Tolerância: $${buyHystVal.toFixed(4)}</span> (Reajuste se cair &lt; <strong>$${recalcThreshold.toFixed(4)}</strong>)`;

        // 3. Delta Trailing Stop (%)
        const tsDeltaPct = parseFloat(trailingStopDeltaInput.value) || 0;
        const tsDeltaVal = p * (tsDeltaPct / 100.0);
        const estStopTrigger = p - tsDeltaVal;
        previewTsDelta.innerHTML = `<span>- $${tsDeltaVal.toFixed(4)}</span> &rarr; <strong class="mono">Stop est.: $${estStopTrigger.toFixed(4)}</strong>`;

        // 4. Histerese de Venda (%)
        const sellHystPct = parseFloat(sellHysteresisInput.value) || 0;
        const sellHystVal = p * (sellHystPct / 100.0);
        const advanceTarget = p + sellHystVal;
        previewSellHyst.innerHTML = `<span>Avanço mín.: +$${sellHystVal.toFixed(4)}</span> (Sobe stop se &gt; <strong>$${advanceTarget.toFixed(4)}</strong>)`;
    }

    // Ouvintes para recalcular sempre que o usuário digitar nos percentuais
    [trailingBuyDeltaInput, buyHysteresisInput, trailingStopDeltaInput, sellHysteresisInput].forEach(inp => {
        inp.addEventListener("input", updatePercentagePreviews);
    });

    // ==========================================
    // CARREGAMENTO DE DADOS INICIAIS DO ATIVO
    // ==========================================

    async function loadSymbolData(symbol) {
        currentSymbol = symbol;
        try {
            const resp = await fetch(`/api/chart-data?symbol=${symbol}&timeframe=${currentTimeframe}`);
            const data = await resp.json();

            if (data.success && data.chart_data) {
                chartManager.loadInitialData(data.chart_data);
                chartManager.updateDynamicLines(data.position, data.active_orders);

                if (data.chart_data.candles && data.chart_data.candles.length > 0) {
                    const lastCandle = data.chart_data.candles[data.chart_data.candles.length - 1];
                    lastKnownPrice = lastCandle.close;
                    currentPriceEl.textContent = `$${lastCandle.close.toFixed(2)}`;
                    updatePercentagePreviews();
                }
            }

            // Carrega parâmetros do ativo
            await loadConfig(symbol);
            // Atualiza tabelas
            await refreshOrders();
            await refreshPositions();
            await refreshTrades();
        } catch (err) {
            console.error("Erro ao carregar dados do ativo:", err);
            showToast("Erro ao conectar com servidor de dados.", "ERROR");
        }
    }

    async function loadConfig(symbol) {
        try {
            const resp = await fetch(`/api/config?symbol=${symbol}`);
            const res = await resp.json();
            if (res.success && res.config) {
                const c = res.config;
                rsiPeriodInput.value = c.rsi_period;
                rsiOversoldInput.value = c.rsi_oversold;
                bbPeriodInput.value = c.bb_period;
                bbStdInput.value = c.bb_std;
                triggerModeSelect.value = c.activation_trigger;
                trailingBuyDeltaInput.value = (c.trailing_buy_delta * 100).toFixed(2);
                buyHysteresisInput.value = (c.buy_hysteresis * 100).toFixed(2);
                trailingStopDeltaInput.value = (c.trailing_stop_delta * 100).toFixed(2);
                sellHysteresisInput.value = (c.sell_hysteresis * 100).toFixed(2);
                baseOrderUsdtInput.value = c.base_order_usdt;
                maxAssetAllocInput.value = c.max_asset_allocation_usdt;
                maxTotalOpenInput.value = c.max_total_open_capital_usdt;
                dropMultInput.value = c.drop_multiplier;
                dropThreshInput.value = (c.drop_threshold_pct * 100).toFixed(2);

                // Permissão de Compra e Timeframe do Par
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
            currentPairCanBuyBadge.title = "Novas compras estão pausadas para este par. Posições abertas continuam protegidas pelo Trailing Stop.";
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
            positionsTableBody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align: center; padding: 2rem;">Nenhuma posição aberta no momento.</td></tr>`;
            return;
        }

        positionsTableBody.innerHTML = positions.map(p => {
            const isProfit = p.unrealized_pnl_usdt >= 0;
            const pnlClass = isProfit ? "text-green" : "text-red";
            return `
                <tr>
                    <td class="mono font-bold">${p.symbol}</td>
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

    // ==========================================
    // MODAIS: ADICIONAR PAR E MODO REAL
    // ==========================================

    // Modal Adicionar Par
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

                // Atualiza o select de símbolos
                symbolSelect.innerHTML = data.symbols.map(s => `
                    <option value="${s}" ${s === data.symbol ? 'selected' : ''}>${s}</option>
                `).join("");

                // Carrega o novo ativo
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
            // Abre confirmação para ir para REAL
            modalConfirmReal.classList.add("open");
        } else {
            // Volta imediatamente para SIMULAÇÃO
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
                showToast(`Modo alterado para ${res.mode === 'REAL' ? 'REAL (Binance Spot)' : 'SIMULAÇÃO'}!`, res.mode === 'REAL' ? 'WARNING' : 'INFO');
            } else {
                showToast(res.error || "Erro ao alternar modo.", "ERROR");
            }
        } catch (err) {
            showToast("Erro ao conectar com o servidor.", "ERROR");
        }
    }

    // ==========================================
    // SOCKET.IO EVENTOS EM TEMPO REAL
    // ==========================================

    socket.on("connect", () => {
        console.log("Conectado ao servidor Socket.IO");
        socket.emit("request_state", { symbol: currentSymbol });
    });

    socket.on("kline_update", (data) => {
        if (data.symbol === currentSymbol) {
            lastKnownPrice = data.candle.close;

            // Só atualiza os candles do gráfico se o tick pertencer ao timeframe que o usuário está visualizando no momento
            const dataTf = (data.timeframe || "").toLowerCase();
            const currentTf = (currentTimeframe || "").toLowerCase();

            if (!dataTf || dataTf === currentTf) {
                chartManager.updateTick(data.candle, data.indicators);

                // Atualiza chips de indicadores no topo
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

    socket.on("asset_added", (data) => {
        if (data.symbols) {
            const selected = symbolSelect.value;
            symbolSelect.innerHTML = data.symbols.map(s => `
                <option value="${s}" ${s === selected ? 'selected' : ''}>${s}</option>
            `).join("");
        }
    });

    socket.on("execution_mode_changed", (data) => {
        updateExecutionModeUI(data.mode);
    });

    socket.on("order_update", (payload) => {
        refreshOrders();
        fetch(`/api/chart-data?symbol=${currentSymbol}`)
            .then(r => r.json())
            .then(d => {
                if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
            });
    });

    socket.on("position_opened", (payload) => {
        refreshPositions();
        refreshOrders();
        fetch(`/api/chart-data?symbol=${currentSymbol}`)
            .then(r => r.json())
            .then(d => {
                if (d.success) chartManager.updateDynamicLines(d.position, d.active_orders);
            });
    });

    socket.on("position_closed", (payload) => {
        refreshPositions();
        refreshOrders();
        refreshTrades();
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
    // INTERAÇÕES DA INTERFACE (LISTENERS)
    // ==========================================

    // Mudança de Ativo
    symbolSelect.addEventListener("change", (e) => {
        loadSymbolData(e.target.value);
    });

    // Mudança de Timeframe
    timeframeBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            timeframeBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTimeframe = btn.getAttribute("data-tf");
            loadSymbolData(currentSymbol);
        });
    });

    // Toggle Bot
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

    // Reset Paper Trading
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

    // Ouvinte de alteração instantânea no toggle de compra do formulário
    if (cfgCanBuy) {
        cfgCanBuy.addEventListener("change", (e) => {
            updateCanBuyUI(e.target.checked);
        });
    }

    // ==========================================
    // GERENCIADOR DE PARES & GATILHOS (MODAL)
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
        managePairsTableBody.innerHTML = `<tr><td colspan="4" class="text-muted" style="text-align: center; padding: 2rem;">Carregando dados dos pares...</td></tr>`;
        try {
            const resp = await fetch("/api/assets/config");
            const data = await resp.json();
            if (data.success && data.assets) {
                renderManagePairsTable(data.assets);
            }
        } catch (e) {
            console.error("Erro ao carregar pares:", e);
            managePairsTableBody.innerHTML = `<tr><td colspan="4" class="text-red" style="text-align: center; padding: 1.5rem;">Erro ao carregar lista de pares.</td></tr>`;
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
                </tr>
            `;
        }).join("");
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
                    // Recarrega configuração do ativo ativo
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

    // Abas das Tabelas
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabName = btn.getAttribute("data-tab");
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.style.display = "none");

            btn.classList.add("active");
            document.getElementById(`tab-${tabName}`).style.display = "block";
        });
    });

    // Função de Toast
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
    loadSymbolData(currentSymbol);
});
