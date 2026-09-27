# 🚀 Guia de Deploy no Homelab (ZimaOS + Portainer)

Este guia orienta o deploy em produção do **Binance Quantitative Bot** no seu **ZimaOS** utilizando o **Portainer**, conectado diretamente à sua instância existente do **PostgreSQL** no homelab (`192.168.100.50:5432 / postgresql`).

---

## 🗄️ Dados de Conexão com o Homelab

- **IP do PostgreSQL**: `192.168.100.50`
- **Porta**: `5432`
- **Banco / Instância**: `postgresql`
- **Aplicação**: Rodando em produção com **Gunicorn (gthread)** + Flask-SocketIO na porta `5000`.

---

## 📁 Arquivos Inclusos no Projeto

- [`Dockerfile`](file:///c:/Users/lcruz/Desktop/%23ProjDev/Python/BOT_BINANCE_0926/Dockerfile): Servidor WSGI de produção `Gunicorn` com worker `gthread` (multithreaded para WebSocket Binance e ticks assíncronos), com healthcheck nativo.
- [`docker-compose.yml`](file:///c:/Users/lcruz/Desktop/%23ProjDev/Python/BOT_BINANCE_0926/docker-compose.yml): Orquestra o container `binance_bot_app` apontando para o PostgreSQL em `192.168.100.50`.
- [`.dockerignore`](file:///c:/Users/lcruz/Desktop/%23ProjDev/Python/BOT_BINANCE_0926/.dockerignore): Exclui `.venv`, `.git`, caches e `.env` para segurança e builds rápidos.
- [`.env.example`](file:///c:/Users/lcruz/Desktop/%23ProjDev/Python/BOT_BINANCE_0926/.env.example): Modelo das variáveis de ambiente.

---

## ⚙️ Passo a Passo para o Deploy no Portainer

### 🌟 Método 1: Via Portainer Stacks com Repositório Git (Recomendado)

Como o repositório está em `https://github.com/lcruz2214/bot_bin_0926.git`:

1. **Acesse o Portainer** no ZimaOS pelo navegador:
   - `http://<IP-DO-ZIMAOS>:9000` (ou a porta do seu Portainer).
2. No menu lateral, acesse **Stacks** e clique em **+ Add stack**.
3. Defina um nome para a stack, por exemplo: `binance-bot`.
4. Em **Build method**, selecione **Repository**.
5. Preencha os campos:
   - **Repository URL**: `https://github.com/lcruz2214/bot_bin_0926.git`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`
   - Se o repositório for privado, ative **Authentication** e insira seu usuário do GitHub e seu **Personal Access Token**.
6. **Variáveis de Ambiente (Environment variables)**:
   - Se precisar ajustar o usuário ou senha do PostgreSQL (caso não seja `postgres` / `postgres`), adicione as variáveis:
     - `POSTGRES_USER`: seu usuário do banco
     - `POSTGRES_PASSWORD`: sua senha do banco
     - `POSTGRES_HOST`: `192.168.100.50`
     - `POSTGRES_DB`: `postgresql`
     - `BINANCE_API_KEY`: sua chave de API (opcional se for modo Paper)
     - `BINANCE_API_SECRET`: seu segredo de API (opcional se for modo Paper)
7. Clique em **Deploy the stack**.
8. O Portainer fará o clone, compilará o Dockerfile com Gunicorn e subirá a aplicação conectada ao PostgreSQL!

---

### 📂 Método 2: Via Pasta Local no ZimaOS (Terminal ou Samba)

1. Conecte via SSH ao ZimaOS ou clone diretamente:
   ```bash
   cd /DATA/AppData
   git clone https://github.com/lcruz2214/bot_bin_0926.git binance-bot
   cd binance-bot
   docker compose up -d --build
   ```
2. A stack aparecerá automaticamente na lista de containers do Portainer.

---

## 🌐 Acessando a Aplicação

Assim que o container estiver no estado **healthy**:
- Abra seu navegador em:
  ```text
  http://<IP-DO-SEU-ZIMAOS>:5000
  ```
- O terminal exibirá o badge `PostgreSQL` conectado diretamente à sua instância `192.168.100.50` e o streaming dos candles da Binance em tempo real!
