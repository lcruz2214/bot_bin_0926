# PROMPT DE DESENVOLVIMENTO: BOT DE MONITORAMENTO E TRADING DE CRIPTO (FLASK + WEBSOCKETS + TRADINGVIEW LIGHTWEIGHT CHARTS)

Você é um engenheiro de software sênior especialista em Python, sistemas assíncronos para negociação de alta frequência e arquitetura web. Desenvolva uma aplicação completa de monitoramento, backtesting e execução simulada (paper trading) de criptoativos integrada à API da Binance.

---

## 1. STACK TECNOLÓGICA
* **Backend:** Python 3.11+, Flask, Flask-SocketIO (para streaming em tempo real), SQLAlchemy (SQLite ou PostgreSQL), Celery ou APScheduler/Threads para o motor de loop contínuo.
* **Cálculo Técnico:** Pandas-TA ou TA-Lib em Python, garantindo cálculos idênticos à Binance (RSI com suavização Wilder e Bollinger Bands padrão com SMA de 20 períodos e 2 desvios padrão).
* **Frontend:** HTML5, TailwindCSS, Vanilla JavaScript / Alpine.js e TradingView Lightweight Charts (biblioteca oficial e leve para plotar candles, BB e subgráfico de RSI).
* **Conexão Cripto:** Binance WebSocket Streams (`<symbol>@kline_<interval>` e `<symbol>@ticker`) via `python-binance` ou `websockets`.

---

## 2. ARQUITETURA DO SISTEMA E INTERFACE

### 2.1 Interface (Dashboard)
1. **Painel de Ativos:** Dropdown/busca para alternar entre múltiplos pares (ex: BTCUSDT, ETHUSDT, SOLUSDT) e alternar timeframes (1m, 5m, 15m, 1h).
2. **Área Gráfica:** 
   * Gráfico de Candles em tempo real (Lightweight Charts).
   * Indicador sobreposto: Bandas de Bollinger (Média central, Banda Superior e Banda Inferior).
   * Subgráfico inferior: RSI (14) com linhas de sobrevenda (30) e sobrecompra (70) customizáveis.
   * Linhas horizontais dinâmicas no gráfico mostrando: Ordens ativas de Trailing Buy, Ordens de Trailing Stop e Preço Médio de Posição.
3. **Painel de Configurações Técnicas e de Risco (editáveis por ativo e globais):**
   * Período do RSI e Nível de Sobrevenda.
   * Período da Média e Multiplicador de Desvio da Banda de Bollinger.
   * Gatilho de Ativação: `[RSI]` OU `[Banda Inferior]` OU `[Ambos simultaneamente]`.
   * Delta do Trailing Buy (% de distância do preço de compra em relação à mínima/referência).
   * Histerese de Ajuste de Compra (% de afastamento para reajuste de ordem).
   * Delta do Trailing Stop (% de recuo permitido antes da venda a mercado).
   * Histerese de Ajuste de Venda (% de avanço do preço para subir o stop).
   * Alocação Financeira: Valor base por ordem em USDT, Alocação Máxima Total por Ativo e Capital Máximo Total em Aberto.
   * Multiplicador de Queda: se o preço de gatilho cair mais de $X\%$, aumentar o volume (quantidade) da próxima compra para manter o peso financeiro ou fazer martingale/preço médio ponderado.
4. **Tabela de Acompanhamento (Live Orders & Trades):**
   * Lista de ordens ativas (Trailing Buy e Trailing Stop).
   * Registro histórico de trades (Preço de compra, Preço de venda, Quantidade, PnL em USDT e %, Motivo da saída).

---

## 3. REGRAS DE NEGÓCIO E MOTORES DE EXECUÇÃO

### 3.1 Gatilho e Mecânica do Trailing Buy (Entrada Reversa Dinâmica)
1. **Ativação:** O ativo entra em condição de sobrevenda (Preço $\le$ Banda Inferior de Bollinger e/ou RSI $\le$ Limite de Sobrevenda).
2. **Criação da Ordem Virtual:**
   * Registra a mínima do preço de referência ($P_{min}$).
   * Define o gatilho de compra em: $P_{buy} = P_{min} \times (1 + \text{trailing\_buy\_delta})$.
3. **Lógica de Não Repetição / Histerese:**
   * Se o preço continuar caindo e a distância $(P_{buy} - P_{atual}) / P_{atual} \ge \text{histerese}$, reajusta $P_{min} = P_{atual}$ e recalcula $P_{buy}$ para baixo.
   * Evitar envio excessivo de atualizações/ordens se o preço estiver dentro da faixa de tolerância.
4. **Ajuste de Volume por Preço Baixo:**
   * Se o preço de entrada cair significativamente em relação ao momento do gatilho inicial, a quantidade de moedas ($Qtd$) deve ser ajustada para cima ($Qtd = \text{Valor\_Em\_Dolar\_Alocado} / P_{buy}$), garantindo que a ordem respeite o capital planejado em USDT ou aumente a proporção conforme configurado.
5. **Execução:** Se o preço repicar e atingir ou ultrapassar $P_{buy}$, a ordem simulada de compra é preenchida a mercado.

### 3.2 Mecânica do Trailing Stop e Stop Loss Emergencial (Saída)
1. **Inicialização do Stop:** Assim que a compra é confirmada a $P_{compra}$, inicializa o stop móvel a $P_{stop} = P_{compra} \times (1 - \text{trailing\_stop\_delta})$.
2. **Rastreamento de Máximas (Trailing):**
   * Conforme o ativo sobe, armazena $P_{max}$.
   * Se o preço subir e a distância $(P_{atual} - P_{stop}) / P_{stop} \ge \text{histerese}$, eleva $P_{stop} = P_{max} \times (1 - \text{trailing\_stop\_delta})$.
   * O $P_{stop}$ **nunca desce**, apenas sobe ou permanece fixo.
3. **Disparo de Saída:**
   * Se $P_{atual} \le P_{stop}$ ou se ocorrer um gap descendente no tick do candle onde $P_{atual} < P_{stop}$, o sistema fecha a posição imediatamente com uma ordem de venda a mercado no preço do tick recebido.
   * Notifica a interface via WebSocket e atualiza o histórico de PnL.

---

## 4. ESTRUTURA DO CÓDIGO SUGERIDA

```text
crypto_bot/
│
├── app.py                     # Entry point Flask + inicialização Flask-SocketIO
├── config.py                  # Parâmetros de API, banco de dados e defaults
├── database/
│   ├── models.py              # Models: Asset, Config, Position, Order, TradeLog
│   └── db_handler.py          # Operações de CRUD
│
├── core/
│   ├── market_stream.py       # Conexão WebSocket com Binance (Tickers/Klines)
│   ├── indicators.py          # Cálculo de RSI (Wilder) e Bollinger Bands
│   ├── strategy_engine.py     # Lógica matemática de Trailing Buy e Trailing Stop
│   └── order_manager.py       # Gerenciamento de posições, limites de capital e paper trading
│
├── static/
│   ├── js/
│   │   ├── chart.js           # Renderização e atualização do TradingView Chart
│   │   └── app.js             # Conexão WebSocket cliente, eventos e DOM
│   └── css/
│       └── output.css         # Tailwind compilado ou importação via CDN
│
└── templates/
    └── index.html             # Painel completo com gráficos, formulários e ordens