# Requisitos de Implementação, Revisão e Ajustes

## Bot de Monitoramento e Trading Quantitativo — Binance

## 1. Objetivo

Este documento define os requisitos para revisão, implementação e/ou ajuste dos seguintes componentes do sistema:

1. Controle de aumento de exposição após quedas de preço;
2. Máquina de estados da posição;
3. Idempotência de ordens;
4. Reconexão e recuperação do WebSocket;
5. Política de persistência PostgreSQL/SQLite;
6. Gerenciador de recuperação;
7. Persistência do estado das estratégias de Trailing Buy e Trailing Stop;
8. Separação entre Ordem, Execução e Trade;
9. Registro de eventos e auditoria;
10. Modo "Explicar" para demonstrar por que o sistema tomou determinada decisão;
11. Mecanismo de parada de emergência ("Kill Switch").

O objetivo principal é aumentar a **confiabilidade, rastreabilidade, capacidade de recuperação e segurança operacional** do bot, principalmente em situações de falha de rede, reinicialização do processo, duplicidade de mensagens, indisponibilidade do banco de dados e execução repetida de comandos.

---

# 2. Princípios gerais

## RF-GERAL-001 — Persistência como fonte de verdade

O estado operacional do sistema não deverá depender exclusivamente de informações mantidas em memória.

Informações necessárias para recuperação deverão ser persistidas no banco de dados, incluindo, quando aplicável:

* posição;
* quantidade;
* preço médio;
* estado da posição;
* estado da ordem;
* preço mínimo rastreado;
* preço máximo rastreado;
* preço de gatilho;
* preço do Trailing Stop;
* configuração utilizada;
* identificadores das ordens;
* eventos relevantes;
* motivo das decisões.

---

## RF-GERAL-002 — Operações críticas deverão ser recuperáveis

Após uma reinicialização inesperada, o sistema deverá ser capaz de reconstruir seu estado operacional a partir do banco de dados e, quando necessário, consultar novamente a Binance para validar o estado real.

---

## RF-GERAL-003 — Nenhuma operação deverá gerar duplicidade por repetição de processamento

Mensagens, eventos, comandos ou tentativas de envio poderão ser processados novamente sem provocar uma segunda execução indevida.

Esse requisito deverá ser atendido por meio de **idempotência**.

---

# 3. Controle de aumento de exposição após queda

## RF-RISCO-001 — Substituir a denominação genérica "Martingale"

O sistema deverá evitar utilizar "Martingale" como denominação principal da funcionalidade.

A funcionalidade deverá ser denominada preferencialmente:

> **Aumento Progressivo de Exposição**

ou:

> **Escalonamento de Entrada**

O termo "Martingale" poderá aparecer na documentação como referência ao conceito utilizado, mas deverá ficar explícito que o sistema possui limites de exposição.

---

## RF-RISCO-002 — Configuração da ordem inicial

O sistema deverá possuir um valor configurável para a primeira entrada:

```text
valor_ordem_inicial_usdt
```

Exemplo:

```text
valor_ordem_inicial_usdt = 100
```

---

## RF-RISCO-003 — Multiplicador de entrada

O sistema deverá permitir configurar um multiplicador para entradas adicionais.

Exemplo:

```text
multiplicador_entrada = 1,5
```

Resultado:

```text
Entrada 1 = 100 USDT
Entrada 2 = 150 USDT
Entrada 3 = 225 USDT
Entrada 4 = 337,50 USDT
```

---

## RF-RISCO-004 — Limite máximo por entrada

Nenhuma entrada poderá ultrapassar:

```text
valor_maximo_por_entrada_usdt
```

Mesmo que o cálculo do multiplicador produza valor superior.

---

## RF-RISCO-005 — Limite máximo por posição

A soma das entradas de um determinado ativo não poderá ultrapassar:

```text
exposicao_maxima_por_ativo_usdt
```

Exemplo:

```text
Limite = 500 USDT

Entrada 1 = 100
Entrada 2 = 150
Entrada 3 = 225

Total = 475 USDT

Nova entrada = BLOQUEADA
```

---

## RF-RISCO-006 — Limite máximo de entradas

Deverá existir:

```text
quantidade_maxima_de_entradas
```

Exemplo:

```text
máximo = 5 entradas
```

Após atingir o limite, nenhuma nova entrada poderá ser realizada automaticamente.

---

## RF-RISCO-007 — Condição mínima para nova entrada

