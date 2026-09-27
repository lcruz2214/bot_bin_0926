/**
 * Gerenciador dos gráficos TradingView Lightweight Charts
 * Suporta Candlesticks, Bandas de Bollinger sobrepostas, Subgráfico de RSI (14)
 * e linhas de preço dinâmicas para Trailing Buy, Trailing Stop e Preço Médio de Posição.
 */

class BotChartManager {
    constructor(candlestickContainerId, rsiContainerId) {
        this.candleContainer = document.getElementById(candlestickContainerId);
        this.rsiContainer = document.getElementById(rsiContainerId);

        this.candleChart = null;
        this.rsiChart = null;

        this.candleSeries = null;
        this.bbUpperSeries = null;
        this.bbMiddleSeries = null;
        this.bbLowerSeries = null;
        this.rsiSeries = null;

        // Linhas horizontais de preço dinâmicas
        this.trailingBuyLine = null;
        this.trailingStopLine = null;
        this.positionEntryLine = null;

        this.currentSymbol = "BTCUSDT";

        this.initCharts();
        this.handleResize();
    }

    initCharts() {
        const chartTheme = {
            layout: {
                background: { color: "#111726" },
                textColor: "#94a3b8",
                fontSize: 12,
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
            },
            grid: {
                vertLines: { color: "#1e293b", style: 1 },
                horzLines: { color: "#1e293b", style: 1 }
            },
            crosshair: {
                mode: 1, // Magnet
                vertLine: { color: "#64748b", width: 1, style: 3 },
                horzLine: { color: "#64748b", width: 1, style: 3 }
            },
            timeScale: {
                borderColor: "#1e293b",
                timeVisible: true,
                secondsVisible: false
            }
        };

        // 1. Gráfico Principal de Candles
        this.candleChart = LightweightCharts.createChart(this.candleContainer, {
            ...chartTheme,
            height: this.candleContainer.clientHeight || 400,
            rightPriceScale: {
                borderColor: "#1e293b",
                autoScale: true
            }
        });

        this.candleSeries = this.candleChart.addCandlestickSeries({
            upColor: "#00f5a0",
            downColor: "#ff385c",
            borderUpColor: "#00f5a0",
            borderDownColor: "#ff385c",
            wickUpColor: "#00f5a0",
            wickDownColor: "#ff385c"
        });

        // Bandas de Bollinger sobrepostas
        this.bbUpperSeries = this.candleChart.addLineSeries({
            color: "#38bdf8",
            lineWidth: 1,
            lineStyle: 2, // Tracejado
            title: "BB Superior"
        });

        this.bbMiddleSeries = this.candleChart.addLineSeries({
            color: "#fbbf24",
            lineWidth: 1,
            lineStyle: 0, // Sólido
            title: "BB Média (SMA 20)"
        });

        this.bbLowerSeries = this.candleChart.addLineSeries({
            color: "#818cf8",
            lineWidth: 1,
            lineStyle: 2, // Tracejado
            title: "BB Inferior"
        });

        // 2. Subgráfico de RSI
        this.rsiChart = LightweightCharts.createChart(this.rsiContainer, {
            ...chartTheme,
            height: this.rsiContainer.clientHeight || 140,
            rightPriceScale: {
                borderColor: "#1e293b",
                scaleMargins: { top: 0.1, bottom: 0.1 },
                autoScale: false
            }
        });

        this.rsiSeries = this.rsiChart.addLineSeries({
            color: "#a855f7",
            lineWidth: 2,
            title: "RSI (14)"
        });

        // Linhas de Sobrecompra (70) e Sobrevenda (30) no RSI
        this.rsiSeries.createPriceLine({
            price: 70,
            color: "#ff385c",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: "Sobrecompra (70)"
        });

        this.rsiSeries.createPriceLine({
            price: 30,
            color: "#00f5a0",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: "Sobrevenda (30)"
        });

        // Sincronização de zoom e pan horizontal entre Gráfico Principal e RSI
        let isSyncing = false;
        const syncCharts = (source, target) => {
            source.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (isSyncing || !range) return;
                isSyncing = true;
                target.timeScale().setVisibleLogicalRange(range);
                isSyncing = false;
            });
        };

        syncCharts(this.candleChart, this.rsiChart);
        syncCharts(this.rsiChart, this.candleChart);
    }

    handleResize() {
        window.addEventListener("resize", () => {
            if (this.candleChart && this.candleContainer) {
                this.candleChart.applyOptions({
                    width: this.candleContainer.clientWidth,
                    height: this.candleContainer.clientHeight || 400
                });
            }
            if (this.rsiChart && this.rsiContainer) {
                this.rsiChart.applyOptions({
                    width: this.rsiContainer.clientWidth,
                    height: this.rsiContainer.clientHeight || 140
                });
            }
        });
    }

    loadInitialData(data) {
        if (!data || !data.candles || data.candles.length === 0) return;

        this.currentSymbol = data.symbol || this.currentSymbol;

        // Atualiza Séries
        this.candleSeries.setData(data.candles);
        if (data.bb_upper) this.bbUpperSeries.setData(data.bb_upper);
        if (data.bb_middle) this.bbMiddleSeries.setData(data.bb_middle);
        if (data.bb_lower) this.bbLowerSeries.setData(data.bb_lower);
        if (data.rsi) this.rsiSeries.setData(data.rsi);

        this.candleChart.timeScale().fitContent();
        this.rsiChart.timeScale().fitContent();
    }

    updateTick(candle, indicators) {
        if (!candle) return;

        // Atualiza candle em tempo real
        this.candleSeries.update(candle);

        const t = candle.time;

        if (indicators) {
            if (indicators.bb_upper !== null) this.bbUpperSeries.update({ time: t, value: indicators.bb_upper });
            if (indicators.bb_middle !== null) this.bbMiddleSeries.update({ time: t, value: indicators.bb_middle });
            if (indicators.bb_lower !== null) this.bbLowerSeries.update({ time: t, value: indicators.bb_lower });
            if (indicators.rsi !== null) this.rsiSeries.update({ time: t, value: indicators.rsi });
        }
    }

    // ==========================================
    // LINHAS DE PREÇO DINÂMICAS NO GRÁFICO
    // ==========================================

    updateDynamicLines(position, activeOrders) {
        // 1. Linha de Posição Aberta (Preço Médio de Entrada)
        if (this.positionEntryLine) {
            this.candleSeries.removePriceLine(this.positionEntryLine);
            this.positionEntryLine = null;
        }
        if (position && position.status === "OPEN" && position.entry_price > 0) {
            this.positionEntryLine = this.candleSeries.createPriceLine({
                price: position.entry_price,
                color: "#fbbf24", // Dourado
                lineWidth: 2,
                lineStyle: 0,
                axisLabelVisible: true,
                title: `Posição @ $${position.entry_price.toFixed(2)}`
            });
        }

        // 2. Linha de Trailing Stop
        if (this.trailingStopLine) {
            this.candleSeries.removePriceLine(this.trailingStopLine);
            this.trailingStopLine = null;
        }
        // Se houver posição aberta, o stop vem dela ou da ordem ativa
        const stopPrice = position && position.status === "OPEN"
            ? position.trailing_stop_price
            : (activeOrders || []).find(o => o.order_type === "TRAILING_STOP")?.trigger_price;

        if (stopPrice && stopPrice > 0) {
            this.trailingStopLine = this.candleSeries.createPriceLine({
                price: stopPrice,
                color: "#ff385c", // Vermelho
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: `Trailing Stop @ $${stopPrice.toFixed(2)}`
            });
        }

        // 3. Linha de Trailing Buy
        if (this.trailingBuyLine) {
            this.candleSeries.removePriceLine(this.trailingBuyLine);
            this.trailingBuyLine = null;
        }
        const buyOrder = (activeOrders || []).find(o => o.order_type === "TRAILING_BUY" && o.status === "ARMED");
        if (buyOrder && buyOrder.trigger_price > 0) {
            this.trailingBuyLine = this.candleSeries.createPriceLine({
                price: buyOrder.trigger_price,
                color: "#00d2ff", // Ciano
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: `Trailing Buy @ $${buyOrder.trigger_price.toFixed(2)}`
            });
        }
    }
}
