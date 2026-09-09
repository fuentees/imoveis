# Deixar o bot rodando

## 1. Credenciais do Telegram

Para tarefa agendada, o mais simples é pôr o token no `config.yaml`
(ele está no `.gitignore`, não vai pro Git):

```yaml
telegram:
  token: "123456:ABC-DEF..."       # do @BotFather
  chat_id: "12345678"              # de @userinfobot
```

Teste antes de agendar:

```bash
python main.py --once --dry-run    # não envia, só imprime
python main.py --once              # envia de verdade um ciclo
```

## 2. Online, sem máquina local — GitHub Actions

Já vem pronto em `.github/workflows/bot.yml`: roda `main.py --once` a cada 3h,
sem servidor. Você só precisa dar os secrets:

1. No repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Crie dois:
   - `TELEGRAM_TOKEN`  → o token do @BotFather
   - `TELEGRAM_CHAT_ID` → seu chat id (@userinfobot)
2. Aba **Actions** → workflow **bot-imoveis** → **Run workflow** pra testar agora.
   Depois disso ele roda sozinho no cron.

Como funciona:
- a config vem de `config.example.yaml` (copiada pra `config.yaml` no runner);
  as credenciais vêm dos secrets (variável de ambiente vence o arquivo).
- o `imoveis.db` **persiste** numa branch órfã `data` (o workflow puxa antes de
  rodar e empurra depois). Não polui o histórico da `main`.
- o `bot.log` de cada ciclo fica em **Actions → run → Artifacts** por 7 dias.

Detalhes/limites:
- horário do cron é **UTC** e o GitHub pode atrasar 5–15 min sob carga.
- repositório **público** = minutos de Actions ilimitados (este é público).
- workflow agendado **pausa após 60 dias sem commit na `main`** — o GitHub
  manda e-mail; é só reativar (ou commitar algo).
- upgrade limpo do estado: trocar a branch `data` por um SQLite hospedado
  (Turso tem free tier) — mexe só no `storage.py`.

## 3. Windows — Task Scheduler

Roda `run.bat` (= `main.py --once`) de tempos em tempos. Sobrevive a reboot.

1. **Iniciar → "Agendador de Tarefas" → Criar Tarefa** (não "Tarefa Básica").
2. **Geral:** nome `bot-imoveis`. Marque **"Executar estando o usuário
   conectado ou não"** e **"Executar com privilégios mais altos"**.
3. **Disparadores → Novo:** "Diariamente", repetir a cada **3 horas**,
   por "1 dia" (indefinidamente).
4. **Ações → Nova:**
   - Programa: `C:\Users\vfcarvalho\bot-garimpeiro-imoveis\run.bat`
   - Iniciar em: `C:\Users\vfcarvalho\bot-garimpeiro-imoveis`
5. **Condições:** desmarque "Iniciar a tarefa apenas se o computador
   estiver ligado na tomada" se for notebook.
6. OK (pede a senha do Windows).

Para conferir: aba **Histórico** da tarefa, e o `bot.log` na pasta do projeto.
O `intervalo_minutos` do `config.yaml` é ignorado nesse modo — quem agenda é
o Windows.

## 4. Alternativa local — modo loop

```bash
python main.py --loop
```

Fica rodando e re-varre a cada `agendamento.intervalo_minutos`. Simples, mas
**para se o terminal fechar ou o PC reiniciar**. Para deixar 24/7 assim, use
uma máquina sempre ligada (Raspberry Pi, VPS, notebook velho) com `systemd`
ou `cron` chamando `python main.py --once`.

## 5. Primeira semana

- Rode em `--loop` ou agendado e **confira na mão** os alertas que chegam.
- Ajuste no `config.yaml`: `limiar_desconto`, `min_amostra`, `exigir_keyword`.
- Olhe o `bot.log` de vez em quando: linha `[!]` = site que quebrou
  (seletor desatualizado), `[robots]` = bloqueado por robots.txt.