Uma nova entrada somente poderá ocorrer quando o preço apresentar uma queda mínima configurada em relação à referência da entrada anterior ou ao preço médio, conforme a estratégia definida.

Exemplo:

```text
queda_minima_nova_entrada = 1,5%
```

---

## RF-RISCO-008 — Registro da justificativa da nova entrada

Cada entrada adicional deverá registrar:

* motivo;
* preço no momento;
* preço de referência;
* percentual de queda;
* valor da entrada;
* número da entrada;
* multiplicador utilizado;
* exposição acumulada;
* limite máximo permitido.

---

## CA-RISCO-001 — Critério de aceite

Dado:

```text
exposição máxima = 500 USDT
```

Quando o cálculo de uma nova entrada resultar em exposição superior a 500 USDT,

Então:

```text
a entrada deverá ser recusada;
nenhuma ordem deverá ser enviada;
o motivo deverá ser registrado;
o evento deverá aparecer no histórico de eventos.
```

---

# 4. Máquina de estados da posição

## RF-ESTADO-001 — Implementar estados explícitos

Cada posição deverá possuir um estado persistido.

Estados mínimos:

```text
SEM_POSICAO
AGUARDANDO_ENTRADA
ENTRADA_DISPARADA
ABERTA
PROTECAO_ATIVA
SAIDA_DISPARADA
ENCERRANDO
ENCERRADA
ERRO
RECUPERACAO
```

Os nomes apresentados acima deverão ser utilizados preferencialmente em PT-BR no dashboard e documentação.

No código, poderá ser utilizado um identificador técnico equivalente.

---

## RF-ESTADO-002 — Transições controladas

As mudanças de estado deverão obedecer a transições válidas.

Exemplo:

```text
SEM_POSICAO
      ↓
AGUARDANDO_ENTRADA
      ↓
ENTRADA_DISPARADA
      ↓
ABERTA
      ↓
PROTECAO_ATIVA
      ↓
SAIDA_DISPARADA
      ↓
ENCERRANDO
      ↓
ENCERRADA
```

Não deverá ser permitido alterar arbitrariamente:

```text
SEM_POSICAO → ENCERRADA
```

sem uma justificativa ou evento compatível.

---

## RF-ESTADO-003 — Registro das transições

Toda mudança de estado deverá registrar:

* estado anterior;
* novo estado;
* data/hora;
* motivo;
* preço;
* quantidade;
* identificador da posição;
* identificador da ordem relacionada, quando aplicável.

---

## RF-ESTADO-004 — Estado persistente

O estado atual deverá estar armazenado no banco de dados.

Após reinicialização, o sistema deverá recuperar o estado da posição.

---

## CA-ESTADO-001 — Recuperação

Se o processo for encerrado enquanto existir uma posição:

```text
estado = PROTECAO_ATIVA
trailing_stop = 100.50
preco_maximo = 102.00
```

Após reiniciar:

```text
estado = PROTECAO_ATIVA
trailing_stop = 100.50
preco_maximo = 102.00
```

Os valores deverão ser recuperados sem reinicialização da estratégia.

---

# 5. Idempotência

## RF-IDEMP-001 — Identificador único de operação

Toda ordem deverá possuir um identificador único de negócio, por exemplo:

```text
id_ordem
```

E deverá existir um identificador para comunicação externa:

```text
id_ordem_cliente
```

ou equivalente disponibilizado pela Binance.

---

## RF-IDEMP-002 — Verificação antes do envio

Antes de enviar uma nova ordem, o sistema deverá verificar se já existe uma ordem equivalente em estado:

```text
ENVIADA
CONFIRMADA
EXECUTADA
EM_PROCESSAMENTO
```

Caso exista, uma nova ordem não deverá ser criada.

---

## RF-IDEMP-003 — Reprocessamento seguro

Se uma mensagem for processada duas vezes:

```text
Mensagem #123
Mensagem #123 novamente
```

o resultado final deverá ser equivalente ao processamento de apenas uma mensagem.

---

## RF-IDEMP-004 — Timeout não significa necessariamente falha

Caso o sistema envie uma ordem e não receba resposta dentro do prazo:

```text
ENVIO
 ↓
TIMEOUT
```

não deverá assumir automaticamente:

```text
ORDEM NÃO EXECUTADA
```

Antes de reenviar, deverá consultar o estado da ordem, quando possível.

---

## RF-IDEMP-005 — Proteção contra compra duplicada

O sistema deverá impedir situações como:

