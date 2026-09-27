# ⚡ BOT DE MONITORAMENTO E TRADING QUANTITATIVO (BINANCE)

Aplicação de monitoramento em tempo real, backtesting dinâmico e execução simulada (**Paper Trading**) de criptoativos integrada diretamente à API e WebSockets da Binance.

Construída com **Python 3.11+, Flask, Flask-SocketIO, SQLAlchemy, PostgreSQL, Pandas/NumPy e TradingView Lightweight Charts**.

---

## 🚀 1. Funcionalidades Principais

### 1.1 Interface & Dashboard (TradingView Lightweight Charts)
* **Gráfico em Tempo Real:** Streaming de candles da Binance via WebSockets para múltiplos pares (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`) e timeframes (`1m`, `5m`, `15m`, `1h`).
* **Bandas de Bollinger Sobrepostas:** Média central (SMA 20) com desvio padrão de 2 sigmas idênticos à Binance.
* **Subgráfico de RSI (14):** Cálculo exato de J. Welles Wilder com linhas de sobrecompra (70) e sobrevenda (30). Sincronizado dinamicamente em escala de tempo com o gráfico principal.
* **Linhas de Preço Dinâmicas no Gráfico:**
  * Linha Ciano tracejada: Ordem de **Trailing Buy** ativa.
  * Linha Vermelha tracejada: Ordem de **Trailing Stop** ativa.
  * Linha Dourada sólida: Preço médio de entrada da **Posição Aberta**.

### 1.2 Regras de Negócio e Motores de Execução
* **Trailing Buy (Entrada Reversa Dinâmica):**
  * Disparado por condição de sobrevenda (RSI $\le 30$ e/ou Preço $\le$ Banda Inferior).
  * Rastreia a mínima $P_{min}$ e arma o gatilho em $P_{buy} = P_{min} \times (1 + \text{trailing\_buy\_delta})$.
  * **Histerese:** Se o preço continuar caindo mais que o limiar de tolerância, recalcula $P_{min}$ e puxa $P_{buy}$ para baixo sem enviar ordens repetitivas desnecessárias.
  * **Multiplicador de Queda (Martingale / Preço Médio Ponderado):** Se o preço de entrada cair além de um limiar configurado (ex: > 1.5%), aumenta proporcionalmente o volume em USDT da compra para melhorar o preço médio.
  * Executa compra simulada a mercado imediatamente ao cruzar $P_{buy}$.
* **Trailing Stop (Proteção e Saída Lucrativa):**
  * Inicializado em $P_{stop} = P_{compra} \times (1 - \text{trailing\_stop\_delta})$.
  * Conforme o ativo sobe, rastreia $P_{max}$ e eleva $P_{stop}$ respeitando a histerese de subida.
  * **Trava de descida:** O $P_{stop}$ **nunca desce**, apenas sobe ou permanece fixo.
  * Se o preço tocar ou cruzar $P_{stop}$ (ou gap down), encerra a posição a mercado imediatamente e registra no histórico de trades.

### 1.3 Gestão de Risco e Segurança
* **Paper Trading Ativo por Padrão:** Não arrisca fundos reais; simula ordens e controle de caixa a mercado em tempo real.
* **Validação de Limites de Capital:**
  * Alocação Base por Ordem em USDT.
  * Alocação Máxima Total por Ativo.
  * Capital Máximo Total em Aberto.
* **Proteção contra quedas bruscas e verificação de saldo.**

---

## 🗄️ 2. Banco de Dados (PostgreSQL + Fallback Seguro)

O sistema foi desenhado para utilizar **PostgreSQL** como banco principal, com tolerância a falhas:

1. **PostgreSQL Primário:** Configurado via variável `DATABASE_URL` no `.env` ou `docker-compose.yml`.
2. **Fallback Seguro para SQLite:** Caso o servidor PostgreSQL não esteja acessível no momento da inicialização, o sistema realiza um fallback transparente para SQLite local (`crypto_bot.db`), garantindo que o bot e o dashboard operem imediatamente sem interrupções.

### Subindo a Aplicação Completa via Docker Compose:
```bash
docker compose up -d --build
```
A aplicação e o PostgreSQL 16 serão iniciados juntos, com volumes persistentes (`postgres_data` e `bot_data`) e healthcheck ativo.

> 💡 **Deploy no ZimaOS / Portainer / Homelab:** Consulte o guia passo a passo em [DEPLOY_ZIMAOS_PORTAINER.md](file:///c:/Users/lcruz/Desktop/%23ProjDev/Python/BOT_BINANCE_0926/DEPLOY_ZIMAOS_PORTAINER.md).

---

## 🛠️ 3. Como Executar Localmente

### 3.1 Instalação das Dependências
No ambiente virtual (`.venv`):
```bash
pip install -r requirements.txt
```

### 3.2 Inicialização do Servidor
```bash
python app.py
```
Acesse o painel no navegador: **http://127.0.0.1:5000**

### 3.3 Execução dos Testes Automatizados
Para rodar a suíte de testes de cálculo de indicadores, estratégias e ordens:
```bash
python test_system.py
```

---

## 📂 4. Estrutura do Projeto

```text
BOT_BINANCE_0926/
│
├── app.py                     # Entry point Flask + WebSocket + REST API
├── config.py                  # Parâmetros de ambiente, DB e defaults técnicos
├── requirements.txt           # Dependências do projeto
├── Dockerfile                 # Imagem Docker otimizada para Linux/ZimaOS
├── docker-compose.yml         # Stack Docker com Bot + PostgreSQL 16
├── .dockerignore              # Arquivos excluídos da compilação da imagem
├── DEPLOY_ZIMAOS_PORTAINER.md # Guia completo para Homelab / ZimaOS / Portainer
├── .env / .env.example        # Variáveis de ambiente
├── test_system.py             # Testes unitários e de integração
│
├── database/
│   ├── models.py              # Models: Asset, BotConfig, Position, Order, TradeLog
│   └── db_handler.py          # Gerenciador de conexão PostgreSQL/SQLite e CRUD
│
├── core/
│   ├── indicators.py          # Cálculo de RSI (Wilder) e Bollinger Bands padrão Binance
│   ├── market_stream.py       # Conexão WebSocket combinada com Binance + REST API
│   ├── strategy_engine.py     # Lógica matemática de Trailing Buy e Trailing Stop
│   └── order_manager.py       # Paper Trading, alocação de capital e gestão de risco
│
├── static/
│   ├── js/
│   │   ├── chart.js           # TradingView Lightweight Charts + Subgráfico RSI sincronizado
│   │   └── app.js             # WebSocket Socket.IO cliente, tabelas e reatividade
│   └── css/
│       └── output.css         # Design fintech moderno dark mode
│
└── templates/
    └── index.html             # Dashboard completo com gráficos, métricas e tabelas
```