```text
BUY enviada
    ↓
Binance executou
    ↓
resposta perdida
    ↓
bot reenviou BUY
    ↓
segunda compra indevida
```

---

# 6. Reconexão do WebSocket

## RF-WS-001 — Detecção de desconexão

O sistema deverá detectar:

* encerramento da conexão;
* timeout;
* ausência de mensagens;
* erro de protocolo;
* erro de autenticação;
* falha de rede.

---

## RF-WS-002 — Reconexão automática

O sistema deverá tentar reconectar automaticamente.

Deverá utilizar intervalo progressivo entre tentativas, preferencialmente com:

```text
espera inicial
+
aumento progressivo
+
limite máximo
```

---

## RF-WS-003 — Limite de tentativas

O sistema deverá possuir configuração para:

```text
maximo_tentativas_reconexao
```

ou permitir tentativas contínuas controladas.

---

## RF-WS-004 — Recuperação de dados perdidos

Após reconectar, o sistema deverá verificar se houve perda de dados durante o período desconectado.

Quando necessário, deverá utilizar a API REST para recuperar os dados faltantes.

---

## RF-WS-005 — Validação após reconexão

Após reconectar, o sistema deverá validar:

* último preço recebido;
* último candle;
* horário da última atualização;
* posição atual;
* ordens pendentes;
* estado da estratégia.

---

## RF-WS-006 — Estado do WebSocket

O dashboard deverá informar:

```text
CONECTADO
RECONectando
DESCONECTADO
RECUPERANDO
```

Preferencialmente com indicação visual.

---

## CA-WS-001 — Critério de aceite

Quando a conexão WebSocket for interrompida:

1. o sistema deverá detectar a interrupção;
2. registrar o evento;
3. alterar o estado operacional;
4. iniciar reconexão;
5. recuperar dados perdidos;
6. validar o estado atual;
7. retornar à operação normal.

---

# 7. PostgreSQL e SQLite

## RF-DB-001 — PostgreSQL como banco de produção

O PostgreSQL deverá ser considerado o banco oficial para:

* produção;
* Paper Trading persistente;
* histórico;
* posições;
* ordens;
* trades;
* eventos;
* configurações.

---

## RF-DB-002 — SQLite não deverá assumir operações automaticamente em produção

O sistema não deverá trocar silenciosamente de PostgreSQL para SQLite durante uma falha.

A troca automática poderá gerar divergência de estado.

---

## RF-DB-003 — Modo SQLite para desenvolvimento

SQLite poderá ser utilizado explicitamente quando:

```text
AMBIENTE = DESENVOLVIMENTO
```

ou mediante configuração específica.

---

## RF-DB-004 — Falha do banco em produção

Se o PostgreSQL ficar indisponível:

```text
PostgreSQL indisponível
        ↓
SAFE_MODE
```

O sistema deverá:

* interromper novas entradas;
* preservar informações em memória somente quando necessário;
* tentar reconectar;
* registrar a falha;
* validar o estado antes de voltar à operação.

---

## RF-DB-005 — Retorno do banco

Após restabelecer a conexão:

```text
Banco recuperado
      ↓
validar estado
      ↓
sincronizar
      ↓
verificar ordens
      ↓
verificar posições
      ↓
sair do SAFE_MODE
```

---

# 8. Gerenciador de Recuperação

## RF-REC-001 — Criar componente de recuperação

Deverá existir um componente específico responsável pela recuperação do sistema.

Sugestão de nome:

```text
core/recovery_manager.py
```

Nome funcional:

> **Gerenciador de Recuperação**

---

## RF-REC-002 — Recuperação na inicialização

Ao iniciar, o sistema deverá verificar:

* posições abertas;
* ordens pendentes;
* ordens executadas recentemente;
* estados das estratégias;
* Trailing Buy ativo;
* Trailing Stop ativo;
* último evento processado;
* configuração utilizada.

---

## RF-REC-003 — Reconciliação com a Binance

Quando aplicável, o sistema deverá comparar:

```text
Estado local
      VS
Estado da Binance
```

Exemplo:

```text
Banco:
BTC = 0,010

Binance:
BTC = 0,012
```

Essa divergência deverá ser identificada e registrada.

---

## RF-REC-004 — Não assumir automaticamente qual estado está correto

Divergências críticas deverão colocar o sistema em:

```text
MODO_SEGURO
```

até que a situação seja resolvida ou validada pela rotina de recuperação.

---

## RF-REC-005 — Recuperação após queda do processo

O sistema deverá ser capaz de continuar uma posição existente sem criar uma nova posição ou perder o estado do Trailing Stop.

---

# 9. Persistência do estado do Trailing

## RF-TRAIL-001 — Persistir Trailing Buy

Deverão ser persistidos, quando aplicáveis:

```text
preco_minimo
preco_gatilho_compra
delta_trailing_compra
estado_trailing_compra
data_inicio
data_atualizacao
```

---

## RF-TRAIL-002 — Persistir Trailing Stop

Deverão ser persistidos:

```text
preco_maximo
preco_stop
delta_trailing_stop
estado_trailing_stop
data_inicio
data_atualizacao
```

---

## RF-TRAIL-003 — Trailing Stop não poderá retroceder

A regra deverá ser garantida tanto em memória quanto no banco:

```text
novo_stop >= stop_anterior
```

Nunca:

```text
novo_stop < stop_anterior
```

---

## RF-TRAIL-004 — Atualização transacional

Alterações críticas do estado do trailing e eventos associados deverão ser persistidas de maneira consistente.

---

## RF-TRAIL-005 — Recuperação do Trailing

Após reinicialização, o sistema deverá recuperar os valores persistidos e continuar o acompanhamento.

---

# 10. Separação entre Ordem, Execução, Posição e Trade

## RF-TRADE-001 — Entidades independentes

O sistema deverá diferenciar:

### Ordem

Intenção de comprar ou vender.

### Execução

Resultado efetivamente executado pela corretora.

### Posição

Quantidade atualmente mantida no ativo.

### Trade

Conjunto lógico de entradas e saída que representa uma operação completa.

---

## RF-TRADE-002 — Exemplo

Uma operação poderá ser:

```text
Trade #100
│
├── Ordem BUY #1
│      └── Execução #1
│
├── Ordem BUY #2
│      └── Execução #2
│
├── Ordem BUY #3
│      ├── Execução #3
│      └── Execução #4
│
└── Ordem SELL #4
       └── Execução #5
```

O sistema deverá conseguir relacionar todos esses registros ao mesmo Trade.

---

## RF-TRADE-003 — Histórico completo

Deverá ser possível reconstruir:

```text
Por que entrou?
Quanto comprou?
Quando comprou?
Por qual preço?
Quantas vezes aumentou a posição?
Quanto pagou de taxas?
Quando saiu?
Por qual motivo?
Qual foi o resultado?
```

---

# 11. Registro de Eventos — Event Log

## RF-EVENT-001 — Criar registro centralizado de eventos

O sistema deverá possuir um mecanismo de registro de eventos de negócio e operação.

Sugestão:

```text
event_log
```

---

## RF-EVENT-002 — Eventos mínimos

Deverão ser registrados eventos como:

```text
BOT_INICIADO
BOT_PARADO
WEBSOCKET_CONECTADO
WEBSOCKET_DESCONECTADO
WEBSOCKET_RECONECTADO

SINAL_COMPRA_GERADO
TRAILING_COMPRA_ARMADO
TRAILING_STOP_ARMADO

ORDEM_CRIADA
ORDEM_ENVIADA
ORDEM_CONFIRMADA
ORDEM_EXECUTADA
ORDEM_REJEITADA
ORDEM_TIMEOUT

POSICAO_ABERTA
POSICAO_AUMENTADA
POSICAO_REDUZIDA
POSICAO_ENCERRADA

BANCO_INDISPONIVEL
BANCO_RECUPERADO

MODO_SEGURO_ATIVADO
MODO_SEGURO_DESATIVADO

KILL_SWITCH_ATIVADO
KILL_SWITCH_DESATIVADO
```

---

## RF-EVENT-003 — Informações mínimas

Cada evento deverá possuir:

```text
id_evento
data_hora
tipo_evento
nivel
ativo
id_posicao
id_ordem
id_trade
mensagem
dados_adicionais
```

---

## RF-EVENT-004 — Dados adicionais estruturados

Informações específicas deverão ser armazenadas preferencialmente em estrutura JSON.

Exemplo:

```json
{
  "preco": 101250.50,
  "rsi": 28.42,
  "banda_inferior": 101300.20,
  "preco_gatilho": 101400.00,
  "motivo": "RSI abaixo de 30 e preço abaixo da banda inferior"
}
```

---

# 12. Modo "Explicar"

## RF-EXPLAIN-001 — Objetivo

O sistema deverá disponibilizar uma forma de explicar, em linguagem humana, o motivo de determinada decisão.

Exemplo:

> "A entrada foi habilitada porque o RSI estava em 28,4 e o preço estava abaixo da Banda de Bollinger inferior."

---

## RF-EXPLAIN-002 — Decisões explicáveis

O sistema deverá conseguir explicar, quando aplicável:

* por que uma entrada foi criada;
* por que uma entrada foi bloqueada;
* por que uma nova entrada foi realizada;
* por que uma saída foi acionada;
* por que uma ordem foi rejeitada;
* por que o Trailing Stop foi atualizado;
* por que o sistema entrou em Modo Seguro;
* por que o Kill Switch foi acionado.

---

## RF-EXPLAIN-003 — Informações utilizadas

A explicação deverá ser baseada nos valores efetivamente utilizados no momento da decisão.

Exemplo:

```text
RSI = 28,41
Limite de sobrevenda = 30

Preço = 101.200
Banda inferior = 101.350

Exposição atual = 300 USDT
Limite = 500 USDT

Decisão = ARMAR TRAILING BUY
```

---

## RF-EXPLAIN-004 — Não alterar lógica

O modo "Explicar" deverá somente interpretar e apresentar informações.

Ele não poderá alterar:

* posição;
* ordem;
* configuração;
* estratégia;
* estado do bot.

---

# 13. Kill Switch — Parada de Emergência

## RF-KILL-001 — Implementar parada de emergência

O sistema deverá possuir um mecanismo de parada de emergência.

Nome funcional:

> **Parada de Emergência**

---

## RF-KILL-002 — Ativação

A parada deverá poder ser acionada:

* pelo dashboard;
* por API protegida;
* por mecanismo administrativo;
* automaticamente em determinadas condições críticas, caso configurado.

---

## RF-KILL-003 — Comportamento mínimo

Ao ativar a Parada de Emergência:

```text
KILL SWITCH
     ↓
bloquear novas entradas
     ↓
cancelar ordens pendentes, quando aplicável
     ↓
impedir novas operações automáticas
     ↓
registrar evento
     ↓
manter monitoramento
```

---

## RF-KILL-004 — Não encerrar posição automaticamente por padrão

A Parada de Emergência deverá, por padrão, impedir novas operações, mas não deverá vender automaticamente todas as posições sem uma configuração explícita.

Deverão existir dois comportamentos configuráveis:

```text
PARADA_OPERACIONAL
```

e

```text
PARADA_COM_ENCERRAMENTO
```

---

## RF-KILL-005 — Confirmação

A ativação manual deverá exigir confirmação para reduzir o risco de acionamento acidental.

---

## RF-KILL-006 — Estado persistente

O estado da Parada de Emergência deverá ser persistido.

Após reiniciar o sistema:

```text
KILL_SWITCH = ATIVO
```

deverá continuar ativo.

---

## RF-KILL-007 — Reativação manual

A saída da Parada de Emergência deverá exigir uma ação explícita.

O sistema não deverá simplesmente voltar a operar sozinho após uma reinicialização.

---

# 14. Hierarquia dos modos operacionais

O sistema deverá possuir uma hierarquia clara:

```text
                ┌──────────────────┐
                │   EMERGENCIA     │
                │   KILL SWITCH    │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │   MODO SEGURO    │
                │   SAFE MODE      │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │     PAUSADO      │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │    OPERANDO      │
                └──────────────────┘
```

### OPERANDO

Operações automáticas permitidas.

### PAUSADO

Não abre novas operações, mas continua monitorando.

### MODO SEGURO

Utilizado diante de falhas críticas ou inconsistências.

### EMERGÊNCIA

Bloqueio operacional explícito e persistente.

---

# 15. Requisitos de auditoria

## RN-AUD-001

Toda operação financeira simulada ou real deverá ser rastreável.

Deverá ser possível relacionar:

```text
Decisão
   ↓
Evento
   ↓
Ordem
   ↓
Execução
   ↓
Posição
   ↓
Trade
```

---

## RN-AUD-002

Nenhuma informação histórica crítica deverá ser sobrescrita de forma que impeça a reconstrução dos acontecimentos.

---

# 16. Critérios gerais de aceite

A implementação será considerada adequada quando os seguintes cenários forem comprovados.

### Cenário 1 — Reinicialização

```text
Bot possui posição aberta
+
Trailing Stop ativo
+
processo é encerrado
+
bot é reiniciado
```

Resultado esperado:

```text
posição recuperada
trailing recuperado
estado recuperado
operação continua normalmente
```

---

### Cenário 2 — Ordem com resposta perdida

```text
ordem enviada
+
corretora executa
+
resposta não chega
+
sistema recebe timeout
```

Resultado esperado:

```text
sistema consulta o estado da ordem
+
identifica execução existente
+
não cria segunda ordem
```

---

### Cenário 3 — WebSocket interrompido

```text
WebSocket conectado
+
perda de conexão
```

Resultado esperado:

```text
falha identificada
+
evento registrado
+
reconexão automática
+
dados recuperados
+
estado validado
+
operação retomada
```

---

### Cenário 4 — Banco indisponível

```text
PostgreSQL indisponível
```

Resultado esperado:

```text
novas operações bloqueadas
+
MODO SEGURO
+
tentativas de reconexão
+
evento registrado
```

O sistema não deverá trocar silenciosamente para SQLite em produção.

---

### Cenário 5 — Limite de exposição

```text
exposição atual = 450 USDT
limite = 500 USDT
nova entrada = 100 USDT
```

Resultado:

```text
entrada bloqueada
```

---

### Cenário 6 — Trailing Stop

```text
Stop atual = 100
Preço sobe para 110
Novo Stop = 105
Preço cai para 108
```

Resultado:

```text
Stop continua em 105
```

O sistema nunca deverá reduzir o Stop para valor inferior a 105.

---

### Cenário 7 — Kill Switch

```text
Bot operando
+
Kill Switch ativado
```

Resultado:

```text
novas entradas bloqueadas
+
ordens pendentes tratadas conforme configuração
+
estado persistido
+
evento registrado
```

Após reinicialização:

```text
Kill Switch continua ativo
```

---

# 17. Ordem sugerida de implementação

A implementação deverá ser realizada preferencialmente nesta ordem:

```text
FASE 1
├── Máquina de estados
├── Persistência do estado
└── Separação Ordem / Execução / Trade

FASE 2
├── Idempotência
├── Event Log
└── Recovery Manager

FASE 3
├── Persistência do Trailing
├── Reconexão WebSocket
└── Reconciliação com Binance

FASE 4
├── Revisão do controle de exposição
├── Limites do escalonamento de entrada
└── Proteções do Gerenciador de Risco

FASE 5
├── Modo Explicar
├── Dashboard operacional
└── Parada de Emergência

FASE 6
└── Testes de falha e recuperação
```

---

# 18. Resultado esperado da arquitetura

Após a implementação, o fluxo esperado deverá ser aproximadamente:

```text
                 MERCADO
                    │
                    ▼
             WEBSOCKET / REST
                    │
                    ▼
              DADOS DE MERCADO
                    │
                    ▼
                INDICADORES
                    │
                    ▼
                ESTRATÉGIA
                    │
                    ▼
             DECISÃO DA ESTRATÉGIA
                    │
                    ▼
              GERENCIADOR DE RISCO
                    │
          ┌─────────┴─────────┐
          │                   │
       PERMITIDO            BLOQUEADO
          │                   │
          ▼                   ▼
    GERENCIADOR            EVENT LOG
      DE ORDENS
          │
          ▼
       IDEMPOTÊNCIA
          │
          ▼
       EXECUÇÃO
          │
          ▼
      POSIÇÃO / TRADE
          │
          ▼
       PERSISTÊNCIA
          │
          ▼
    EVENT LOG + EXPLICAÇÃO
```

Em caso de falha:

```text
              FALHA
                │
                ▼
        GERENCIADOR DE
          RECUPERAÇÃO
                │
        ┌───────┴────────┐
        │                │
     RECUPERÁVEL     INCONSISTÊNCIA
        │                │
        ▼                ▼
    RECUPERAR        MODO SEGURO
        │                │
        └───────┬────────┘
                ▼
          VALIDAR ESTADO
                │
                ▼
         RETOMAR OPERAÇÃO
```

---

# 19. Requisito final de segurança

O sistema deverá seguir o princípio:

> **Em caso de dúvida sobre o estado real de uma ordem, posição, saldo ou conexão, o sistema deverá preferir interromper novas operações e validar o estado antes de continuar.**

O comportamento desejado não é simplesmente:

```text
"deu erro → tentar novamente"
```

mas:

```text
"deu erro
→ descobrir o que realmente aconteceu
→ reconciliar estado
→ evitar duplicidade
→ somente então continuar"
```

Esse princípio deverá orientar principalmente o **Gerenciador de Ordens, Gerenciador de Recuperação, Idempotência, Persistência e Modo Seguro**.
